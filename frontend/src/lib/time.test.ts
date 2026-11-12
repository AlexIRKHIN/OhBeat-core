import { describe, expect, it } from "vitest";

import { codeDigits, timeLeft } from "./time";

describe("countdowns", () => {
  it("shows minutes and seconds, then nothing", () => {
    const now = Date.parse("2026-11-12T10:00:00Z");
    expect(timeLeft("2026-11-12T10:05:00Z", now)).toBe("5:00");
    expect(timeLeft("2026-11-12T10:00:00.400Z", now)).toBe("0:01"); // a started second still counts
    expect(timeLeft("2026-11-12T10:00:00Z", now)).toBeNull();
  });
});

describe("NFR-31 code field", () => {
  it("keeps six digits from typing or a pasted SMS", () => {
    expect(codeDigits("583 204")).toBe("583204");
    expect(codeDigits("код: 583204.")).toBe("583204");
    expect(codeDigits("12345678")).toBe("123456");
  });
});
