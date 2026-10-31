// FR-33: connecting to sales gives the Producer role.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { z } from "zod";

import { ApiError, api, refreshTokens } from "../api/client";
import type { Billing, ProducerAccount } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorState, Field, LoadingState, PageTitle, Spinner } from "../components/ui";
import { applyFieldErrors, errorText } from "../lib/errors";
import { BILLING_QUERY } from "./BillingPage";

async function loadBilling(): Promise<Billing | null> {
  try {
    return await api<Billing>("/users/me/billing");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function ProducerConnectPage() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const billing = useQuery({ queryKey: BILLING_QUERY, queryFn: loadBilling });
  const [justConnected, setJustConnected] = useState(false);

  if (hasRole("producer")) {
    return (
      <div className="mx-auto max-w-xl">
        <PageTitle>{t("producer.title")}</PageTitle>
        <div className="card text-emerald-700">{t(justConnected ? "producer.success" : "producer.already")}</div>
      </div>
    );
  }
  if (billing.isPending) return <LoadingState />;
  if (billing.isError) return <ErrorState onRetry={() => void billing.refetch()} />;

  return (
    <div className="mx-auto max-w-xl">
      <PageTitle>{t("producer.title")}</PageTitle>
      <p className="mb-4 text-sm text-slate-600">{t("producer.intro")}</p>
      {billing.data ? (
        <ProducerForm onConnected={() => setJustConnected(true)} />
      ) : (
        <div className="card space-y-3">
          <p>{t("producer.needBilling")}</p>
          <Link to="/billing?next=/producer/connect" className="btn-primary">
            {t("producer.fillBilling")}
          </Link>
        </div>
      )}
    </div>
  );
}

const FIELDS = ["tax_status", "yookassa_account_id", "pep_agreement", "license_terms"] as const;

function ProducerForm({ onConnected }: { onConnected: () => void }) {
  const { t } = useTranslation();
  const { reloadUser } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);

  const schema = useMemo(
    () =>
      z.object({
        tax_status: z.enum(["individual", "self_employed", "ip"]),
        yookassa_account_id: z.string().trim().min(1, t("validation.required")).max(64, t("validation.maxLength", { count: 64 })),
        pep_agreement: z.literal(true, { errorMap: () => ({ message: t("validation.consent") }) }),
        license_terms: z.literal(true, { errorMap: () => ({ message: t("validation.consent") }) }),
      }),
    [t],
  );
  type FormValues = z.infer<typeof schema>;

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isValid, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), mode: "onTouched", defaultValues: { tax_status: "self_employed" } });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      await api<ProducerAccount>("/users/me/producer-account", { method: "POST", body: values });
      onConnected();
      // The new role gets into the access token only with a fresh token pair
      await refreshTokens();
      await reloadUser();
    } catch (error) {
      if (!applyFieldErrors(error, setError, FIELDS)) setFormError(errorText(error));
    }
  };

  return (
    <form className="card space-y-4" onSubmit={handleSubmit(onSubmit)} noValidate>
      <fieldset>
        <legend className="mb-2 text-sm font-medium text-slate-700">{t("producer.taxStatus")}</legend>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-4">
          {(["individual", "self_employed", "ip"] as const).map((status) => (
            <label key={status} className="flex items-center gap-2 text-sm">
              <input type="radio" value={status} {...register("tax_status")} />
              {t(`producer.tax_${status}`)}
            </label>
          ))}
        </div>
      </fieldset>

      <Field label={t("producer.yookassaId")} htmlFor="yookassa_account_id" error={errors.yookassa_account_id?.message} hint={t("producer.yookassaHint")}>
        <input id="yookassa_account_id" className={`input ${errors.yookassa_account_id ? "input-error" : ""}`} {...register("yookassa_account_id")} />
      </Field>

      <div className="space-y-2">
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" {...register("pep_agreement")} />
          <span>
            {t("producer.pepBefore")}
            <Link to="/legal/pep" target="_blank" className="link">
              {t("producer.pepLink")}
            </Link>
          </span>
        </label>
        {errors.pep_agreement && <p className="text-sm text-red-600">{errors.pep_agreement.message}</p>}
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" {...register("license_terms")} />
          <span>
            {t("producer.termsBefore")}
            <Link to="/legal/license-terms" target="_blank" className="link">
              {t("producer.termsLink")}
            </Link>
          </span>
        </label>
        {errors.license_terms && <p className="text-sm text-red-600">{errors.license_terms.message}</p>}
      </div>

      {formError && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>}

      <button type="submit" className="btn-primary w-full sm:w-auto" disabled={!isValid || isSubmitting}>
        {isSubmitting && <Spinner />}
        {t("producer.submit")}
      </button>
    </form>
  );
}
