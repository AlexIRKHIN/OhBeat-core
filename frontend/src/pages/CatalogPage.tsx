// Catalog (US-A2, UC-1, UC-2): public, filters in the page address, "newest first".
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { BeatGrid, FilterBar } from "../components/BeatBrowser";
import { EMPTY_FILTERS, filtersFromParams, filtersToParams, type CatalogFilters } from "../lib/catalog";

export function CatalogPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const filters = filtersFromParams(params);
  const apply = useCallback((f: CatalogFilters) => setParams(filtersToParams(f), { replace: true }), [setParams]);

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-wide text-cyan sm:text-3xl">{t("catalog.title")}</h1>
        <p className="text-sm text-soft">{t("catalog.subtitle")}</p>
      </div>
      <FilterBar value={filters} onChange={apply} />
      <BeatGrid endpoint="/beats" queryKey={["catalog"]} filters={filters} onReset={() => apply(EMPTY_FILTERS)} />
    </section>
  );
}
