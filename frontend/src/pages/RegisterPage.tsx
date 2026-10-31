// FR-31: registration with consent to personal data processing and the e-signature agreement.
import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";

import { api, type TokenPair } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Field, PageTitle, Spinner } from "../components/ui";
import { applyFieldErrors, errorText } from "../lib/errors";
import { isStrongPassword } from "../lib/validation";

const FIELDS = ["email", "password", "display_name", "pd_consent", "pep_agreement"] as const;

export function RegisterPage() {
  const { t } = useTranslation();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);

  const schema = useMemo(
    () =>
      z.object({
        email: z.string().trim().min(1, t("validation.required")).email(t("validation.email")),
        password: z.string().refine(isStrongPassword, t("validation.password")),
        display_name: z
          .string()
          .trim()
          .min(2, t("validation.minLength", { count: 2 }))
          .max(100, t("validation.maxLength", { count: 100 })),
        pd_consent: z.literal(true, { errorMap: () => ({ message: t("validation.consent") }) }),
        pep_agreement: z.literal(true, { errorMap: () => ({ message: t("validation.consent") }) }),
      }),
    [t],
  );
  type FormValues = z.infer<typeof schema>;

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isValid, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), mode: "onTouched" });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      const pair = await api<TokenPair>("/auth/register", { method: "POST", body: values, auth: false });
      await signIn(pair);
      navigate("/profile");
    } catch (error) {
      if (!applyFieldErrors(error, setError, FIELDS)) setFormError(errorText(error));
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("auth.registerTitle")}</PageTitle>
      <form className="card space-y-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label={t("auth.email")} htmlFor="email" error={errors.email?.message}>
          <input id="email" type="email" autoComplete="email" className={`input ${errors.email ? "input-error" : ""}`} {...register("email")} />
        </Field>
        <Field label={t("auth.displayName")} htmlFor="display_name" error={errors.display_name?.message}>
          <input id="display_name" autoComplete="nickname" className={`input ${errors.display_name ? "input-error" : ""}`} {...register("display_name")} />
        </Field>
        <Field label={t("auth.password")} htmlFor="password" error={errors.password?.message} hint={t("auth.passwordHint")}>
          <input id="password" type="password" autoComplete="new-password" className={`input ${errors.password ? "input-error" : ""}`} {...register("password")} />
        </Field>

        <div className="space-y-2">
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" {...register("pd_consent")} />
            <span>
              {t("auth.pdConsentBefore")}
              <Link to="/legal/privacy" target="_blank" className="link">
                {t("auth.pdConsentLink")}
              </Link>
            </span>
          </label>
          {errors.pd_consent && <p className="text-sm text-danger">{errors.pd_consent.message}</p>}
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" {...register("pep_agreement")} />
            <span>
              {t("auth.pepBefore")}
              <Link to="/legal/pep" target="_blank" className="link">
                {t("auth.pepLink")}
              </Link>
            </span>
          </label>
          {errors.pep_agreement && <p className="text-sm text-danger">{errors.pep_agreement.message}</p>}
        </div>

        {formError && <p className="alert-error">{formError}</p>}

        {/* FR-3 / NFR-11: the button stays disabled while the form has errors */}
        <button type="submit" className="btn-primary w-full" disabled={!isValid || isSubmitting}>
          {isSubmitting && <Spinner />}
          {isSubmitting ? t("common.sending") : t("auth.registerSubmit")}
        </button>
        <p className="text-center text-sm text-soft">
          {t("auth.haveAccount")}{" "}
          <Link to="/login" className="link">
            {t("nav.login")}
          </Link>
        </p>
      </form>
    </div>
  );
}
