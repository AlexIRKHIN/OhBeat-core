// FR-32: public profile — name, bio, avatar (NFR-22).
// The avatar goes from the browser straight to S3 (presigned POST), Core API then checks and publishes it.
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, uploadToS3 } from "../api/client";
import type { Profile, UploadForm } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toasts";
import { Field, PageTitle, Spinner } from "../components/ui";
import { applyFieldErrors, errorText } from "../lib/errors";
import { IMAGE_TYPES, MAX_IMAGE_BYTES, MAX_IMAGE_SIDE, readImageSize } from "../lib/validation";
import { z } from "zod";

const BIO_MAX = 1000;

type AvatarState =
  | { kind: "unchanged" }
  | { kind: "removed" }
  | { kind: "uploading"; preview: string; percent: number }
  | { kind: "uploaded"; preview: string; key: string };

export function ProfilePage() {
  const { t } = useTranslation();
  const { user, reloadUser } = useAuth();
  const toast = useToast();
  const [avatar, setAvatar] = useState<AvatarState>({ kind: "unchanged" });
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const abortUpload = useRef<(() => void) | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const schema = useMemo(
    () =>
      z.object({
        display_name: z
          .string()
          .trim()
          .min(2, t("validation.minLength", { count: 2 }))
          .max(100, t("validation.maxLength", { count: 100 })),
        bio: z.string().max(BIO_MAX, t("validation.maxLength", { count: BIO_MAX })),
      }),
    [t],
  );
  type FormValues = z.infer<typeof schema>;

  const {
    register,
    handleSubmit,
    setError,
    reset,
    watch,
    formState: { errors, isValid, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    mode: "onChange",
    defaultValues: { display_name: user?.display_name ?? "", bio: user?.bio ?? "" },
  });

  useEffect(() => () => abortUpload.current?.(), []);

  if (!user) return null;

  const chooseFile = async (file: File | undefined) => {
    setAvatarError(null);
    if (!file) return;
    // Checks before the upload starts: type, size and resolution (NFR-22)
    if (!IMAGE_TYPES.includes(file.type)) return setAvatarError(t("validation.imageType"));
    if (file.size > MAX_IMAGE_BYTES) return setAvatarError(t("validation.imageSize"));
    try {
      const { width, height } = await readImageSize(file);
      if (width > MAX_IMAGE_SIDE || height > MAX_IMAGE_SIDE) return setAvatarError(t("validation.imageDimensions"));
    } catch {
      return setAvatarError(t("validation.imageType"));
    }

    const preview = URL.createObjectURL(file);
    setAvatar({ kind: "uploading", preview, percent: 0 });
    try {
      const form = await api<UploadForm>("/users/me/avatar", {
        method: "POST",
        body: { name: file.name, size_bytes: file.size, content_type: file.type },
      });
      const upload = uploadToS3(form, file, (percent) => setAvatar({ kind: "uploading", preview, percent }));
      abortUpload.current = upload.abort;
      await upload.promise;
      setAvatar({ kind: "uploaded", preview, key: form.key });
    } catch (error) {
      setAvatar({ kind: "unchanged" });
      setAvatarError(`${t("profile.uploadFailed")}. ${errorText(error)}`);
    } finally {
      abortUpload.current = null;
    }
  };

  const onSubmit = async (values: FormValues) => {
    const body: Record<string, unknown> = { display_name: values.display_name, bio: values.bio || null };
    if (avatar.kind === "uploaded") body.avatar_key = avatar.key;
    if (avatar.kind === "removed") body.avatar_key = null;
    try {
      const saved = await api<Profile>("/users/me", { method: "PUT", body });
      reset({ display_name: saved.display_name, bio: saved.bio ?? "" });
      setAvatar({ kind: "unchanged" });
      await reloadUser();
      toast.show(t("profile.saved"), "success");
    } catch (error) {
      const fieldErrors = applyFieldErrors(error, setError, ["display_name", "bio"]);
      if (error instanceof Error && "details" in error) {
        const avatarDetail = (error as { details: { field: string; issue: string }[] }).details.find(
          (d) => d.field === "avatar_key",
        );
        if (avatarDetail) return setAvatarError(avatarDetail.issue);
      }
      if (!fieldErrors) toast.show(errorText(error), "error");
    }
  };

  const shownAvatar =
    avatar.kind === "uploading" || avatar.kind === "uploaded"
      ? avatar.preview
      : avatar.kind === "removed"
        ? null
        : user.avatar_url;
  const bioLength = watch("bio")?.length ?? 0;
  const uploading = avatar.kind === "uploading";

  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle>{t("profile.title")}</PageTitle>
      <form className="card space-y-5" onSubmit={handleSubmit(onSubmit)} noValidate>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="h-24 w-24 shrink-0 overflow-hidden rounded-full bg-panel-2">
            {shownAvatar ? (
              <img src={shownAvatar} alt={t("profile.avatar")} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-3xl text-muted">
                {user.display_name.slice(0, 1).toUpperCase()}
              </div>
            )}
          </div>
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" disabled={uploading} onClick={() => fileInput.current?.click()}>
                {t("profile.avatarChoose")}
              </button>
              {shownAvatar && !uploading && (
                <button type="button" className="btn-secondary" onClick={() => setAvatar({ kind: "removed" })}>
                  {t("profile.avatarRemove")}
                </button>
              )}
            </div>
            <input
              ref={fileInput}
              type="file"
              accept={IMAGE_TYPES.join(",")}
              className="hidden"
              onChange={(e) => {
                void chooseFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            {uploading ? (
              <div className="w-56">
                {/* NFR-10: upload progress bar */}
                <div className="h-2 overflow-hidden rounded bg-panel-2">
                  <div className="h-full bg-orange transition-all" style={{ width: `${avatar.percent}%` }} />
                </div>
                <p className="mt-1 text-xs text-muted">{t("profile.uploading", { percent: avatar.percent })}</p>
              </div>
            ) : (
              <p className={`text-xs ${avatarError ? "text-danger" : "text-muted"}`}>{avatarError ?? t("profile.avatarRules")}</p>
            )}
          </div>
        </div>

        <Field label={t("profile.displayName")} htmlFor="display_name" error={errors.display_name?.message}>
          <input id="display_name" className={`input ${errors.display_name ? "input-error" : ""}`} {...register("display_name")} />
        </Field>
        <Field
          label={t("profile.bio")}
          htmlFor="bio"
          error={errors.bio?.message}
          hint={t("profile.charsLeft", { count: Math.max(0, BIO_MAX - bioLength) })}
        >
          <textarea id="bio" rows={4} className={`input ${errors.bio ? "input-error" : ""}`} {...register("bio")} />
        </Field>

        <p className="text-sm text-soft">
          {t("profile.roles")}: {user.roles.map((role) => t(`profile.role_${role}`)).join(", ")}
        </p>

        <button type="submit" className="btn-primary" disabled={!isValid || isSubmitting || uploading}>
          {isSubmitting && <Spinner />}
          {isSubmitting ? t("common.saving") : t("common.save")}
        </button>
      </form>
    </div>
  );
}
