// Return from YooKassa (FR-27, GAP-65: /orders/{id}/return). The webhook may come a little later
// than the buyer, so the page asks GET /orders/{id} every 2 seconds for at most 60 seconds.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Order } from "../api/types";
import { ErrorState, LoadingState, NotFoundPage, PageTitle, Spinner } from "../components/ui";
import { formatRub } from "../lib/catalog";
import { POLL_INTERVAL_MS, keepPolling, returnState } from "../lib/payment";
import { PayPanel } from "./OrderPage";

export function PaymentReturnPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const started = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);
  const order = useQuery({
    queryKey: ["orders", id, "return"],
    queryFn: () => api<Order>(`/orders/${id}`),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && !keepPolling(returnState(data, Date.now() - started.current)) ? false : POLL_INTERVAL_MS;
    },
    retry: 2,
  });
  // A clock for the 60 s limit, so the timeout shows even if the answers stop changing
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(Date.now() - started.current), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (order.isPending) return <LoadingState />;
  if (order.error instanceof ApiError && [403, 404].includes(order.error.status)) return <NotFoundPage />;
  if (order.isError) return <ErrorState onRetry={() => void order.refetch()} />;

  const o = order.data;
  const state = returnState(o, elapsed);
  return (
    <div className="mx-auto max-w-xl space-y-4">
      <PageTitle>{t("order.title", { id: o.order_id })}</PageTitle>
      <div className="card space-y-3 text-center">
        {state === "waiting" && (
          <p className="flex items-center justify-center gap-2 text-soft">
            <Spinner /> {t("payment.waiting")}
          </p>
        )}
        {state === "paid" && (
          <>
            <p className="text-lg font-semibold text-cyan">{t("payment.success", { total: formatRub(o.total) })}</p>
            <p className="text-sm text-soft">{t("payment.paidText")}</p>
          </>
        )}
        {state === "canceled" && (
          <>
            <p className="text-lg font-semibold text-danger">{t("payment.orderCanceled")}</p>
            <p className="text-sm text-soft">
              {t(`payment.cancelReason.${o.cancel_reason}`, { defaultValue: t("payment.cancelReason.other") })} {t("payment.notCharged")}
            </p>
          </>
        )}
        {state === "declined" && (
          <div className="mx-auto max-w-xs text-left">
            <PayPanel order={o} />
          </div>
        )}
        {state === "expired" && <p className="text-soft">{t("order.expiredText")}</p>}
        {/* FR-27: the text for a payment that is still being processed */}
        {state === "timeout" && <p className="text-soft">{t("payment.timeout")}</p>}
        <Link to={`/orders/${o.order_id}`} className="link inline-block text-sm">
          {t("payment.toOrder")}
        </Link>
      </div>
    </div>
  );
}
