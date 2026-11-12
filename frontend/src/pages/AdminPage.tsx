// Administration (FR-35 … FR-37): the Audit Log (read only), genres, the stop-list and stuck beats.
// The tab lives in the address (?tab=genres), so a reload or a link opens the same tab.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { ConfirmModal } from "../components/Modal";
import { useToast } from "../components/Toasts";
import { ErrorState, Field, LoadingState, PageTitle, Spinner } from "../components/ui";
import {
  EMPTY_AUDIT_FILTERS,
  actionGroups,
  auditParams,
  type AuditFilters,
  type AuditPage,
  type GenreAdmin,
  type ProcessingBeat,
  type StopWord,
} from "../lib/admin";
import { errorText } from "../lib/errors";
import { formatMoscowDateTime } from "../lib/validation";

const TABS = ["journal", "genres", "stopwords", "beats"] as const;
type Tab = (typeof TABS)[number];

export function AdminPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.includes(params.get("tab") as Tab) ? (params.get("tab") as Tab) : "journal";

  return (
    <div className="space-y-4">
      <PageTitle>{t("admin.title")}</PageTitle>
      <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((name) => (
          <button
            key={name}
            role="tab"
            type="button"
            aria-selected={tab === name}
            onClick={() => setParams({ tab: name })}
            className={`-mb-px rounded-t-md border-b-2 px-3 py-2 text-sm ${tab === name ? "border-accent text-cyan" : "border-transparent text-soft hover:text-ink"}`}
          >
            {t(`admin.tabs.${name}`)}
          </button>
        ))}
      </div>
      {tab === "journal" && <AuditTab />}
      {tab === "genres" && <GenresTab />}
      {tab === "stopwords" && <StopWordsTab />}
      {tab === "beats" && <BeatsTab />}
    </div>
  );
}

// --- Audit Log (FR-35, NFR-32): only reading ---

