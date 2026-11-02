// Order (REST API §2.6, wider by GAP-63): status, items with contract numbers, totals and,
// for Exclusive, how long the reservation lasts (FR-18). Payment is added in slice 3b.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Order } from "../api/types";
import { useDictionaries } from "../components/BeatBrowser";
import { ErrorState, LoadingState, NotFoundPage, PageTitle } from "../components/ui";
import { formatRub } from "../lib/catalog";
import { formatMoscowDateTime } from "../lib/validation";
import { Totals } from "./CartPage";

const STATUS_CLASS: Record<Order["status"], string> = {
  pending: "border-accent/60 text-cyan",
  paid: "border-cyan/60 text-cyan",
  expired: "border-line text-muted",
  canceled: "border-danger/60 text-danger",
};

/** "14:59" until the moment, null once it has passed. */
export function timeLeft(until: string, now: number): string | null {
  const ms = new Date(until).getTime() - now;
  if (ms <= 0) return null;
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

export function OrderPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const dictionaries = useDictionaries();
  const order = useQuery({ queryKey: ["orders", id], queryFn: () => api<Order>(`/orders/${id}`) });
  const reserving = order.data?.status === "pending" && Boolean(order.data.reserved_until);
  const now = useNow(reserving);

  if (order.isPending) return <LoadingState />;
  if (order.error instanceof ApiError && [403, 404].includes(order.error.status)) return <NotFoundPage />;
  if (order.isError) return <ErrorState onRetry={() => void order.refetch()} />;

  const o = order.data;
  const left = o.reserved_until ? timeLeft(o.reserved_until, now) : null;
  const licenseName = (code: string) => dictionaries.data?.licenses.find((l) => l.code === code)?.name ?? code;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <PageTitle>{t("order.title", { id: o.order_id })}</PageTitle>
        <span className={`mb-4 rounded-full border px-2 py-0.5 text-xs ${STATUS_CLASS[o.status]}`}>{t(`order.status.${o.status}`)}</span>
      </div>
      <p className="-mt-4 text-sm text-muted">{t("order.createdAt", { date: formatMoscowDateTime(o.created_at) })}</p>

      {o.status === "pending" && o.reserved_until && (
        <p className="rounded-md border border-orange/40 bg-orange/10 px-3 py-2 text-sm text-orange">
          {left ? t("order.reservedFor", { left }) : t("order.reservationOver")}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-[1fr_18rem]">
        <ul className="card divide-y divide-line p-0 sm:p-0">
          {o.items.map((item) => (
            <li key={item.item_id} className="flex gap-3 p-4">
              <Link to={`/beats/${item.beat_id}`} className="h-14 w-14 shrink-0 overflow-hidden rounded-md border border-line bg-panel-2">
                {item.cover_url ? <img src={item.cover_url} alt="" className="h-full w-full object-cover" /> : <span className="flex h-full items-center justify-center text-muted">♪</span>}
              </Link>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-ink">{item.title}</p>
                <p className="text-sm text-soft">
                  {item.producer} · {licenseName(item.license)}
                </p>
                <p className="text-xs text-muted">{t("order.contract", { number: item.contract_number })}</p>
              </div>
              <span className="shrink-0 text-right text-sm">
                <span className="block text-cyan">{formatRub(item.price)}</span>
                <span className="block text-xs text-muted">+ {formatRub(item.service_fee)}</span>
              </span>
            </li>
          ))}
        </ul>
        <aside className="card h-fit space-y-3">
          <Totals cart={o} />
          {o.status === "pending" && (
            <>
              {o.requires_signature && !o.signed && <p className="text-sm text-orange">{t("order.signatureNeeded")}</p>}
              <button type="button" className="btn-primary w-full" disabled>
                {t("order.pay")}
              </button>
              <p className="text-xs text-muted">{t("order.paySoon")}</p>
            </>
          )}
          {o.status === "expired" && (
            <p className="text-sm text-soft">
              {t("order.expiredText")}{" "}
              <Link to="/cart" className="link">
                {t("checkout.toCart")}
              </Link>
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
