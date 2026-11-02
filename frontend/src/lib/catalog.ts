// Catalog filters live in the page address (?genre=Trap&bpm_min=80), so a filtered list can be shared
// by a link and survives a reload. Names are the query parameters of REST API §2.3.
import type { BeatCard } from "../api/types";

export interface CatalogFilters {
  genre: string;
  bpm_min: string;
  bpm_max: string;
  musical_key: string;
  price_max: string;
}

export const EMPTY_FILTERS: CatalogFilters = { genre: "", bpm_min: "", bpm_max: "", musical_key: "", price_max: "" };
const KEYS = Object.keys(EMPTY_FILTERS) as (keyof CatalogFilters)[];

export function filtersFromParams(params: URLSearchParams): CatalogFilters {
  return Object.fromEntries(KEYS.map((k) => [k, params.get(k) ?? ""])) as unknown as CatalogFilters;
}

/** Only filled filters go to the address and to the API. */
export function filtersToParams(filters: CatalogFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of KEYS) if (filters[key].trim()) params.set(key, filters[key].trim());
  return params;
}

export function hasFilters(filters: CatalogFilters): boolean {
  return KEYS.some((k) => filters[k].trim() !== "");
}

/** NFR-27: amounts in rubles with the ₽ sign, "1 500 ₽"; kopecks only when there are any, "1 099,95 ₽". */
export function formatRub(amount: number): string {
  const kopecks = Math.round(amount * 100) % 100 !== 0;
  const digits = kopecks ? 2 : 0;
  return `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(amount)} ₽`;
}

/** The lowest active price: what the card shows as "from …" (REST API §2.3 price_max uses it too). */
export function minPrice(beat: BeatCard): number | null {
  const prices = beat.licenses.filter((l) => l.is_active).map((l) => l.price);
  return prices.length ? Math.min(...prices) : null;
}
