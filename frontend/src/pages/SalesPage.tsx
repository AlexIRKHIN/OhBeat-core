// "My sales" of the Producer (REST API §2.10, UC-14; part of FR-34 moved to slice 3): sold items and
// the total for a period. Prices are the Producer's own — the service fee is the platform's.
// ASSUMPTION: GAP-69 — the period is in calendar days by Moscow time, both ends included.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { Sales } from "../api/types";
import { useDictionaries } from "../components/BeatBrowser";
import { ErrorState, Field, LoadingState, PageTitle } from "../components/ui";
import { formatRub } from "../lib/catalog";
import { errorText } from "../lib/errors";
import { formatMoscowDateTime } from "../lib/validation";

/** YYYY-MM-DD of today by Moscow time, minus `days`. */
export function moscowDay(days = 0, now = new Date()): string {
  const shifted = new Date(now.getTime() + 3 * 3600_000 - days * 86_400_000);
  return shifted.toISOString().slice(0, 10);
}

export function SalesPage() {
  const { t } = useTranslation();
  const dictionaries = useDictionaries();
  const [period, setPeriod] = useState({ from: moscowDay(29), to: moscowDay(0) });
  const sales = useQuery({
    queryKey: ["sales", period],
    queryFn: () => api<Sales>(`/users/me/sales?${new URLSearchParams(period)}`),
    enabled: Boolean(period.from && period.to),
  });
  const licenseName = (code: string) => dictionaries.data?.licenses.find((l) => l.code === code)?.name ?? code;

  return (
    <div className="space-y-4">
      <PageTitle>{t("sales.title")}</PageTitle>
      <div className="card flex flex-wrap items-end gap-3">
        <Field label={t("sales.from")} htmlFor="sales-from">
          <input id="sales-from" type="date" className="input" value={period.from} max={period.to}
                 onChange={(e) => setPeriod((p) => ({ ...p, from: e.target.value }))} />
        </Field>
        <Field label={t("sales.to")} htmlFor="sales-to">
          <input id="sales-to" type="date" className="input" value={period.to} min={period.from}
                 onChange={(e) => setPeriod((p) => ({ ...p, to: e.target.value }))} />
        </Field>
        {sales.data && (
          <p className="ml-auto text-right">
            <span className="block text-xs text-muted">{t("sales.total", { count: sales.data.count })}</span>
            <span className="text-2xl font-semibold text-cyan">{formatRub(sales.data.total)}</span>
          </p>
        )}
      </div>

      {sales.isPending && sales.fetchStatus !== "idle" && <LoadingState />}
      {sales.isError && <ErrorState text={errorText(sales.error)} onRetry={() => void sales.refetch()} />}
      {sales.data && sales.data.items.length === 0 && <div className="card text-center text-soft">{t("sales.empty")}</div>}
      {sales.data && sales.data.items.length > 0 && (
        // NFR-21: a list on phones, a table from 640 px
        <ul className="card divide-y divide-line p-0 sm:hidden">
          {sales.data.items.map((s) => (
            <li key={`${s.order_id}-${s.beat_id}`} className="flex items-start justify-between gap-3 px-4 py-3 text-sm">
              <span className="min-w-0">
                <span className="block truncate text-ink">{s.title}</span>
                <span className="block text-xs text-muted">
                  {licenseName(s.license)} · {formatMoscowDateTime(s.paid_at)}
                </span>
              </span>
              <span className="shrink-0 text-cyan">{formatRub(s.price)}</span>
            </li>
          ))}
        </ul>
      )}
      {sales.data && sales.data.items.length > 0 && (
        <div className="card hidden overflow-x-auto p-0 sm:block sm:p-0">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-normal">{t("sales.date")}</th>
                <th className="px-4 py-2 font-normal">{t("sales.beat")}</th>
                <th className="px-4 py-2 font-normal">{t("sales.license")}</th>
                <th className="px-4 py-2 text-right font-normal">{t("sales.price")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {sales.data.items.map((s) => (
                <tr key={`${s.order_id}-${s.beat_id}`}>
                  <td className="whitespace-nowrap px-4 py-2 text-soft">{formatMoscowDateTime(s.paid_at)}</td>
                  <td className="px-4 py-2 text-ink">{s.title}</td>
                  <td className="px-4 py-2 text-soft">{licenseName(s.license)}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-right text-cyan">{formatRub(s.price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