function AuditTab() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_AUDIT_FILTERS);
  const facets = useQuery({
    queryKey: ["admin", "audit-facets"],
    queryFn: () => api<{ actions: string[]; entities: string[] }>("/admin/audit-log/facets"),
  });
  const log = useInfiniteQuery({
    queryKey: ["admin", "audit", filters],
    queryFn: ({ pageParam }) => api<AuditPage>(`/admin/audit-log?${auditParams(filters, pageParam)}`),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const set = (key: keyof AuditFilters) => (e: { target: { value: string } }) => setFilters((f) => ({ ...f, [key]: e.target.value }));
  const items = log.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <div className="card grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Field label={t("admin.audit.action")} htmlFor="f-action">
          <select id="f-action" className="input" value={filters.action} onChange={set("action")}>
            <option value="">{t("admin.audit.any")}</option>
            <optgroup label={t("admin.audit.groups")}>
              {actionGroups(facets.data?.actions ?? []).map((g) => (
                <option key={g} value={g}>
                  {g}*
                </option>
              ))}
            </optgroup>
            <optgroup label={t("admin.audit.exact")}>
              {(facets.data?.actions ?? []).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </optgroup>
          </select>
        </Field>
        <Field label={t("admin.audit.entity")} htmlFor="f-entity">
          <select id="f-entity" className="input" value={filters.entity} onChange={set("entity")}>
            <option value="">{t("admin.audit.any")}</option>
            {(facets.data?.entities ?? []).map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </Field>
        <Field label="ID" htmlFor="f-id">
          <input id="f-id" className="input" inputMode="numeric" value={filters.entity_id}
                 onChange={(e) => setFilters((f) => ({ ...f, entity_id: e.target.value.replace(/\D/g, "").slice(0, 12) }))} />
        </Field>
        <Field label={t("sales.from")} htmlFor="f-from">
          <input id="f-from" type="date" className="input" value={filters.from} max={filters.to || undefined} onChange={set("from")} />
        </Field>
        <Field label={t("sales.to")} htmlFor="f-to">
          <input id="f-to" type="date" className="input" value={filters.to} min={filters.from || undefined} onChange={set("to")} />
        </Field>
      </div>
      <p className="text-xs text-muted">{t("admin.audit.readOnly")}</p>

      {log.isPending && <LoadingState />}
      {log.isError && <ErrorState text={errorText(log.error)} onRetry={() => void log.refetch()} />}
      {log.data && items.length === 0 && <div className="card text-center text-soft">{t("admin.audit.empty")}</div>}
      {items.length > 0 && (
        <ul className="card divide-y divide-line p-0 sm:p-0">
          {items.map((entry) => (
            <AuditRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
      {log.hasNextPage && (
        <div className="text-center">
          <button type="button" className="btn-secondary" disabled={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
            {log.isFetchingNextPage && <Spinner />}
            {t("catalog.more")}
          </button>
        </div>
      )}
    </div>
  );
}

function AuditRow({ entry }: { entry: AuditPage["items"][number] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <li className="space-y-1 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="whitespace-nowrap text-muted">{formatMoscowDateTime(entry.occurred_at)}</span>
        <span className="font-mono text-cyan">{entry.action}</span>
        <span className="text-soft">
          {entry.entity}
          {entry.entity_id !== null && ` #${entry.entity_id}`}
        </span>
        <span className="text-muted">{entry.actor ? (entry.actor.email ?? `ID ${entry.actor.id}`) : t("admin.audit.system")}</span>
        {entry.ip && <span className="text-xs text-muted">IP {entry.ip}</span>}
        {entry.details && (
          <button type="button" className="link ml-auto text-xs" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? t("admin.audit.hide") : t("admin.audit.details")}
          </button>
        )}
      </div>
      {open && entry.details && (
        <pre className="overflow-x-auto rounded-md border border-line bg-panel-2 p-2 text-xs text-soft">{JSON.stringify(entry.details, null, 2)}</pre>
      )}
    </li>
  );
}

// --- Genres (FR-36) ---

function GenresTab() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const genres = useQuery({ queryKey: ["admin", "genres"], queryFn: () => api<GenreAdmin[]>("/admin/genres") });
  const [name, setName] = useState("");
  const [toDelete, setToDelete] = useState<GenreAdmin | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "genres"] });
    void queryClient.invalidateQueries({ queryKey: ["dictionaries"] }); // the upload form and the catalog filter
  };
  const add = useMutation({
    mutationFn: () => api<GenreAdmin>("/admin/genres", { method: "POST", body: { name } }),
    onSuccess: (genre) => {
      setName("");
      toast.show(t("admin.genres.added", { name: genre.name }), "success");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api<void>(`/admin/genres/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setToDelete(null);
      refresh();
    },
    onError: (error) => {
      setToDelete(null);
      toast.show(errorText(error), "error");
      refresh();
    },
  });

  if (genres.isPending) return <LoadingState />;
  if (genres.isError) return <ErrorState onRetry={() => void genres.refetch()} />;
  return (
    <div className="space-y-4">
      <AddForm
        id="genre-name"
        label={t("admin.genres.new")}
        value={name}
        onChange={setName}
        busy={add.isPending}
        error={add.error}
        onSubmit={() => add.mutate()}
        hint={t("admin.genres.hint")}
      />
      <ul className="card divide-y divide-line p-0 sm:p-0">
        {genres.data.map((g) => (
          <li key={g.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
            <span className="text-ink">{g.name}</span>
            <span className="flex items-center gap-3">
              <span className="text-xs text-muted">{t("admin.genres.count", { count: g.beats_count })}</span>
              <button
                type="button"
                className="text-xs text-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                disabled={g.beats_count > 0}
                title={g.beats_count > 0 ? t("admin.genres.inUse", { count: g.beats_count }) : undefined}
                onClick={() => setToDelete(g)}
              >
                {t("cart.remove")}
              </button>
            </span>
          </li>
        ))}
      </ul>
      {toDelete && (
        <ConfirmModal
          title={t("admin.genres.deleteTitle")}
          confirmLabel={t("cart.remove")}
          cancelLabel={t("myBeats.cancel")}
          danger
          busy={remove.isPending}
          onCancel={() => setToDelete(null)}
          onConfirm={() => remove.mutate(toDelete.id)}
        >
          {t("admin.genres.deleteText", { name: toDelete.name })}
        </ConfirmModal>
      )}
    </div>
  );
}

// --- Stop-list (FR-36, GAP-16) ---

function StopWordsTab() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const words = useQuery({ queryKey: ["admin", "stop-words"], queryFn: () => api<StopWord[]>("/admin/stop-words") });
  const [word, setWord] = useState("");
  const [toDelete, setToDelete] = useState<StopWord | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin", "stop-words"] });
  const add = useMutation({
    mutationFn: () => api<StopWord>("/admin/stop-words", { method: "POST", body: { word } }),
    onSuccess: (created) => {
      setWord("");
      toast.show(t("admin.stopWords.added", { word: created.word }), "success");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api<void>(`/admin/stop-words/${id}`, { method: "DELETE" }),
    onSettled: () => {
      setToDelete(null);
      refresh();
    },
  });

  if (words.isPending) return <LoadingState />;
  if (words.isError) return <ErrorState onRetry={() => void words.refetch()} />;
  return (
    <div className="space-y-4">
      <AddForm
        id="stop-word"
        label={t("admin.stopWords.new")}
        value={word}
        onChange={setWord}
        busy={add.isPending}
        error={add.error}
        onSubmit={() => add.mutate()}
        hint={t("admin.stopWords.hint")}
      />
      {words.data.length === 0 ? (
        <div className="card text-center text-soft">{t("admin.stopWords.empty")}</div>
      ) : (
        <ul className="card flex flex-wrap gap-2">
          {words.data.map((w) => (
            <li key={w.id} className="flex items-center gap-2 rounded-full border border-line bg-panel-2 px-3 py-1 text-sm">
              <span className="text-ink">{w.word}</span>
              <button type="button" className="text-muted hover:text-danger" aria-label={t("cart.remove")} onClick={() => setToDelete(w)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {toDelete && (
        <ConfirmModal
          title={t("admin.stopWords.deleteTitle")}
          confirmLabel={t("cart.remove")}
          cancelLabel={t("myBeats.cancel")}
          danger
          busy={remove.isPending}
          onCancel={() => setToDelete(null)}
          onConfirm={() => remove.mutate(toDelete.id)}
        >
          {t("admin.stopWords.deleteText", { word: toDelete.word })}
        </ConfirmModal>
      )}
    </div>
  );
}

function AddForm(props: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  busy: boolean;
  error: unknown;
  onSubmit: () => void;
  hint: string;
}) {
  const { t } = useTranslation();
  const fieldError = props.error instanceof ApiError ? (props.error.details[0]?.issue ?? props.error.message) : props.error ? errorText(props.error) : undefined;
  return (
    <form
      className="card flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (props.value.trim()) props.onSubmit();
      }}
    >
      <div className="min-w-[14rem] flex-1">
        <Field label={props.label} htmlFor={props.id} error={fieldError} hint={props.hint}>
          <input id={props.id} className={`input ${fieldError ? "input-error" : ""}`} value={props.value} maxLength={100}
                 onChange={(e) => props.onChange(e.target.value)} />
        </Field>
      </div>
      <button type="submit" className="btn-primary" disabled={props.busy || !props.value.trim()}>
        {props.busy && <Spinner />}
        {t("admin.add")}
      </button>
    </form>
  );
}

// --- Stuck beats (FR-37) ---

function BeatsTab() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [all, setAll] = useState(false);
  const [rejecting, setRejecting] = useState<ProcessingBeat | null>(null);
  const [reason, setReason] = useState("");
  const beats = useQuery({
    queryKey: ["admin", "beats", all],
    queryFn: () => api<ProcessingBeat[]>(`/admin/beats?status=processing${all ? "&all=true" : ""}`),
    refetchInterval: 15_000, // a reprocessed beat leaves the list when Media Worker is done
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin", "beats"] });
  const reprocess = useMutation({
    mutationFn: (id: number) => api(`/admin/beats/${id}/reprocess`, { method: "POST" }),
    onSuccess: () => toast.show(t("admin.beats.reprocessed"), "success"),
    onError: (error) => toast.show(errorText(error), "error"),
    onSettled: refresh,
  });
  const reject = useMutation({
    mutationFn: (id: number) => api(`/admin/beats/${id}/reject`, { method: "POST", body: { reason } }),
    onSuccess: () => {
      toast.show(t("admin.beats.rejected"), "success");
      setRejecting(null);
      setReason("");
      refresh();
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-soft">{t("admin.beats.intro")}</p>
        <label className="flex items-center gap-2 text-sm text-soft">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} className="accent-[#3b8fd0]" />
          {t("admin.beats.showAll")}
        </label>
      </div>
      {beats.isPending && <LoadingState />}
      {beats.isError && <ErrorState onRetry={() => void beats.refetch()} />}
      {beats.data && beats.data.length === 0 && <div className="card text-center text-soft">{t("admin.beats.empty")}</div>}
      {beats.data && beats.data.length > 0 && (
        <ul className="card divide-y divide-line p-0 sm:p-0">
          {beats.data.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <div className="min-w-0 flex-1">
                <p className="text-ink">
                  {b.title} <span className="text-xs text-muted">#{b.id}</span>
                  {b.stuck && <span className="ml-2 rounded-full border border-orange/60 px-2 py-0.5 text-xs text-orange">{t("admin.beats.stuck")}</span>}
                </p>
                <p className="text-xs text-muted">
                  <Link to={`/producers/${b.producer_id}`} className="link">
                    {b.producer}
                  </Link>{" "}
                  · {t("admin.beats.since", { date: formatMoscowDateTime(b.processing_since) })}
                </p>
              </div>
              <button type="button" className="btn-secondary" disabled={reprocess.isPending} onClick={() => reprocess.mutate(b.id)}>
                {t("admin.beats.reprocess")}
              </button>
              <button type="button" className="btn border border-danger/60 bg-danger/20 text-danger hover:bg-danger/30" onClick={() => setRejecting(b)}>
                {t("admin.beats.reject")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {rejecting && (
        <ConfirmModal
          title={t("admin.beats.rejectTitle", { title: rejecting.title })}
          confirmLabel={t("admin.beats.reject")}
          cancelLabel={t("myBeats.cancel")}
          danger
          busy={reject.isPending}
          confirmDisabled={reason.trim().length < 3}
          onCancel={() => {
            setRejecting(null);
            reject.reset();
          }}
          onConfirm={() => reject.mutate(rejecting.id)}
        >
          <Field label={t("admin.beats.reason")} htmlFor="reject-reason" hint={t("admin.beats.reasonHint")}
                 error={reject.error ? errorText(reject.error) : undefined}>
            <textarea id="reject-reason" className="input min-h-24" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </ConfirmModal>
      )}
    </div>
  );
}
