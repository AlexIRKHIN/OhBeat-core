// "My purchases" (REST API §2.12): paid items with the payment date, the contract number and its
// SHA-256 — the Artist can compare it with the hash of the downloaded PDF (RFC ПЭП §6).
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Purchase } from "../api/types";
import { useDictionaries } from "../components/BeatBrowser";
import { DownloadLinks } from "../components/DownloadLinks";
import { ErrorState, LoadingState, PageTitle } from "../components/ui";
import { formatRub } from "../lib/catalog";
import { formatMoscowDateTime } from "../lib/validation";

interface PurchasesResponse {
  items: Purchase[];
}

export function PurchasesPage() {
  const { t } = useTranslation();
  const dictionaries = useDictionaries();
  const purchases = useQuery({ queryKey: ["purchases"], queryFn: () => api<PurchasesResponse>("/users/me/purchases") });
  const licenseName = (code: string) => dictionaries.data?.licenses.find((l) => l.code === code)?.name ?? code;

  if (purchases.isPending) return <LoadingState />;
  if (purchases.isError) return <ErrorState onRetry={() => void purchases.refetch()} />;

  const items = purchases.data.items;
  return (
    <div>
      <PageTitle>{t("purchases.title")}</PageTitle>
      {items.length === 0 ? (
        <div className="card text-center">
          <p className="mb-3 text-soft">{t("purchases.empty")}</p>
          <Link to="/" className="btn-primary">
            {t("cart.toCatalog")}
          </Link>
        </div>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.item_id} className="card flex flex-col gap-3 sm:flex-row">
              <div className="h-20 w-20 shrink-0 overflow-hidden rounded-md border border-line bg-panel-2">
                {item.cover_url ? <img src={item.cover_url} alt="" className="h-full w-full object-cover" /> : <span className="flex h-full items-center justify-center text-muted">♪</span>}
              </div>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="font-medium text-ink">{item.title}</p>
                  <p className="text-sm text-cyan">{formatRub(item.price + item.service_fee)}</p>
                </div>
                <p className="text-sm text-soft">
                  {item.producer} · {licenseName(item.license)}
                </p>
                <p className="text-xs text-muted">
                  {item.paid_at && t("purchases.paidAt", { date: formatMoscowDateTime(item.paid_at) })} ·{" "}
                  <Link to={`/orders/${item.order_id}`} className="link">
                    {t("order.title", { id: item.order_id })}
                  </Link>{" "}
                  · {t("order.contract", { number: item.contract_number })}
                </p>
                {item.pdf_sha256 && (
                  <p className="break-all font-mono text-[11px] text-muted" title={t("purchases.hashHint")}>
                    SHA-256: {item.pdf_sha256}
                  </p>
                )}
                <div className="pt-1">
                  <DownloadLinks orderId={item.order_id} beatId={item.beat_id} />
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
