// Beat page (REST API §2.10): cover, preview, description and licenses with prices
// of the Producer (FR-15: the service fee is added later, in the cart).
// FR-14: the Artist picks exactly one license and puts it into the cart.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { BeatCard, LicenseCode } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { toTrack, useDictionaries } from "../components/BeatBrowser";
import { useToast } from "../components/Toasts";
import { ErrorState, LoadingState, NotFoundPage, Spinner } from "../components/ui";
import { formatDuration } from "../lib/beatFiles";
import { useCart, usePutCartItem } from "../lib/cart";
import { formatRub } from "../lib/catalog";
import { errorText } from "../lib/errors";
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

        <LicensePicker beat={b} names={(code) => licenseInfo.get(code)?.name ?? code} contents={contents} />
      </div>
    </article>
  );
}

/** FR-14, FR-19: one license per beat; the button is off for a reserved beat and for your own one (GAP-26). */
function LicensePicker({ beat, names, contents }: { beat: BeatCard; names: (code: LicenseCode) => string; contents: (code: string) => string }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const cart = useCart(Boolean(user));
  const put = usePutCartItem();

  const active = beat.licenses.filter((l) => l.is_active);
  const inCart = cart.data?.items.find((i) => i.beat_id === beat.id);
  const [picked, setChoice] = useState<LicenseCode | null>(null);
  // Until the Artist picks: the license already in the cart, otherwise the cheapest (the first one)
  const choice = picked ?? inCart?.license ?? active[0]?.code ?? null;

  const own = user?.id === beat.producer.id;
  const yourOrder = inCart?.unavailable_reason === "IN_YOUR_ORDER" ? inCart.order_id : null;
  const blocked = yourOrder
    ? t("beat.blockedYourOrder")
    : beat.is_reserved
      ? t("beat.blockedReserved")
      : own
        ? t("beat.blockedOwn")
        : null;
  const sameAsCart = inCart?.license === choice;

  const add = () => {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    if (!choice) return;
    put.mutate(
      { beatId: beat.id, license: choice },
      {
        onSuccess: () => toast.show(inCart ? t("beat.licenseChanged") : t("beat.added"), "success"),
        onError: (error) => {
          toast.show(errorText(error), "error");
          // The beat was reserved or sold meanwhile: show its real state
          if (error instanceof ApiError && error.status === 409) void queryClient.invalidateQueries({ queryKey: ["beats", String(beat.id)] });
        },
      },
    );
  };

  return (
    <section className="card space-y-3 p-0 sm:p-0">
      <h2 className="px-4 pt-4 text-sm font-medium text-cyan">{t("beat.licenses")}</h2>
      <fieldset className="divide-y divide-line" disabled={Boolean(blocked)}>
        <legend className="sr-only">{t("beat.chooseLicense")}</legend>
        {active.map((lic) => (
          <label
            key={lic.code}
            className={`flex cursor-pointer items-center justify-between gap-3 px-4 py-3 ${choice === lic.code ? "bg-accent/10" : "hover:bg-panel-2"}`}
          >
            <span className="flex items-center gap-3">
              <input
                type="radio"
                name="license"
                value={lic.code}
                checked={choice === lic.code}
                onChange={() => setChoice(lic.code)}
                className="accent-[#3b8fd0]"
              />
              <span>
                <span className="block font-medium text-ink">
                  {names(lic.code)}
                  {inCart?.license === lic.code && <span className="ml-2 text-xs text-cyan">· {t("beat.inCart")}</span>}
                </span>
                <span className="block text-xs text-muted">{contents(lic.code)}</span>
              </span>
            </span>
            <span className="shrink-0 text-lg text-cyan">{formatRub(lic.price)}</span>
          </label>
        ))}
      </fieldset>
      <div className="space-y-2 px-4 pb-4">
        {blocked && (
          <p className="text-sm text-orange">
            {blocked}
            {yourOrder && (
              <Link to={`/orders/${yourOrder}`} className="link ml-2">
                {t("cart.openOrder", { id: yourOrder })}
              </Link>
            )}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" onClick={add} disabled={Boolean(blocked) || !choice || sameAsCart || put.isPending}>
            {put.isPending && <Spinner />}
            {inCart ? (sameAsCart ? t("beat.inCart") : t("beat.changeLicense")) : t("beat.addToCart")}
          </button>
          {inCart && (
            <Link to="/cart" className="link text-sm">
              {t("beat.goToCart")}
            </Link>
          )}
        </div>
        <p className="text-xs text-muted">{t("beat.feeNote")}</p>
      </div>
    </section>
  );
}
