"""YooKassa mock: API v3 for Core API, a payment page for the buyer and a control panel for you.

    POST /v3/payments                 create (Idempotence-Key, capture=false, transfers)
    GET  /v3/payments/{id}            status check (Core API verifies every webhook with it, FR-22)
    POST /v3/payments/{id}/capture    take the held money
    POST /v3/payments/{id}/cancel     release the held money
    GET  /checkout/{id}               page of the buyer: success / bank declines / success without webhook
    GET  /admin                       control panel: payments, payouts, webhooks, faults

Faults ("break the next N requests") make the mock behave like a real service having a bad day:
timeout, 500, 429. A timeout is the tricky one: the payment IS created, only the answer is lost —
exactly the case Idempotence-Key exists for.
"""

import base64
import html
import logging
import os
import secrets
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from mock import payments, store, webhooks
from mock.payments import ApiProblem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("yookassa-mock")

@asynccontextmanager
async def lifespan(_: FastAPI):
    store.ensure_connected()  # tests connect to their own file beforehand
    yield


app = FastAPI(title="YooKassa mock", docs_url="/docs", lifespan=lifespan)

OPERATIONS = ("create", "get", "capture", "cancel")
FAULTS = ("timeout", "500", "429")


@app.exception_handler(ApiProblem)
def _problem(_: Request, error: ApiProblem) -> JSONResponse:
    return JSONResponse(error.body, status_code=error.status_code)


def _check_auth(authorization: str | None) -> None:
    """HTTP Basic: shopId and the secret key, as in YooKassa."""
    expected = f"{os.environ.get('YOOKASSA_SHOP_ID', '')}:{os.environ.get('YOOKASSA_SECRET_KEY', '')}"
    try:
        scheme, encoded = (authorization or "").split(" ", 1)
        given = base64.b64decode(encoded).decode()
    except ValueError:
        given, scheme = "", ""
    if scheme.lower() != "basic" or not secrets.compare_digest(given, expected):
        raise ApiProblem(401, "invalid_credentials", "Basic authentication with shopId and secret key is required")


def _run(operation: str, key: str | None, action) -> JSONResponse:
    """Idempotency + faults around one API operation."""
    if operation != "get":
        if not key:
            raise ApiProblem(400, "invalid_request", "Idempotence-Key header is required", "Idempotence-Key")
        stored = store.stored_answer(key, operation)
        if stored:
            log.info("%s: same Idempotence-Key %s -> stored answer", operation, key)
            return JSONResponse(stored[1], status_code=stored[0])

    fault = store.take_fault(operation)
    if fault == "500":
        raise ApiProblem(500, "internal_server_error", "Mock fault: internal error")
    if fault == "429":
        raise ApiProblem(429, "too_many_requests", "Mock fault: too many requests")

    try:
        status_code, body = 200, action()
    except ApiProblem as error:
        if error.status_code >= 500:
            raise
        status_code, body = error.status_code, error.body
    if operation != "get":
        store.store_answer(key, operation, status_code, body)  # type: ignore[arg-type]

    if fault == "timeout":
        # The work is done, the answer comes too late: the client has given up by then
        time.sleep(float(os.environ.get("MOCK_TIMEOUT_SECONDS", "15")))
    return JSONResponse(body, status_code=status_code)


@app.post("/v3/payments")
async def create_payment(request: Request, authorization: str | None = Header(None),
                         idempotence_key: str | None = Header(None, alias="Idempotence-Key")):
    _check_auth(authorization)
    body = await request.json()
    return await _in_thread(lambda: _run("create", idempotence_key, lambda: payments.create(body)))


@app.get("/v3/payments/{payment_id}")
def get_payment(payment_id: str, authorization: str | None = Header(None)):
    _check_auth(authorization)
    return _run("get", None, lambda: payments.get(payment_id))


@app.post("/v3/payments/{payment_id}/capture")
async def capture_payment(payment_id: str, request: Request, authorization: str | None = Header(None),
                          idempotence_key: str | None = Header(None, alias="Idempotence-Key")):
    _check_auth(authorization)
    body = await _json_or_empty(request)
    return await _in_thread(lambda: _run("capture", idempotence_key, lambda: payments.capture(payment_id, body)))


@app.post("/v3/payments/{payment_id}/cancel")
async def cancel_payment(payment_id: str, authorization: str | None = Header(None),
                         idempotence_key: str | None = Header(None, alias="Idempotence-Key")):
    _check_auth(authorization)
    return await _in_thread(lambda: _run("cancel", idempotence_key, lambda: payments.cancel(payment_id)))


