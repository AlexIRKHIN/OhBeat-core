// Cart (FR-14, FR-15, REST API §2.11): Producers' prices, the service fee as a separate line and
// the total. A beat that cannot be bought any more is marked and must be removed before checkout.
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { Cart, CartItem } from "../api/types";
import { useDictionaries } from "../components/BeatBrowser";
import { useToast } from "../components/Toasts";
import { ErrorState, LoadingState, PageTitle } from "../components/ui";
import { useCart, useRemoveCartItem } from "../lib/cart";
import { formatRub } from "../lib/catalog";
import { errorText } from "../lib/errors";

export function CartPage() {
  const { t } = useTranslation();
  const cart = useCart();

  if (cart.isPending) return <LoadingState />;
  if (cart.isError) return <ErrorState onRetry={() => void cart.refetch()} />;

  const { items } = cart.data;
  if (items.length === 0) {
    return (
      <div>
        <PageTitle>{t("cart.title")}</PageTitle>
        <div className="card text-center">
          <p className="mb-3 text-soft">{t("cart.empty")}</p>
          <Link to="/" className="btn-primary">
            {t("cart.toCatalog")}
          </Link>
        </div>
      </div>
    );
  }

  const hasUnavailable = items.some((i) => !i.available);
  return (
    <div>
      <PageTitle>{t("cart.title")}</PageTitle>
      <div className="grid gap-4 md:grid-cols-[1fr_18rem]">
        <ul className="card divide-y divide-line p-0 sm:p-0">
          {items.map((item) => (
            <CartRow key={item.beat_id} item={item} />
          ))}
        </ul>
        <aside className="card h-fit space-y-3">
          <Totals cart={cart.data} />
          {hasUnavailable && <p className="text-sm text-orange">{t("cart.removeUnavailable")}</p>}
          {hasUnavailable ? (
            <button type="button" className="btn-primary w-full" disabled>
              {t("cart.checkout")}
            </button>
          ) : (
            <Link to="/checkout" className="btn-primary w-full">
              {t("cart.checkout")}
            </Link>
          )}
        </aside>
      </div>
    </div>
  );
}

function CartRow({ item }: { item: CartItem }) {
  const { t } = useTranslation();
  const toast = useToast();
  const remove = useRemoveCartItem();
  const dictionaries = useDictionaries();
  const licenseName = dictionaries.data?.licenses.find((l) => l.code === item.license)?.name ?? item.license;

  return (
    <li className={`flex gap-3 p-4 ${item.available ? "" : "opacity-80"}`}>
      <Link to={`/beats/${item.beat_id}`} className="h-16 w-16 shrink-0 overflow-hidden rounded-md border border-line bg-panel-2">
        {item.cover_url ? <img src={item.cover_url} alt="" className="h-full w-full object-cover" /> : <span className="flex h-full items-center justify-center text-muted">♪</span>}
      </Link>
      <div className="min-w-0 flex-1">
        <Link to={`/beats/${item.beat_id}`} className="block truncate font-medium text-ink hover:text-cyan">
          {item.title}
        </Link>
        <p className="truncate text-sm text-soft">{item.producer}</p>
        <p className="text-xs text-muted">
          {licenseName}
          {item.available && (
            <Link to={`/beats/${item.beat_id}`} className="link ml-2">
              {t("cart.changeLicense")}
            </Link>
          )}
        </p>
        {!item.available && item.unavailable_reason && (
          <p className="mt-1 text-sm text-orange">
            {t(`cart.reason.${item.unavailable_reason}`)}
            {item.order_id && (
              <Link to={`/orders/${item.order_id}`} className="link ml-2">
                {t("cart.openOrder", { id: item.order_id })}
              </Link>
            )}
          </p>
        )}
      </div>
      <div className="flex shrink-0 flex-col items-end justify-between gap-2">
        <span className={item.available ? "text-cyan" : "text-muted line-through"}>{formatRub(item.price)}</span>
        <button
          type="button"
          className="text-xs text-soft hover:text-danger"
          disabled={remove.isPending}
          onClick={() => remove.mutate(item.beat_id, { onError: (error) => toast.show(errorText(error), "error") })}
        >
          {t("cart.remove")}
        </button>
      </div>
    </li>
  );
}

/** FR-15, FR-30: the Producers' prices, the fee on top of them, the total to pay. */
export function Totals({ cart }: { cart: Pick<Cart, "items_total" | "service_fee" | "total"> & { fee_percent?: number } }) {
  const { t } = useTranslation();
  return (
    <dl className="space-y-1 text-sm">
      <div className="flex justify-between text-soft">
        <dt>{t("cart.itemsTotal")}</dt>
        <dd>{formatRub(cart.items_total)}</dd>
      </div>
      <div className="flex justify-between text-soft">
        <dt>{cart.fee_percent === undefined ? t("cart.fee") : t("cart.feePercent", { percent: cart.fee_percent })}</dt>
        <dd>{formatRub(cart.service_fee)}</dd>
      </div>
      <div className="flex justify-between border-t border-line pt-2 text-base font-semibold text-ink">
        <dt>{t("cart.total")}</dt>
        <dd className="text-cyan">{formatRub(cart.total)}</dd>
      </div>
    </dl>
  );
}
