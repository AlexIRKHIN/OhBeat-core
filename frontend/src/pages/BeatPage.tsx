// Beat page (REST API §2.10): cover, preview, description and licenses with prices
// of the Producer (FR-15: the service fee is added later, in the cart).
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { BeatCard } from "../api/types";
import { toTrack, useDictionaries } from "../components/BeatBrowser";
import { ErrorState, LoadingState, NotFoundPage } from "../components/ui";
import { formatDuration } from "../lib/beatFiles";
import { formatRub } from "../lib/catalog";
import { PlayButton } from "../player/Player";

export function BeatPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const beat = useQuery({ queryKey: ["beats", id], queryFn: () => api<BeatCard>(`/beats/${id}`) });
  const dictionaries = useDictionaries();

  if (beat.isPending) return <LoadingState />;
  if (beat.error instanceof ApiError && beat.error.status === 404) return <NotFoundPage />;
  if (beat.isError) return <ErrorState onRetry={() => void beat.refetch()} />;

  const b = beat.data;
  const track = toTrack(b);
  const licenseInfo = new Map(dictionaries.data?.licenses.map((l) => [l.code, l]));
  const contents = (code: string) => {
    const l = licenseInfo.get(code as never);
    if (!l) return "";
    return [l.includes_mp3 && "MP3", l.includes_wav && "WAV", l.includes_stems && t("beat.stems"), l.is_exclusive && t("beat.exclusiveRights")]
      .filter(Boolean)
      .join(" + ");
  };

  return (
    <article className="grid gap-6 md:grid-cols-[18rem_1fr]">
      <div className="relative aspect-square overflow-hidden rounded-lg border border-line bg-panel-2">
        {b.cover_url ? <img src={b.cover_url} alt="" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-5xl text-muted">♪</div>}
        {track && (
          <span className="absolute bottom-3 right-3">
            <PlayButton track={track} size="lg" />
          </span>
        )}
      </div>

      <div className="space-y-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold text-cyan sm:text-3xl">{b.title}</h1>
            {b.is_reserved && <span className="rounded-full border border-orange/60 px-2 py-0.5 text-xs text-orange">{t("catalog.reserved")}</span>}
          </div>
          <Link to={`/producers/${b.producer.id}`} className="text-soft hover:text-cyan">
            {b.producer.display_name}
          </Link>
        </div>

        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          {[
            [t("beat.genres"), b.genres.join(", ")],
            ["BPM", String(b.bpm)],
            [t("beat.key"), b.musical_key],
            [t("beat.duration"), formatDuration(b.duration_sec)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-md border border-line bg-panel-2 px-3 py-2">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className="text-ink">{value}</dd>
            </div>
          ))}
        </dl>

        {b.description && <p className="whitespace-pre-line text-soft">{b.description}</p>}

        <section className="card space-y-2 p-0 sm:p-0">
          <h2 className="px-4 pt-4 text-sm font-medium text-cyan">{t("beat.licenses")}</h2>
          <ul className="divide-y divide-line">
            {b.licenses.map((lic) => (
              <li key={lic.code} className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="font-medium text-ink">{licenseInfo.get(lic.code)?.name ?? lic.code}</p>
                  <p className="text-xs text-muted">{contents(lic.code)}</p>
                </div>
                <p className="shrink-0 text-lg text-cyan">{formatRub(lic.price)}</p>
              </li>
            ))}
          </ul>
          <p className="px-4 pb-4 text-xs text-muted">{t("beat.buySoon")}</p>
        </section>
      </div>
    </article>
  );
}