async def _json_or_empty(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    data = await request.json()
    return data if isinstance(data, dict) else {}


async def _in_thread(fn):
    """The timeout fault sleeps; do it off the event loop so the mock keeps serving others."""
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(fn)


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok"}


# --- Pages (HTML) ---

STYLE = """
<style>
  body { font-family: system-ui, sans-serif; background: #f4f6f8; color: #1d2733; margin: 0; }
  main { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  .card { background: #fff; border: 1px solid #dde3ea; border-radius: 10px; padding: 20px; margin-bottom: 16px; }
  .banner { background: #fff3cd; border: 1px solid #f0d77b; border-radius: 8px; padding: 8px 12px; font-size: 14px; }
  h1 { font-size: 22px; } h2 { font-size: 17px; margin-top: 0; }
  button { font: inherit; padding: 10px 16px; border-radius: 8px; border: 1px solid #b8c2cc; background: #fff; cursor: pointer; }
  button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
  button.danger { background: #fee2e2; border-color: #f87171; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px; border-bottom: 1px solid #eef1f4; vertical-align: top; }
  code { font-size: 12px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  input, select { font: inherit; padding: 6px; }
  .muted { color: #64748b; font-size: 13px; }
</style>
"""


def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
                        f"<title>{html.escape(title)}</title>{STYLE}</head><body><main>{content}</main></body></html>")


def _rub(value: str | Decimal) -> str:
    return f"{Decimal(value):,.2f}".replace(",", " ").replace(".", ",") + " ₽"


@app.get("/checkout/{payment_id}", response_class=HTMLResponse)
def checkout(payment_id: str):
    payment = store.get_payment(payment_id)
    if payment is None:
        return _page("Платёж не найден", "<div class='card'>Платёж не найден.</div>")
    banner = "<p class='banner'>Тестовая страница мока платёжного шлюза. Настоящие карты здесь не нужны и не принимаются.</p>"
    head = (f"<h1>Оплата {_rub(payment['amount']['value'])}</h1>"
            f"<p>{html.escape(payment.get('description') or '')}</p>"
            f"<p class='muted'>Платёж <code>{payment['id']}</code></p>")
    if payment["status"] != "pending":
        return _page("Оплата", f"{banner}<div class='card'>{head}<p>Платёж уже в статусе <b>{payment['status']}</b>.</p></div>")
    buttons = (
        f"<form method='post' class='row'>"
        f"<button class='primary' name='outcome' value='success'>Успешная оплата</button>"
        f"<button class='danger' name='outcome' value='decline'>Отказ банка</button>"
        f"<button name='outcome' value='silent'>Холд без уведомления</button>"
        f"</form>"
        f"<p class='muted'>«Успешная оплата» — деньги заблокированы на карте (холд), магазин получит "
        f"уведомление <code>payment.waiting_for_capture</code>. «Отказ банка» — платёж отменён, причина "
        f"<code>insufficient_funds</code>. «Холд без уведомления» — деньги заблокированы, но вебхук не уходит "
        f"(повторить его можно из пульта).</p>"
    )
    return _page("Оплата", f"{banner}<div class='card'>{head}{buttons}</div>")


