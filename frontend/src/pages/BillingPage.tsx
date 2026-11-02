// UI spec §2 "Billing details": data for the license contract (FR-32).
// The same form is filled by a Producer when connecting to sales (FR-33).
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { ApiError, api } from "../api/client";
import type { Billing } from "../api/types";
import { useToast } from "../components/Toasts";
import { ErrorState, Field, LoadingState, PageTitle, Spinner } from "../components/ui";
import { applyFieldErrors, errorText } from "../lib/errors";
import {
  NAME_PATTERN,
  capitalizeName,
  formatNationalNumber,
  isCompleteNationalNumber,
  isValidInn,
  normalizeNationalNumber,
  splitE164,
  toE164,
} from "../lib/validation";

const COUNTRY_CODES = ["+7", "+375", "+380", "+998", "+77", "+1", "+44", "+49"];
const SERVER_FIELDS = [
  "payer_type", "last_name", "first_name", "middle_name", "email", "phone", "company_name", "inn", "legal_address",
] as const;

export const BILLING_QUERY = ["users", "me", "billing"] as const;

/** null = the form has never been saved (the API answers 404). */
export async function loadBilling(): Promise<Billing | null> {
  try {
    return await api<Billing>("/users/me/billing");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function BillingPage() {
  const query = useQuery({ queryKey: BILLING_QUERY, queryFn: loadBilling });
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />;
  return <BillingForm initial={query.data} />;
}

function BillingForm({ initial }: { initial: Billing | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [formError, setFormError] = useState<string | null>(null);

  const schema = useMemo(() => {
    const required = t("validation.required");
    const name = z.string().trim().min(1, required).max(100).regex(NAME_PATTERN, t("validation.nameLetters"));
    return z
      .object({
        payer_type: z.enum(["individual", "business"]),
        last_name: name,
        first_name: name,
        middle_name: z.string().trim().max(100).refine((v) => v === "" || NAME_PATTERN.test(v), t("validation.nameLetters")),
        email: z.string().trim().min(1, required).email(t("validation.email")),
        phone_code: z.string(),
        phone_digits: z.string(),
        company_name: z.string().trim().max(255),
        inn: z.string().trim(),
        legal_address: z.string().trim().max(1000),
      })
      .superRefine((v, ctx) => {
        // The phone is optional here; it becomes mandatory only for an order with Exclusive
        if (v.phone_digits && !isCompleteNationalNumber(v.phone_code, v.phone_digits)) {
          ctx.addIssue({ code: "custom", path: ["phone_digits"], message: t("validation.phone") });
        }
        if (v.payer_type === "business") {
          if (!v.company_name) ctx.addIssue({ code: "custom", path: ["company_name"], message: required });
          if (!v.legal_address) ctx.addIssue({ code: "custom", path: ["legal_address"], message: required });
          if (!/^(\d{10}|\d{12})$/.test(v.inn)) {
            ctx.addIssue({ code: "custom", path: ["inn"], message: t("validation.innFormat") });
          } else if (!isValidInn(v.inn)) {
            ctx.addIssue({ code: "custom", path: ["inn"], message: t("validation.innChecksum") });
          }
        }
      });
  }, [t]);
  type FormValues = z.infer<typeof schema>;

  const phone = splitE164(initial?.phone ?? null, COUNTRY_CODES);
  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    setError,
    trigger,
    formState: { errors, isValid, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    mode: "onTouched",
    defaultValues: {
      payer_type: initial?.payer_type ?? "individual",
      last_name: initial?.last_name ?? "",
      first_name: initial?.first_name ?? "",
      middle_name: initial?.middle_name ?? "",
      email: initial?.email ?? "",
      phone_code: phone.code,
      phone_digits: phone.digits,
      company_name: initial?.company_name ?? "",
      inn: initial?.inn ?? "",
      legal_address: initial?.legal_address ?? "",
    },
  });

  const payerType = watch("payer_type");
  const phoneCode = watch("phone_code");

  // Saved data is valid: show the button as enabled at once
  useEffect(() => {
    if (initial) void trigger();
  }, [initial, trigger]);

  const onSubmit = async (v: FormValues) => {
    setFormError(null);
    const business = v.payer_type === "business";
    const body = {
      payer_type: v.payer_type,
      last_name: v.last_name,
      first_name: v.first_name,
      middle_name: v.middle_name || null,
      email: v.email,
      phone: v.phone_digits ? toE164(v.phone_code, v.phone_digits) : null,
      company_name: business ? v.company_name : null,
      inn: business ? v.inn : null,
      legal_address: business ? v.legal_address : null,
    };
    try {
      const saved = await api<Billing>("/users/me/billing", { method: "PUT", body });
      queryClient.setQueryData(BILLING_QUERY, saved);
      toast.show(t("billing.saved"), "success");
      const next = params.get("next");
      if (next?.startsWith("/") && !next.startsWith("//")) navigate(next);
    } catch (error) {
      // The server reports "phone"; the form shows it under the digits input
      const mapped =
        error instanceof ApiError
          ? new ApiError(error.status, error.errorCode, error.message,
              error.details.map((d) => (d.field === "phone" ? { ...d, field: "phone_digits" } : d)))
          : error;
      if (!applyFieldErrors(mapped, setError, [...SERVER_FIELDS, "phone_digits"])) setFormError(errorText(error));
    }
  };

  // UI spec §2 item 2: capitalize names when the user leaves the field
  const nameProps = (field: "last_name" | "first_name" | "middle_name") => {
    const reg = register(field);
    return {
      ...reg,
      onBlur: (e: React.FocusEvent<HTMLInputElement>) => {
        setValue(field, capitalizeName(e.target.value.trim()), { shouldValidate: true });
        return reg.onBlur(e);
      },
    };
  };

  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle>{t("billing.title")}</PageTitle>
      <p className="mb-4 text-sm text-soft">{t("billing.intro")}</p>
      <form className="card space-y-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-cyan">{t("billing.payerType")}</legend>
          <div className="flex flex-wrap gap-4">
            {(["individual", "business"] as const).map((type) => (
              <label key={type} className="flex items-center gap-2 text-sm">
                <input type="radio" value={type} {...register("payer_type", { onChange: () => void trigger() })} />
                {t(`billing.${type}`)}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("billing.lastName")} htmlFor="last_name" error={errors.last_name?.message}>
            <input id="last_name" autoComplete="family-name" className={`input ${errors.last_name ? "input-error" : ""}`} {...nameProps("last_name")} />
          </Field>
          <Field label={t("billing.firstName")} htmlFor="first_name" error={errors.first_name?.message}>
            <input id="first_name" autoComplete="given-name" className={`input ${errors.first_name ? "input-error" : ""}`} {...nameProps("first_name")} />
          </Field>
          <Field label={t("billing.middleName")} htmlFor="middle_name" error={errors.middle_name?.message}>
            <input id="middle_name" autoComplete="additional-name" className={`input ${errors.middle_name ? "input-error" : ""}`} {...nameProps("middle_name")} />
          </Field>
        </div>

        <Field label={t("billing.email")} htmlFor="email" error={errors.email?.message} hint={t("billing.emailHint")}>
          <input id="email" type="email" autoComplete="email" className={`input ${errors.email ? "input-error" : ""}`} {...register("email")} />
        </Field>

        <Field label={t("billing.phone")} htmlFor="phone_digits" error={errors.phone_digits?.message} hint={t("billing.phoneHint")}>
          <div className="flex gap-2">
            <select
              aria-label={t("billing.countryCode")}
              className="input w-28"
              {...register("phone_code", { onChange: () => setValue("phone_digits", "", { shouldValidate: true }) })}
            >
              {COUNTRY_CODES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
            <Controller
              control={control}
              name="phone_digits"
              render={({ field }) => (
                <input
                  id="phone_digits"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel-national"
                  placeholder={phoneCode === "+7" ? "(900) 123-45-67" : ""}
                  className={`input ${errors.phone_digits ? "input-error" : ""}`}
                  value={formatNationalNumber(phoneCode, field.value)}
                  onChange={(e) => field.onChange(normalizeNationalNumber(phoneCode, e.target.value))}
                  onBlur={field.onBlur}
                />
              )}
            />
          </div>
        </Field>

        {/* UI spec §2 item 1: for a business the form expands with the company fields */}
        {payerType === "business" && (
          <div className="space-y-4 border-t border-line pt-4">
            <Field label={t("billing.companyName")} htmlFor="company_name" error={errors.company_name?.message}>
              <input id="company_name" autoComplete="organization" placeholder="ООО «Звук»" className={`input ${errors.company_name ? "input-error" : ""}`} {...register("company_name")} />
            </Field>
            <Field label={t("billing.inn")} htmlFor="inn" error={errors.inn?.message}>
              {/* Text, not a number: an INN may start with zero (UI spec §2 item 6) */}
              <input
                id="inn"
                type="text"
                inputMode="numeric"
                maxLength={12}
                className={`input ${errors.inn ? "input-error" : ""}`}
                {...register("inn", { onChange: (e) => setValue("inn", e.target.value.replace(/\D/g, "")) })}
              />
            </Field>
            <Field label={t("billing.legalAddress")} htmlFor="legal_address" error={errors.legal_address?.message}>
              <input id="legal_address" autoComplete="street-address" className={`input ${errors.legal_address ? "input-error" : ""}`} {...register("legal_address")} />
            </Field>
          </div>
        )}

        {formError && <p className="alert-error">{formError}</p>}

        <button type="submit" className="btn-primary w-full sm:w-auto" disabled={!isValid || isSubmitting}>
          {isSubmitting && <Spinner />}
          {isSubmitting ? t("common.saving") : t("billing.submit")}
        </button>
        <p className="text-xs text-muted">
          {t("billing.privacyBefore")}
          <Link to="/legal/privacy" target="_blank" className="link">
            {t("auth.pdConsentLink")}
          </Link>
        </p>
      </form>
    </div>
  );
}
