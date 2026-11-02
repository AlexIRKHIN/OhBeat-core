// "My beats" (FR-5, FR-34, REST API §2.10): statuses and rejection reasons, prices,
// take off sale / put back, logical deletion with a confirmation (NFR-20).
// While some beat is being processed, the list refreshes itself every 5 seconds.
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { BeatCard, BeatLicense, BeatPage, BeatStatus, LicenseCode } from "../api/types";
import { toTrack } from "../components/BeatBrowser";
import { ConfirmModal } from "../components/Modal";
import { useToast } from "../components/Toasts";
import { ErrorState, LoadingState, PageTitle, Spinner } from "../components/ui";
import { formatDuration } from "../lib/beatFiles";
import { errorText } from "../lib/errors";
import { formatMoscowDateTime } from "../lib/validation";
import { PlayButton } from "../player/Player";
import { useAuth } from "../auth/AuthContext";

const QUERY = ["users", "me", "beats"] as const;
const LICENSES: LicenseCode[] = ["basic", "premium", "trackout", "exclusive"];
const LICENSE_NAMES: Record<LicenseCode, string> = { basic: "Basic", premium: "Premium", trackout: "Trackout", exclusive: "Exclusive" };

const STATUS_CLASS: Record<BeatStatus, string> = {
  uploading: "border-line text-muted",
  processing: "border-orange/50 text-orange",
  active: "border-accent/60 text-accent-light",
  reserved: "border-orange/50 text-orange",
  sold: "border-cyan/50 text-cyan",
  rejected: "border-danger/60 text-danger",
  hidden: "border-line text-soft",
};

