"""Final contracts: PDF from the signed draft plus the signature mark (FR-26, RFC ПЭП §5, ADR 0004).

    the draft text (the same text whose SHA-256 is contracts.draft_sha256)
  + the mark: "concluded by accepting the offer" (Basic / Premium / Trackout)
              or the stamp of the simple electronic signature (Exclusive, RFC §5)
  → PDF (WeasyPrint) → private bucket contracts/{number}.pdf → contracts.pdf_key, pdf_sha256

Made inside the processing of payment.succeeded, before the commit (ASSUMPTION: GAP-43): when the
order is `paid`, its contracts already exist. The key and the bytes depend only on the data, so a
repeated attempt overwrites the same object with the same file.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Beat
from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.storage import ObjectStorage
from app.contracts.draft import DraftItem, license_files, render_draft, sha256_text
from app.dictionaries.models import License
from app.orders.models import Contract, Order, OrderItem

MSK = timezone(timedelta(hours=3))  # NFR-29: contracts show Moscow time (no daylight saving)

_html = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


class ContractMismatch(Exception):
    """The draft built now differs from the signed one: the PDF would not be what was accepted."""


def contract_number(order_id: int, n: int) -> str:
    return f"{order_id}-{n}"  # ASSUMPTION: GAP-32


def draft_item(order: Order, item: OrderItem, beat: Beat, license_row: License, n: int) -> DraftItem:
    return DraftItem(
        order_id=order.id,
        number=contract_number(order.id, n),
        beat={"id": beat.id, "title": beat.title, "bpm": beat.bpm, "musical_key": beat.musical_key},
        license_code=license_row.code,
        license_name=license_row.name,
        license_files=license_files(license_row.includes_mp3, license_row.includes_wav, license_row.includes_stems),
        price=Decimal(item.price_at_purchase),
        fee=Decimal(item.platform_fee),
        producer_id=item.producer_id,
    )


def _msk(moment: datetime) -> str:
    return moment.astimezone(MSK).strftime("%d.%m.%Y %H:%M:%S")


def _full_name(party: dict) -> str:
    return " ".join(p for p in (party.get("last_name"), party.get("first_name"), party.get("middle_name")) if p)


def mask_phone(phone: str | None) -> str:
    """+79001234567 → +7 (900) ***-**-67 (RFC §5: the key id is shown masked)."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if phone and phone.startswith("+7") and len(digits) == 11:
        return f"+7 ({digits[1:4]}) ***-**-{digits[-2:]}"
    return f"+{digits[:-4]}****{digits[-2:]}" if len(digits) > 6 else "—"


def stamp(contract: Contract, snapshot: dict, producer_id: int, number: str) -> dict:
    buyer = snapshot["buyer"]
    licensor = snapshot["licensors"][str(producer_id)]
    licensor_name = f"{licensor.get('display_name')} (ID {producer_id})"
    if contract.signature_type == "otp":
        pep_date = licensor.get("pep_agreement_at")
        basis = f"соглашение о ПЭП от {datetime.fromisoformat(pep_date).astimezone(MSK):%d.%m.%Y}" if pep_date else "соглашение о ПЭП"
        return {
            "title": "ДОКУМЕНТ ПОДПИСАН ПРОСТОЙ ЭЛЕКТРОННОЙ ПОДПИСЬЮ",
            "rows": [
                ("Лицензиат", _full_name(buyer)),
                ("Идентификатор ключа", mask_phone(contract.signer_phone)),
                ("Способ подтверждения", "одноразовый SMS-код"),
                ("Дата и время (МСК)", _msk(contract.signed_at)),
                ("", ""),
                ("Лицензиар", licensor_name),
                ("Основание", basis),
                ("", ""),
                ("SHA-256 проекта", contract.draft_sha256),
                ("Номер договора", number),
            ],
        }
    # Basic / Premium / Trackout: the offer accepted from the account (RFC ПЭП §2, slice-3-plan §8)
    return {
        "title": "ДОГОВОР ЗАКЛЮЧЁН АКЦЕПТОМ ПУБЛИЧНОЙ ОФЕРТЫ",
        "rows": [
            ("Лицензиат", _full_name(buyer)),
            ("Учётная запись", f"ID {buyer.get('user_id')}, {buyer.get('email')}"),
            ("IP-адрес", contract.signer_ip),
            ("Дата и время (МСК)", _msk(contract.signed_at)),
            ("", ""),
            ("Лицензиар", licensor_name),
            ("", ""),
            ("SHA-256 проекта", contract.draft_sha256),
            ("Номер договора", number),
        ],
    }


def render_pdf(draft: str, stamp_data: dict, number: str) -> bytes:
    # The same data must give the same bytes (ADR 0004, GAP-43): the font subset embedded into the PDF
    # carries a creation time, and fontTools takes it from SOURCE_DATE_EPOCH — the standard variable of
    # reproducible builds. Without it the time of generation would change pdf_sha256 on every attempt.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
    from weasyprint import HTML  # imported here: the library is heavy and only needed for contracts

    html = _html.get_template("contract.html.j2").render(draft=draft, stamp=stamp_data, number=number)
    return HTML(string=html).write_pdf()


def pdf_key(number: str) -> str:
    return f"contracts/{number}.pdf"


def issue_contracts(db: Session, storage: ObjectStorage, order: Order) -> int:
    """PDF for every item of a paid order. Raises on storage failure: the webhook answers 500 and
    YooKassa repeats it (GAP-43)."""
    rows = db.execute(
        select(OrderItem, Beat, License, Contract)
        .join(Beat, Beat.id == OrderItem.beat_id)
        .join(License, License.id == OrderItem.license_id)
        .join(Contract, Contract.order_item_id == OrderItem.id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id)
    ).all()
    bucket = get_settings().bucket_private
    for n, row in enumerate(rows, start=1):
        number = contract_number(order.id, n)
        draft = render_draft(draft_item(order, row.OrderItem, row.Beat, row.License, n),
                             order.billing_snapshot, row.Contract.signature_type)
        if sha256_text(draft) != row.Contract.draft_sha256:
            raise ContractMismatch(f"contract {number}: the draft differs from the signed one")
        pdf = render_pdf(draft, stamp(row.Contract, order.billing_snapshot, row.OrderItem.producer_id, number), number)
        key = pdf_key(number)
        storage.put(bucket, key, pdf, "application/pdf")
        row.Contract.pdf_key = key
        row.Contract.pdf_sha256 = hashlib.sha256(pdf).hexdigest()
        write_audit(db, action="contract.generated", entity="order", entity_id=order.id, actor_user_id=None, ip=None,
                    details={"contract": number, "pdf_sha256": row.Contract.pdf_sha256})
    return len(rows)
