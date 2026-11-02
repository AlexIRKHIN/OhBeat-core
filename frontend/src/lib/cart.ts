// Cart on the server (REST API §2.11): one query shared by the header badge, the beat page,
// the cart and the checkout. Every change returns the whole cart, which replaces the cached one.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type ApiErrorDetail } from "../api/client";
import type { Billing, Cart, LicenseCode } from "../api/types";

export const CART_QUERY = ["cart"] as const;

export function useCart(enabled = true) {
  return useQuery({ queryKey: CART_QUERY, queryFn: () => api<Cart>("/cart"), enabled });
}

export function usePutCartItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ beatId, license }: { beatId: number; license: LicenseCode }) =>
      api<Cart>(`/cart/items/${beatId}`, { method: "PUT", body: { license } }),
    onSuccess: (cart) => queryClient.setQueryData(CART_QUERY, cart),
  });
}

export function useRemoveCartItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (beatId: number) => api<void>(`/cart/items/${beatId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CART_QUERY }),
  });
}

export type CheckoutBlocker = "empty" | "unavailable" | "billing" | "phone";

/** What keeps the Artist from placing the order. The server checks the same again (409). */
export function checkoutBlockers(cart: Cart, billing: Billing | null): CheckoutBlocker[] {
  const blockers: CheckoutBlocker[] = [];
  if (cart.items.length === 0) blockers.push("empty");
  if (cart.items.some((i) => !i.available)) blockers.push("unavailable"); // FR-14: remove them first
  if (!billing) blockers.push("billing"); // FR-32: the contract needs the buyer's details
  else if (!billing.phone && cart.items.some((i) => i.license === "exclusive")) blockers.push("phone"); // RFC ПЭП: SMS code
  return blockers;
}

/** POST /orders body: the prices the Artist sees now (FR-15). */
export function orderBody(cart: Cart, offerAccepted: boolean) {
  return {
    items: cart.items.map((i) => ({ beat_id: i.beat_id, license: i.license, expected_price: i.price })),
    offer_accepted: offerAccepted,
  };
}

export interface PriceChange {
  beatId: number;
  title: string;
  license: string;
  oldPrice: number;
  newPrice: number;
}

/** 409 PRICE_CHANGED → rows "was / now" for the confirmation window. */
export function priceChanges(cart: Cart, details: ApiErrorDetail[]): PriceChange[] {
  return details.flatMap((d) => {
    const item = cart.items.find((i) => i.beat_id === d.beat_id);
    if (!item || d.price === undefined) return [];
    return [{ beatId: item.beat_id, title: item.title, license: item.license, oldPrice: item.price, newPrice: d.price }];
  });
}
