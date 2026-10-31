// Sign-in (REST API §2.8). The server answers the same for an unknown email and a wrong password.
import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { api, type TokenPair } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Field, PageTitle, Spinner } from "../components/ui";
import { errorText } from "../lib/errors";

/** Only local paths are accepted as a return address, never another site. */
function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/profile";
}

export function LoginPage() {
  const { t } = useTranslation();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [formError, setFormError] = useState<string | null>(null);

  const schema = useMemo(
    () =>
      z.object({
        email: z.string().trim().min(1, t("validation.required")),
        password: z.string().min(1, t("validation.required")),
      }),
    [t],
  );
  type FormValues = z.infer<typeof schema>;

  const {
    register,
    handleSubmit,
    formState: { errors, isValid, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), mode: "onChange" });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      const pair = await api<TokenPair>("/auth/login", { method: "POST", body: values, auth: false });
      await signIn(pair);
      navigate(safeNext(params.get("next")));
    } catch (error) {
      setFormError(errorText(error));
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("auth.loginTitle")}</PageTitle>
      <form className="card space-y-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label={t("auth.email")} htmlFor="email" error={errors.email?.message}>
          <input id="email" type="email" autoComplete="email" className="input" {...register("email")} />
        </Field>
        <Field label={t("auth.password")} htmlFor="password" error={errors.password?.message}>
          <input id="password" type="password" autoComplete="current-password" className="input" {...register("password")} />
        </Field>
        {formError && (
          <p role="alert" className="alert-error">
            {formError}
          </p>
        )}
        <button type="submit" className="btn-primary w-full" disabled={!isValid || isSubmitting}>
          {isSubmitting && <Spinner />}
          {t("auth.loginSubmit")}
        </button>
        <p className="text-center text-sm text-soft">
          {t("auth.noAccount")}{" "}
          <Link to="/register" className="link">
            {t("nav.register")}
          </Link>
        </p>
      </form>
    </div>
  );
}
