import { useTranslation } from "react-i18next";

export function HomePage() {
  const { t } = useTranslation();
  return (
    <section className="space-y-4">
      <h1 className="text-3xl font-bold tracking-wide text-cyan sm:text-4xl">{t("home.title")}</h1>
      <p className="max-w-2xl text-lg text-soft">{t("home.subtitle")}</p>
      <div className="card text-soft">{t("home.catalogSoon")}</div>
    </section>
  );
}
