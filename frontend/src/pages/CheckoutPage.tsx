// Checkout (FR-15 … FR-18, FR-32): order contents and totals, the offer checkbox, then POST /orders.
// Errors of the server are turned into what the Artist can do: confirm new prices (PRICE_CHANGED),
// see that a beat is taken (BEAT_RESERVED / BEAT_SOLD), fill in the buyer's details (BILLING_REQUIRED).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Cart, OrderCreated } from "../api/types";
import { useDictionaries } from "../components/BeatBrowser";
import { ConfirmModal } from "../components/Modal";
import { ErrorState, LoadingState, PageTitle, Spinner } from "../components/ui";
import { CART_QUERY, checkoutBlockers, orderBody, priceChanges, useCart, type PriceChange } from "../lib/cart";
import { formatRub } from "../lib/catalog";
import { errorText } from "../lib/errors";
import { BILLING_QUERY, loadBilling } from "./BillingPage";
import { Totals } from "./CartPage";

export function CheckoutPage() {
  const { t } = useTranslation();
  const cart = useCart();
  const billing = useQuery({ queryKey: BILLING_QUERY, queryFn: loadBilling });

  if (cart.isPending || billing.isPending) return <LoadingState />;
  if (cart.isError || billing.isError) return <ErrorState onRetry={() => void Promise.all([cart.refetch(), billing.refetch()])} />;

  const blockers = checkoutBlockers(cart.data, billing.data);
  return (
    <div>
      <PageTitle>{t("checkout.title")}</PageTitle>
      {blockers.length > 0 ? <Blocked blockers={blockers} /> : <CheckoutForm cart={cart.data} />}
    </div>
  );
}

function Blocked({ blockers }: { blockers: ReturnType<typeof checkoutBlockers> }) {
  const { t } = useTranslation();
  const back = encodeURIComponent("/checkout");
  return (
    <div className="card space-y-3">
      {blockers.includes("empty") && (
        <p className="text-soft">
          {t("cart.empty")}{" "}
          <Link to="/" className="link">
            {t("cart.toCatalog")}
          </Link>
        </p>
      )}
      {blockers.includes("unavailable") && (
        <p className="text-orange">
          {t("cart.removeUnavailable")}{" "}
          <Link to="/cart" className="link">
            {t("checkout.toCart")}
          </Link>
        </p>
      )}
      {(blockers.includes("billing") || blockers.includes("phone")) && (
        <div className="space-y-2">
          <p className="text-soft">{blockers.includes("phone") ? t("checkout.needPhone") : t("checkout.needBilling")}</p>
          <Link to={`/billing?next=${back}`} className="btn-primary">
            {t("checkout.fillBilling")}
          </Link>
        </div>
      )}
    </div>
  );
}

function CheckoutForm({ cart }: { cart: Cart }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dictionaries = useDictionaries();
  const [offer, setOffer] = useState(false);
  const [changes, setChanges] = useState<PriceChange[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const hasExclusive = cart.items.some((i) => i.license === "exclusive");
  const hasLease = cart.items.some((i) => i.license !== "exclusive");
  const licenseName = (code: string) => dictionaries.data?.licenses.find((l) => l.code === code)?.name ?? code;

  const create = useMutation({
    mutationFn: (current: Cart) => api<OrderCreated>("/orders", { method: "POST", body: orderBody(current, offer) }),
    onSuccess: (order) => navigate(`/orders/${order.order_id}`),
    onError: async (error) => {
      if (error instanceof ApiError && error.errorCode === "PRICE_CHANGED") {
        // FR-15: show was / now, the refreshed cart holds the new prices for the second attempt
        setChanges(priceChanges(cart, error.details));
        await queryClient.invalidateQueries({ queryKey: CART_QUERY });
        return;
      }
      if (error instanceof ApiError && error.status === 409) {
        // FR-18: BEAT_RESERVED / BEAT_SOLD / BEAT_NOT_AVAILABLE … — the cart will mark the beat
        void queryClient.invalidateQueries({ queryKey: CART_QUERY });
        void queryClient.invalidateQueries({ queryKey: BILLING_QUERY });
      }
      setProblem(errorText(error));
    },
  });

  const submit = (current: Cart) => {
    setProblem(null);
    create.mutate(current);
  };

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_18rem]">
      <section className="card space-y-3">
        <h2 className="text-sm font-medium text-cyan">{t("checkout.contents")}</h2>
        <ul className="divide-y divide-line text-sm">
          {cart.items.map((item) => (
            <li key={item.beat_id} className="flex justify-between gap-3 py-2">
              <span className="min-w-0">
                <span className="block truncate text-ink">{item.title}</span>
                <span className="block text-xs text-muted">
                  {item.producer} · {licenseName(item.license)}
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block text-cyan">{formatRub(item.price)}</span>
                <span className="block text-xs text-muted">+ {formatRub(item.service_fee)}</span>
              </span>
            </li>
          ))}
        </ul>
        {hasExclusive && <p className="rounded-md border border-orange/40 bg-orange/10 px-3 py-2 text-sm text-orange">{t("checkout.exclusiveNote")}</p>}
      </section>

      <aside className="card h-fit space-y-4">
        <Totals cart={cart} />
        {/* FR-16: the offer for Basic / Premium / Trackout. ASSUMPTION: GAP-28 — the checkbox is always required */}
        <label className="flex items-start gap-2 text-sm text-soft">
          <input type="checkbox" checked={offer} onChange={(e) => setOffer(e.target.checked)} className="mt-1 accent-[#3b8fd0]" />
          <span>
            <Trans
              i18nKey={hasLease ? "checkout.offer" : "checkout.offerExclusive"}
              components={{ offer: <Link to="/legal/offer" target="_blank" className="link" /> }}
            />
          </span>
        </label>
        {problem && <p className="alert-error">{problem}</p>}
        {/* FR-17: the button is off until the offer is accepted */}
        <button type="button" className="btn-primary w-full" disabled={!offer || create.isPending} onClick={() => submit(cart)}>
          {create.isPending && <Spinner />}
          {t("checkout.placeOrder")}
        </button>
      </aside>

      {changes && (
        <ConfirmModal
          title={t("checkout.priceChangedTitle")}
          confirmLabel={t("checkout.confirmNewPrices")}
          cancelLabel={t("checkout.backToCart")}
          busy={create.isPending}
          onCancel={() => navigate("/cart")}
          onConfirm={() => {
            const fresh = queryClient.getQueryData<Cart>(CART_QUERY) ?? cart;
            setChanges(null);
            submit(fresh);
          }}
        >
          <p className="mb-2">{t("checkout.priceChangedText")}</p>
          <ul className="space-y-1">
            {changes.map((c) => (
              <li key={c.beatId} className="flex justify-between gap-3">
                <span className="truncate">
                  {c.title} · {licenseName(c.license)}
                </span>
                <span className="shrink-0">
                  <span className="text-muted line-through">{formatRub(c.oldPrice)}</span> <span className="text-cyan">{formatRub(c.newPrice)}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 font-medium text-ink">{t("checkout.newTotal", { total: formatRub(cart.total) })}</p>
        </ConfirmModal>
      )}
    </div>
  );
}
