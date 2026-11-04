import { describe, expect, it } from "vitest";

import { moscowDay } from "./SalesPage";

describe("GAP-69 sales period by Moscow days", () => {
  it("today in Moscow may already be tomorrow in UTC", () => {
    const lateUtc = new Date("2026-11-03T22:30:00Z"); // 01:30 on 4 November in Moscow
    expect(moscowDay(0, lateUtc)).toBe("2026-11-04");
    expect(moscowDay(29, lateUtc)).toBe("2026-10-06");
  });
});
