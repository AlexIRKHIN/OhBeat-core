// Public producer page (FR-34, US-P5, REST API §2.9): profile and the showcase with catalog filters.
import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { BeatCard } from "../api/types";
import { BeatGrid, FilterBar } from "../components/BeatBrowser";
import { ErrorState, LoadingState, NotFoundPage } from "../components/ui";
import { EMPTY_FILTERS, filtersFromParams, filtersToParams, type CatalogFilters } from "../lib/catalog";

interface ProducerProfile {
  id: number;
  display_name: string;
  bio: string | null;
  avatar_url: string | null;
  items: BeatCard[];
  next_cursor: string | null;
}

export function ProducerPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const filters = filtersFromParams(params);
  const apply = useCallback((f: CatalogFilters) => setParams(filtersToParams(f), { replace: true }), [setParams]);
  // The profile part; the beats themselves are paged by BeatGrid from the same endpoint
  const profile = useQuery({
    queryKey: ["producers", id, "profile"],
    queryFn: () => api<ProducerProfile>(`/producers/${id}?limit=1`, { auth: false }),
  });

  if (profile.isPending) return <LoadingState />;
  if (profile.error instanceof ApiError && profile.error.status === 404) return <NotFoundPage />;
  if (profile.isError) return <ErrorState onRetry={() => void profile.refetch()} />;
  const p = profile.data;

  return (
    <section className="space-y-5">
      <header className="card flex flex-col items-center gap-4 text-center sm:flex-row sm:text-left">
        <div className="h-24 w-24 shrink-0 overflow-hidden rounded-full bg-panel-2">
          {p.avatar_url ? (
            <img src={p.avatar_url} alt="" className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full items-center justify-center text-3xl text-muted">{p.display_name.slice(0, 1).toUpperCase()}</div>
          )}
        </div>
        <div>
          <p className="text-xs uppercase tracking-wider text-muted">{t("producer.public")}</p>
          <h1 className="text-2xl font-bold text-cyan">{p.display_name}</h1>
          {p.bio && <p className="mt-1 whitespace-pre-line text-soft">{p.bio}</p>}
        </div>
      </header>
      <FilterBar value={filters} onChange={apply} />
      <BeatGrid endpoint={`/producers/${id}`} queryKey={["producers", id, "beats"]} filters={filters} onReset={() => apply(EMPTY_FILTERS)} />
    </section>
  );
}
