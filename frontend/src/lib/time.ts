// Countdowns: the reservation (FR-18), the life of an SMS code and the pause before a new one (NFR-31).
import { useEffect, useState } from "react";

/** "14:59" until the moment, null once it has passed. */
export function timeLeft(until: string | number, now: number): string | null {
  const ms = new Date(until).getTime() - now;
  if (ms <= 0) return null;
  const total = Math.ceil(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** The current time, updated every second while `active`. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

/** What the code field keeps from any input or paste: digits only, at most 6 ("583 204" → "583204"). */
export function codeDigits(input: string): string {
  return input.replace(/\D/g, "").slice(0, 6);
}
