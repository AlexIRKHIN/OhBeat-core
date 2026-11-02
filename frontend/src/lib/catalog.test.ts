import { describe, expect, it } from "vitest";

import { EMPTY_FILTERS, filtersFromParams, filtersToParams, formatRub, hasFilters, minPrice } from "./catalog";

describe("filters <-> page address", () => {
  it("only filled filters go to the address", () => {
    const params = filtersToParams({ ...EMPTY_FILTERS, genre: "Trap", bpm_min: "80", price_max: " " });
    expect(params.toString()).toBe("genre=Trap&bpm_min=80");
  });

  it("reads filters back", () => {
    const filters = filtersFromParams(new URLSearchParams("genre=Trap&musical_key=Am&unknown=1"));
    expect(filters).toEqual({ ...EMPTY_FILTERS, genre: "Trap", musical_key: "Am" });
    expect(hasFilters(filters)).toBe(true);
    expect(hasFilters(EMPTY_FILTERS)).toBe(false);
  });
});

describe("NFR-27 prices", () => {
  it("formats rubles with a space and the ₽ sign", () => {
    expect(formatRub(1500).replace(/\s/g, " ")).toBe("1 500 ₽");
    expect(formatRub(500000).replace(/\s/g, " ")).toBe("500 000 ₽");
  });

  it("shows kopecks only when there are any (fee on top, FR-30)", () => {
    expect(formatRub(1099.95).replace(/\s/g, " ")).toBe("1 099,95 ₽");
    expect(formatRub(450.5).replace(/\s/g, " ")).toBe("450,50 ₽");
    expect(formatRub(4950).replace(/\s/g, " ")).toBe("4 950 ₽");
  });

  it("the card price is the lowest active one", () => {
    const beat = {
      licenses: [
        { code: "basic", price: 500, is_active: false },
        { code: "premium", price: 3000, is_active: true },
        { code: "exclusive", price: 20000, is_active: true },
      ],
    } as never;
    expect(minPrice(beat)).toBe(3000);
  });
});
