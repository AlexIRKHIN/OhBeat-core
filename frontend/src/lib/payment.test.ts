import { describe, expect, it } from "vitest";

import type { Order } from "../api/types";
import { POLL_LIMIT_MS, keepPolling, returnState } from "./payment";

const order = (over: Partial<Order> = {}): Order => ({
  order_id: 1,
  status: "pending",
  created_at: "2026-11-03T10:00:00Z",
  items_total: 1500,
  service_fee: 150,
  total: 1650,
  items: [],
  requires_signature: false,
  signed: true,
  reserved_until: null,
  payment_status: "pending",
  payment_cancel_reason: null,
  cancel_reason: null,
  ...over,
});

describe("FR-27 return page", () => {
  it("waits while the payment is processed, then gives up after 60 s", () => {
    expect(returnState(order(), 2_000)).toBe("waiting");
    expect(returnState(order({ payment_status: "waiting_for_capture" }), 30_000)).toBe("waiting");
    expect(returnState(order(), POLL_LIMIT_MS)).toBe("timeout");
    expect(keepPolling("timeout")).toBe(false);
  });

  it("paid, canceled by the FR-23 check, declined by the bank (FR-25)", () => {
    expect(returnState(order({ status: "paid", payment_status: "succeeded" }), 0)).toBe("paid");
    expect(returnState(order({ status: "canceled", cancel_reason: "BEAT_SOLD" }), 0)).toBe("canceled");
    expect(returnState(order({ payment_status: "canceled", payment_cancel_reason: "insufficient_funds" }), 0)).toBe("declined");
  });

  it("an expired order still waits if its money is held (FR-24: payment after expiry)", () => {
    expect(returnState(order({ status: "expired", payment_status: "waiting_for_capture" }), 0)).toBe("waiting");
    expect(returnState(order({ status: "expired", payment_status: "canceled" }), 0)).toBe("expired");
  });
});
