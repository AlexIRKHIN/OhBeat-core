// Payment from the browser (FR-20, FR-21, FR-27): create a payment and leave for the YooKassa page;
// after the return, poll the order every 2 seconds for at most 60 seconds.
import { useMutation } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Order } from "../api/types";

export const POLL_INTERVAL_MS = 2_000;
export const POLL_LIMIT_MS = 60_000;

export function usePay(orderId: number) {
  return useMutation({
    mutationFn: () => api<{ payment_id: string; confirmation_url: string }>(`/orders/${orderId}/payments`, { method: "POST" }),
    // The payment page is another site: a full page change, not a route of the SPA
    onSuccess: ({ confirmation_url }) => window.location.assign(confirmation_url),
  });
}

export type ReturnState = "paid" | "canceled" | "declined" | "expired" | "waiting" | "timeout";

/** What the return page shows for the order it has just read. */
export function returnState(order: Order, elapsedMs: number): ReturnState {
  if (order.status === "paid") return "paid";
  if (order.status === "canceled") return "canceled"; // FR-23: a beat could not be sold, the hold is released
  // FR-25: the bank declined, the order still waits — the Artist may pay again
  if (order.payment_status === "canceled" && order.status === "pending") return "declined";
  // An expired order with a payment still in flight may yet be paid (FR-24): keep waiting for it
  if (order.status === "expired" && (order.payment_status === "canceled" || order.payment_status === null)) return "expired";
  return elapsedMs >= POLL_LIMIT_MS ? "timeout" : "waiting"; // FR-27
}

export function keepPolling(state: ReturnState): boolean {
  return state === "waiting";
}
