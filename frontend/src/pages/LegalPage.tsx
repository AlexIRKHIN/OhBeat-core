// Legal documents linked from the forms. Their texts are not in the documentation (GAP-31).
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { NotFoundPage, PageTitle } from "../components/ui";

const TITLES: Record<string, string> = {
  privacy: "legal.privacy",
  pep: "legal.pep",
  "license-terms": "legal.licenseTerms",
};

export function LegalPage() {
  const { t } = useTranslation();
  const { doc = "" } = useParams();
  if (!TITLES[doc]) return <NotFoundPage />;
  return (
    <article className="card">
      <PageTitle>{t(TITLES[doc])}</PageTitle>
      <p className="text-slate-600">{t("legal.placeholder")}</p>
    </article>
  );
}
