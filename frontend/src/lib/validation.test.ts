import { describe, expect, it } from "vitest";

import {
  capitalizeName,
  formatMoscowDateTime,
  formatNationalNumber,
  isStrongPassword,
  isValidInn,
  normalizeNationalNumber,
  toE164,
} from "./validation";

describe("NFR-5 password rule", () => {
  it.each([
    ["Qwerty1!", true],
    ["Qwer1!", false],
    ["qwerty12!", false],
    ["Qwertyui!", false],
    ["Qwerty123", false],
    ["Йцукенг1!", false],
  ])("%s -> %s", (password, expected) => {
    expect(isStrongPassword(password)).toBe(expected);
  });
});

describe("INN checksum (UI spec §2 item 6)", () => {
  it.each([
    ["7707083893", true],
    ["500100732259", true],
    ["7707083894", false],
    ["500100732258", false],
    ["12345", false],
  ])("%s -> %s", (inn, expected) => {
    expect(isValidInn(inn)).toBe(expected);
  });
});

describe("Phone mask (UI spec §2 item 4)", () => {
  it("replaces a leading 8 with +7", () => {
    const digits = normalizeNationalNumber("+7", "8 900 123-45-67");
    expect(digits).toBe("9001234567");
    expect(toE164("+7", digits)).toBe("+79001234567");
  });

  it("formats a Russian number", () => {
    expect(formatNationalNumber("+7", "9001234567")).toBe("(900) 123-45-67");
  });
});

describe("Name capitalization (UI spec §2 item 2)", () => {
  it("uppercases the first letter of each part", () => {
    expect(capitalizeName("анна-мария петрова")).toBe("Анна-Мария Петрова");
  });
});

describe("NFR-28/29 date format", () => {
  it("shows Moscow time as DD.MM.YYYY HH:MM", () => {
    expect(formatMoscowDateTime("2026-10-04T11:22:15Z")).toBe("04.10.2026 14:22");
  });
});
