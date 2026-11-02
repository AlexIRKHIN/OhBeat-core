import { describe, expect, it } from "vitest";

import type { Billing, Cart, CartItem } from "../api/types";
import { checkoutBlockers, orderBody, priceChanges } from "./cart";

const item = (over: Partial<CartItem> = {}): CartItem => ({
  beat_id: 1,
  title: "Neon Nights",
  producer: "DJ",
  cover_url: null,
  license: "basic",
  price: 1500,
  service_fee: 150,
  available: true,
  unavailable_reason: null,
  order_id: null,
  ...over,
});

const cart = (items: CartItem[]): Cart => ({ items, items_total: 0, service_fee: 0, total: 0, fee_percent: 10 });

const billing = { payer_type: "individual", phone: "+79001234567" } as Billing;

describe("FR-14, FR-32 checkout blockers", () => {
  it("an empty cart cannot be ordered", () => {
    expect(checkoutBlockers(cart([]), billing)).toEqual(["empty"]);
  });

  it("an unavailable item blocks the order until it is removed", () => {
    expect(checkoutBlockers(cart([item(), item({ beat_id: 2, available: false })]), billing)).toEqual(["unavailable"]);
  });

  it("buyer details are required, a phone only for Exclusive", () => {
    expect(checkoutBlockers(cart([item()]), null)).toEqual(["billing"]);
    const noPhone = { ...billing, phone: null };
    expect(checkoutBlockers(cart([item()]), noPhone)).toEqual([]);
    expect(checkoutBlockers(cart([item({ license: "exclusive" })]), noPhone)).toEqual(["phone"]);
  });
});

describe("FR-15 prices the Artist saw", () => {
  it("the order carries the cart prices as expected_price", () => {
    expect(orderBody(cart([item({ price: 999.95 })]), true)).toEqual({
      items: [{ beat_id: 1, license: "basic", expected_price: 999.95 }],
      offer_accepted: true,
    });
  });

  it("PRICE_CHANGED details become was / now rows", () => {
    const rows = priceChanges(cart([item()]), [{ field: "items[0].expected_price", issue: "", beat_id: 1, price: 1800 }]);
    expect(rows).toEqual([{ beatId: 1, title: "Neon Nights", license: "basic", oldPrice: 1500, newPrice: 1800 }]);
  });
});