export function MyBeatsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const query = useInfiniteQuery({
    queryKey: QUERY,
    queryFn: ({ pageParam }) => api<BeatPage>(`/users/me/beats?limit=20${pageParam ? `&cursor=${pageParam}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // FR-5: the final status appears without reloading the page
    refetchInterval: (q) =>
      q.state.data?.pages.some((p) => p.items.some((b) => b.status === "processing")) ? 5000 : false,
  });

  const beats = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <PageTitle>{t("myBeats.title")}</PageTitle>
        <div className="flex gap-2">
          {user && (
            <Link to={`/producers/${user.id}`} className="btn-secondary">
              {t("myBeats.publicPage")}
            </Link>
          )}
          <Link to="/producer/beats/new" className="btn-primary">
            {t("myBeats.upload")}
          </Link>
        </div>
      </div>

      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : beats.length === 0 ? (
        <div className="card space-y-2 text-center">
          <p className="text-lg text-ink">{t("myBeats.empty")}</p>
          <p className="text-sm text-soft">{t("myBeats.emptyHint")}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {beats.map((beat) => (
            <BeatRow key={beat.id} beat={beat} />
          ))}
          {query.hasNextPage && (
            <div className="text-center">
              <button type="button" className="btn-secondary" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
                {query.isFetchingNextPage && <Spinner />}
                {t("myBeats.loadMore")}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function BeatRow({ beat }: { beat: BeatCard }) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const status = beat.status as BeatStatus;
  const listed = status === "active" || status === "hidden";

  const refresh = () => queryClient.invalidateQueries({ queryKey: QUERY });

  const run = async (action: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    try {
      await action();
      if (success) toast.show(success, "success");
      await refresh();
    } catch (error) {
      toast.show(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="card flex flex-col gap-4 sm:flex-row">
      <div className="h-24 w-24 shrink-0 overflow-hidden rounded-md bg-panel-2">
        {beat.cover_url ? (
          <img src={beat.cover_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-2xl text-muted">♪</div>
        )}
      </div>

      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="truncate text-lg font-semibold text-ink">{beat.title}</h2>
          <span className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_CLASS[status]}`}>{t(`status.${status}`)}</span>
        </div>
        <p className="text-xs text-muted">
          {beat.bpm} BPM · {beat.musical_key} · {beat.genres.join(", ")}
          {beat.duration_sec != null && ` · ${t("myBeats.duration")} ${formatDuration(beat.duration_sec)}`}
          {" · "}
          {beat.published_at
            ? `${t("myBeats.published")} ${formatMoscowDateTime(beat.published_at)}`
            : beat.created_at && `${t("myBeats.created")} ${formatMoscowDateTime(beat.created_at)}`}
        </p>

        {status === "processing" && (
          <p className="flex items-center gap-2 text-sm text-orange">
            <Spinner /> {t("myBeats.processing")}
          </p>
        )}
        {status === "uploading" && <p className="text-sm text-muted">{t("myBeats.abandoned")}</p>}
        {status === "rejected" && (
          <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {t("myBeats.reason")}: {beat.rejection_reason}
          </p>
        )}

        {toTrack(beat) && (
          <div className="flex items-center gap-2 text-xs text-muted">
            <PlayButton track={toTrack(beat)!} /> {t("myBeats.preview")}
          </div>
        )}

        {/* Prices make sense only for a beat that is or will be on sale */}
        {(status === "active" || status === "hidden" || status === "reserved" || status === "processing") && (
          <Prices beat={beat} disabled={busy} onSaved={refresh} />
        )}

        <div className="flex flex-wrap gap-2 pt-1">
          {status === "active" && (
            <button type="button" className="btn-secondary" disabled={busy}
              onClick={() => void run(() => api(`/beats/${beat.id}`, { method: "PATCH", body: { status: "hidden" } }))}>
              {t("myBeats.hide")}
            </button>
          )}
          {status === "hidden" && (
            <button type="button" className="btn-secondary" disabled={busy}
              onClick={() => void run(() => api(`/beats/${beat.id}`, { method: "PATCH", body: { status: "active" } }))}>
              {t("myBeats.unhide")}
            </button>
          )}
          {listed && (
            <button type="button" className="btn-secondary hover:border-danger/60 hover:text-danger" disabled={busy}
              onClick={() => setConfirmDelete(true)}>
              {t("myBeats.delete")}
            </button>
          )}
          {status === "rejected" && (
            // US-P4: upload the beat again with a fixed file; the form opens with the same metadata
            <Link to={`/producer/beats/new?from=${beat.id}`} className="btn-primary">
              {t("myBeats.reupload")}
            </Link>
          )}
        </div>
      </div>

      {confirmDelete && (
        <ConfirmModal
          title={t("myBeats.deleteTitle")}
          confirmLabel={t("myBeats.delete")}
          cancelLabel={t("myBeats.cancel")}
          danger
          busy={busy}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() =>
            void run(async () => {
              await api(`/beats/${beat.id}`, { method: "DELETE" });
              setConfirmDelete(false);
            }, t("myBeats.deleted"))
          }
        >
          {t("myBeats.deleteText", { title: beat.title })}
        </ConfirmModal>
      )}
    </article>
  );
}

/** Prices of the four licenses with "on" switches (REST API §2.4). One row is saved at a time. */
function Prices({ beat, disabled, onSaved }: { beat: BeatCard; disabled: boolean; onSaved: () => Promise<unknown> }) {
  const { t } = useTranslation();
  const toast = useToast();
  const initial = (code: LicenseCode): BeatLicense | undefined => beat.licenses.find((l) => l.code === code);
  const [draft, setDraft] = useState(() =>
    Object.fromEntries(LICENSES.map((c) => [c, { on: initial(c)?.is_active ?? false, price: String(initial(c)?.price ?? "") }])) as Record<
      LicenseCode,
      { on: boolean; price: string }
    >,
  );
  const [saving, setSaving] = useState<LicenseCode | null>(null);

  const changed = (code: LicenseCode) =>
    draft[code].on !== (initial(code)?.is_active ?? false) || draft[code].price !== String(initial(code)?.price ?? "");
  const validPrice = (value: string) => /^\d+$/.test(value) && Number(value) >= 100 && Number(value) <= 500000;

  const save = async (code: LicenseCode) => {
    setSaving(code);
    try {
      await api(`/beats/${beat.id}/licenses/${code}`, {
        method: "PUT",
        body: { price: Number(draft[code].price), is_active: draft[code].on },
      });
      toast.show(t("myBeats.priceSaved"), "success");
      await onSaved();
    } catch (error) {
      toast.show(errorText(error), "error"); // LAST_ACTIVE_LICENSE, STEMS_REQUIRED, BEAT_SOLD ...
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {LICENSES.map((code) => {
        const row = draft[code];
        const invalid = row.price !== "" && !validPrice(row.price);
        return (
          <div key={code} className="flex items-center gap-2 rounded-md border border-line bg-panel-2 px-2 py-1.5">
            <label className="flex w-24 items-center gap-2 text-xs text-soft">
              <input type="checkbox" checked={row.on} disabled={disabled}
                onChange={(e) => setDraft((d) => ({ ...d, [code]: { ...d[code], on: e.target.checked } }))} />
              {LICENSE_NAMES[code]}
            </label>
            <input
              aria-label={`${LICENSE_NAMES[code]} — ${t("upload.price")}`}
              inputMode="numeric"
              className={`input h-8 flex-1 py-1 ${invalid ? "input-error" : ""}`}
              value={row.price}
              disabled={disabled || !row.on}
              onChange={(e) => setDraft((d) => ({ ...d, [code]: { ...d[code], price: e.target.value.replace(/\D/g, "") } }))}
            />
            <span className="text-xs text-muted">₽</span>
            {changed(code) && (
              <button type="button" className="btn-secondary h-8 px-2 py-0 text-xs" disabled={disabled || saving !== null || !validPrice(row.price)}
                onClick={() => void save(code)}>
                {saving === code ? <Spinner /> : t("myBeats.savePrice")}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
