// Small building blocks shared by all screens: field with error text, spinner, states.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: ReactNode;
  htmlFor: string;
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700">
        {label}
      </label>
      {children}
      {/* NFR-11: the error text is shown right next to the field */}
      {error ? (
        <p id={`${htmlFor}-error`} className="text-sm text-red-600">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-slate-500">{hint}</p>
      ) : null}
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent ${className}`}
      aria-hidden
    />
  );
}

export function LoadingState() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-slate-500">
      <Spinner /> {t("common.loading")}
    </div>
  );
}

export function ErrorState({ onRetry, text }: { onRetry?: () => void; text?: string }) {
  const { t } = useTranslation();
  return (
    <div className="card flex flex-col items-center gap-3 text-center">
      <p className="text-slate-700">{text ?? t("common.loadError")}</p>
      {onRetry && (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="mb-4 text-2xl font-semibold sm:text-3xl">{children}</h1>;
}

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="card text-center">
      <p className="mb-3 text-lg">{t("common.notFound")}</p>
      <Link to="/" className="link">
        {t("common.toHome")}
      </Link>
    </div>
  );
}