@app.post("/checkout/{payment_id}")
def checkout_submit(payment_id: str, outcome: str = Form(...)):
    if outcome not in ("success", "decline", "silent"):
        raise ApiProblem(400, "invalid_request", "Unknown outcome")
    payment = store.get_payment(payment_id)
    return_url = (payment or {}).get("confirmation", {}).get("return_url")
    payments.buyer_paid(payment_id, outcome)
    return RedirectResponse(return_url or f"/checkout/{payment_id}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin():
    items = store.list_payments()
    faults = store.list_faults()
    delay = store.get_setting("webhook_delay_seconds", "0")

    rows = []
    payouts: dict[str, Decimal] = defaultdict(Decimal)
    platform = Decimal("0")
    for p in items:
        if p["status"] == "succeeded":
            for t in p["transfers"]:
                payouts[t["account_id"]] += Decimal(t["amount"]["value"])
            platform += Decimal(p["metadata"].get("platform_fee") or "0")
        transfers = "<br>".join(f"{html.escape(t['account_id'])}: {_rub(t['amount']['value'])} ({t['status']})" for t in p["transfers"])
        reason = p.get("cancellation_details", {}).get("reason", "")
        actions = (
            f"<form method='post' action='/admin/payments/{p['id']}/resend' class='row'>"
            f"<input type='number' name='times' value='3' min='1' max='20' style='width:4em'>"
            f"<select name='mode'><option value='sequential'>подряд</option><option value='parallel'>одновременно</option></select>"
            f"<button>Отправить вебхук ещё раз</button></form>"
        )
        if p["status"] == "waiting_for_capture":
            actions += (f"<form method='post' action='/admin/payments/{p['id']}/expire-hold'>"
                        f"<button class='danger'>Холд истёк</button></form>")
        rows.append(
            f"<tr><td><code>{p['id']}</code><br><span class='muted'>{p['created_at']}</span></td>"
            f"<td>{html.escape(str(p['metadata'].get('order_id', '')))}</td>"
            f"<td><b>{p['status']}</b><br><span class='muted'>{html.escape(reason)}</span></td>"
            f"<td>{_rub(p['amount']['value'])}<br><span class='muted'>сбор {_rub(p['metadata'].get('platform_fee') or '0')}</span></td>"
            f"<td>{transfers}</td><td>{actions}</td></tr>"
        )

    fault_forms = "".join(
        f"<form method='post' action='/admin/fault' class='row'><b style='width:6em'>{op}</b>"
        f"<input type='hidden' name='operation' value='{op}'>"
        f"<select name='kind'><option value='none'>нет</option>"
        + "".join(f"<option value='{k}' {'selected' if faults.get(op, ('',))[0] == k else ''}>{k}</option>" for k in FAULTS)
        + f"</select><input type='number' name='count' min='0' max='20' value='{faults.get(op, ('', 1))[1]}' style='width:4em'>"
        f"<span class='muted'>следующих запросов</span><button>Применить</button></form>"
        for op in OPERATIONS
    )
    payout_rows = "".join(f"<tr><td>{html.escape(acc)}</td><td>{_rub(total)}</td></tr>" for acc, total in sorted(payouts.items()))
    deliveries = "".join(
        f"<tr><td>{d['at']}</td><td><code>{d['payment_id'][:8]}…</code></td><td>{d['event']}</td><td>{d['attempt']}</td><td>{html.escape(d['result'])}</td></tr>"
        for d in store.list_deliveries()
    )
    content = f"""
      <h1>Пульт мока ЮKassa</h1>
      <p class='banner'>Тестовая среда. Вебхуки уходят на <code>{html.escape(webhooks.webhook_url())}</code>.</p>
      <div class='card'><h2>Платежи</h2>
        <table><tr><th>Платёж</th><th>Заказ</th><th>Статус</th><th>Сумма</th><th>Перечисления (FR-30)</th><th></th></tr>{''.join(rows) or '<tr><td colspan=6>Пока нет</td></tr>'}</table></div>
      <div class='card'><h2>Перечислено продавцам после succeeded</h2>
        <table><tr><th>account_id</th><th>Сумма</th></tr>{payout_rows or '<tr><td colspan=2>Пока нет</td></tr>'}
        <tr><td><b>Платформе (сбор)</b></td><td><b>{_rub(platform)}</b></td></tr></table></div>
      <div class='card'><h2>Поломки</h2><p class='muted'>timeout — работа сделана, но ответ опаздывает на {os.environ.get('MOCK_TIMEOUT_SECONDS', '15')} с;
        500 и 429 — запрос не выполнен.</p>{fault_forms}</div>
      <div class='card'><h2>Задержка вебхуков</h2>
        <form method='post' action='/admin/settings' class='row'><input type='number' name='webhook_delay_seconds' min='0' max='120' value='{html.escape(delay)}' style='width:5em'>
        <span class='muted'>секунд перед отправкой</span><button>Сохранить</button></form></div>
      <div class='card'><h2>Доставка вебхуков</h2>
        <table><tr><th>Время (UTC)</th><th>Платёж</th><th>Событие</th><th>Попытка</th><th>Ответ</th></tr>{deliveries or '<tr><td colspan=5>Пока нет</td></tr>'}</table></div>
    """
    return _page("Пульт мока ЮKassa", content)


@app.post("/admin/fault")
def admin_fault(operation: str = Form(...), kind: str = Form(...), count: int = Form(1)):
    if operation in OPERATIONS and (kind in FAULTS or kind == "none"):
        store.set_fault(operation, kind, count)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/settings")
def admin_settings(webhook_delay_seconds: float = Form(0)):
    store.set_setting("webhook_delay_seconds", str(max(0.0, webhook_delay_seconds)))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/payments/{payment_id}/resend")
def admin_resend(payment_id: str, times: int = Form(1), mode: str = Form("sequential")):
    """A repeated notification: Core API must process the event once and answer 200 every time (FR-22)."""
    payment = payments.get(payment_id)
    event = store.last_event(payment_id) or f"payment.{payment['status']}"
    times = max(1, min(times, 20))
    if mode == "parallel":
        for _ in range(times):
            webhooks.send(payment, event)
    else:
        threading.Thread(target=lambda: [webhooks.deliver(payment, event) for _ in range(times)], daemon=True).start()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/payments/{payment_id}/expire-hold")
def admin_expire_hold(payment_id: str):
    """The hold ran out before capture: YooKassa cancels the payment by itself (GAP-37)."""
    payments.cancel(payment_id, party="yoo_money", reason="expired_on_capture")
    return RedirectResponse("/admin", status_code=303)
