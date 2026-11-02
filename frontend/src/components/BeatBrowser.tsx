// Catalog building blocks shared by the catalog and the producer page (REST API §2.3, §2.9):
// the filter panel, the beat card and the grid with "Show more".
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { BeatCard as Beat, BeatPage, Dictionaries } from "../api/types";
import { formatDuration } from "../lib/beatFiles";
import { EMPTY_FILTERS, filtersToParams, formatRub, hasFilters, minPrice, type CatalogFilters } from "../lib/catalog";
import { PlayButton, type Track } from "../player/Player";
import { ErrorState, Spinner } from "./ui";

export function toTrack(beat: Beat): Track | null {
  return beat.preview_url
    ? { id: beat.id, title: beat.title, producer: beat.producer.display_name, previewUrl: beat.preview_url, coverUrl: beat.cover_url, durationSec: beat.duration_sec }
    : null;
}

export function useDictionaries() {
  return useQuery({ queryKey: ["dictionaries"], queryFn: () => api<Dictionaries>("/dictionaries", { auth: false }), staleTime: 300_000 });
}

/** Filter panel. Numbers are applied after a short pause in typing, selects at once. */
export function FilterBar({ value, onChange }: { value: CatalogFilters; onChange: (f: CatalogFilters) => void }) {
  const { t } = useTranslation();
  const dictionaries = useDictionaries();
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (JSON.stringify(draft) !== JSON.stringify(value)) onChange(draft);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [draft, value, onChange]);

  const digits = (key: "bpm_min" | "bpm_max" | "price_max", max: number) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setDraft((d) => ({ ...d, [key]: e.target.value.replace(/\D/g, "").slice(0, max) }));

  return (
    <div className="card grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <label className="col-span-2 space-y-1 text-xs text-cyan sm:col-span-1">
        <span>{t("catalog.genre")}</span>
        <select className="input" value={draft.genre} onChange={(e) => setDraft((d) => ({ ...d, genre: e.target.value }))}>
          <option value="">{t("catalog.any")}</option>
          {dictionaries.data?.genres.map((g) => (
            <option key={g.id} value={g.name}>
              {g.name}
            </option>
          ))}
        </select>
      </label>
      <label className="space-y-1 text-xs text-cyan">
        <span>{t("catalog.bpmFrom")}</span>
        <input className="input" inputMode="numeric" placeholder="40" value={draft.bpm_min} onChange={digits("bpm_min", 3)} />
      </label>
      <label className="space-y-1 text-xs text-cyan">
        <span>{t("catalog.bpmTo")}</span>
        <input className="input" inputMode="numeric" placeholder="300" value={draft.bpm_max} onChange={digits("bpm_max", 3)} />
      </label>
      <label className="space-y-1 text-xs text-cyan">
        <span>{t("catalog.key")}</span>
        <select className="input" value={draft.musical_key} onChange={(e) => setDraft((d) => ({ ...d, musical_key: e.target.value }))}>
          <option value="">{t("catalog.any")}</option>
          {dictionaries.data?.musical_keys.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </label>
      <label className="space-y-1 text-xs text-cyan">
        <span>{t("catalog.priceMax")}</span>
        <input className="input" inputMode="numeric" placeholder="₽" value={draft.price_max} onChange={digits("price_max", 6)} />
      </label>
      <div className="col-span-2 flex items-end sm:col-span-1">
        <button type="button" className="btn-secondary w-full" disabled={!hasFilters(draft)} onClick={() => setDraft(EMPTY_FILTERS)}>
          {t("catalog.reset")}
        </button>
      </div>
    </div>
  );
}

export function BeatTile({ beat }: { beat: Beat }) {
  const { t } = useTranslation();
  const track = toTrack(beat);
  const price = minPrice(beat);
  return (
    <article className="card flex flex-col gap-3 p-3 sm:p-3">
      <Link to={`/beats/${beat.id}`} className="relative block aspect-square overflow-hidden rounded-md bg-panel-2">
        {beat.cover_url ? (
          <img src={beat.cover_url} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-3xl text-muted">♪</div>
        )}
        {beat.is_reserved && (
          // FR-19: a reserved beat is marked in the catalog
          <span className="absolute left-2 top-2 rounded-full border border-orange/60 bg-nep/80 px-2 py-0.5 text-xs text-orange">
            {t("catalog.reserved")}
          </span>
        )}
        {track && (
          <span className="absolute bottom-2 right-2">
            <PlayButton track={track} />
          </span>
        )}
      </Link>
      <div className="min-w-0 space-y-1">
        <Link to={`/beats/${beat.id}`} className="block truncate font-semibold text-ink hover:text-cyan">
          {beat.title}
        </Link>
        <Link to={`/producers/${beat.producer.id}`} className="block truncate text-sm text-soft hover:text-cyan">
          {beat.producer.display_name}
        </Link>
        <p className="truncate text-xs text-muted">
          {beat.bpm} BPM · {beat.musical_key} · {formatDuration(beat.duration_sec)} · {beat.genres.join(", ")}
        </p>
        {price !== null && <p className="text-sm text-cyan">{t("catalog.from", { price: formatRub(price) })}</p>}
      </div>
    </article>
  );
}

/** A paged grid of beats from `endpoint` with the given filters. */
export function BeatGrid({
  endpoint,
  filters,
  onReset,
  queryKey,
}: {
  endpoint: string;
  filters: CatalogFilters;
  onReset: () => void;
  queryKey: unknown[];
}) {
  const { t } = useTranslation();
  const params = filtersToParams(filters).toString();
  const query = useInfiniteQuery({
    queryKey: [...queryKey, params],
    queryFn: ({ pageParam }) => {
      const search = new URLSearchParams(params);
      if (pageParam) search.set("cursor", pageParam);
      return api<BeatPage>(`${endpoint}?${search}`, { auth: false });
    },
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const beats = query.data?.pages.flatMap((p) => p.items) ?? [];

  if (query.isPending)
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-busy="true">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="card aspect-[3/4] animate-pulse p-3" />
        ))}
      </div>
    );
  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />;
  if (beats.length === 0)
    return (
      <div className="card space-y-3 text-center">
        <p className="text-lg text-ink">{t("catalog.nothing")}</p>
        {hasFilters(filters) && (
          <button type="button" className="btn-secondary" onClick={onReset}>
            {t("catalog.reset")}
          </button>
        )}
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {beats.map((beat) => (
          <BeatTile key={beat.id} beat={beat} />
        ))}
      </div>
      {query.hasNextPage && (
        <div className="text-center">
          <button type="button" className="btn-secondary" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
            {query.isFetchingNextPage && <Spinner />}
            {t("catalog.more")}
          </button>
        </div>
      )}
    </div>
  );
}
