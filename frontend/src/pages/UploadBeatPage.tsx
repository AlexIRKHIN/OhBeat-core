// UI spec §1 "Upload a beat" (FR-1 … FR-5, AC-1 … AC-5).
//
// 1. Fields and files are checked in the browser; the button stays disabled while anything is wrong.
// 2. POST /beats -> the beat is created in `uploading`, every file gets a presigned POST form.
// 3. The files go straight to MinIO in parallel, each with its own progress bar.
//    A lost connection shows a toast and "Retry"; expired forms are re-issued (POST /beats/{id}/uploads).
// 4. POST /beats/{id}/confirm -> "The beat is uploaded and being processed" -> "My beats".
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { ApiError, NetworkError, api, uploadToS3 } from "../api/client";
import type { BeatCard, BeatCreated, Dictionaries, FileField, LicenseCode, PresignedForm, UploadsReissued } from "../api/types";
import { Dropzone, type UploadState } from "../components/Dropzone";
import { useToast } from "../components/Toasts";
import { ErrorState, Field, LoadingState, PageTitle, Spinner } from "../components/ui";
import { errorText } from "../lib/errors";
import { FILE_LIMITS, checkBeatFile, contentTypeFor, type FileProblem } from "../lib/beatFiles";

const LICENSES: LicenseCode[] = ["basic", "premium", "trackout", "exclusive"];
const LICENSE_NAMES: Record<LicenseCode, string> = { basic: "Basic", premium: "Premium", trackout: "Trackout", exclusive: "Exclusive" };
const NEEDS_STEMS: LicenseCode[] = ["trackout", "exclusive"];
const FIELDS: FileField[] = ["cover", "wav", "stems"];
const DESCRIPTION_MAX = 1000;

type Phase = "edit" | "creating" | "uploading" | "confirming";
type Files = Record<FileField, File | null>;

export function UploadBeatPage() {
  const [params] = useSearchParams();
  const fromId = params.get("from");
  const dictionaries = useQuery({ queryKey: ["dictionaries"], queryFn: () => api<Dictionaries>("/dictionaries", { auth: false }) });
  const source = useQuery({
    queryKey: ["beats", fromId],
    queryFn: () => api<BeatCard>(`/beats/${fromId}`),
    enabled: !!fromId,
  });

  if (dictionaries.isPending || (fromId && source.isPending)) return <LoadingState />;
  if (dictionaries.isError) return <ErrorState onRetry={() => void dictionaries.refetch()} />;
  return <UploadForm dictionaries={dictionaries.data} source={source.data ?? null} />;
}

function UploadForm({ dictionaries, source }: { dictionaries: Dictionaries; source: BeatCard | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();

  // --- Metadata and prices (AC-1, AC-3) ---
  const schema = useMemo(() => {
    const license = z.object({ on: z.boolean(), price: z.string() });
    return z
      .object({
        title: z.string().trim().min(3, t("validation.minLength", { count: 3 })).max(60, t("validation.maxLength", { count: 60 })),
        bpm: z
          .string()
          .regex(/^\d+$/, t("validation.required"))
          .refine((v) => Number(v) >= 40 && Number(v) <= 300, "40–300"),
        musical_key: z.string().min(1, t("validation.required")),
        genres: z.array(z.string()).min(1, t("upload.genresHint")).max(3, t("upload.genresHint")),
        description: z.string().max(DESCRIPTION_MAX, t("validation.maxLength", { count: DESCRIPTION_MAX })),
        licenses: z.object({ basic: license, premium: license, trackout: license, exclusive: license }),
      })
      .superRefine((v, ctx) => {
        const active = LICENSES.filter((code) => v.licenses[code].on);
        if (active.length === 0) ctx.addIssue({ code: "custom", path: ["licenses"], message: t("upload.atLeastOneLicense") });
        for (const code of active) {
          const price = Number(v.licenses[code].price);
          if (!/^\d+$/.test(v.licenses[code].price) || price < 100 || price > 500000) {
            ctx.addIssue({ code: "custom", path: ["licenses", code, "price"], message: t("upload.priceRange") });
          }
        }
      });
  }, [t]);
  type FormValues = z.infer<typeof schema>;

  const defaults = useMemo<FormValues>(() => {
    const licenses = Object.fromEntries(
      LICENSES.map((code) => {
        const found = source?.licenses.find((l) => l.code === code);
        return [code, { on: found?.is_active ?? false, price: found ? String(found.price) : "" }];
      }),
    ) as FormValues["licenses"];
    return {
      title: source?.title ?? "",
      bpm: source ? String(source.bpm) : "",
      musical_key: source?.musical_key ?? "",
      genres: source?.genres ?? [],
      description: source?.description ?? "",
      licenses,
    };
  }, [source]);

  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    setError,
    trigger,
    formState: { errors, isValid },
  } = useForm<FormValues>({ resolver: zodResolver(schema), mode: "onTouched", defaultValues: defaults });

  useEffect(() => {
    if (source) void trigger();
  }, [source, trigger]);

  // --- Files (AC-2) ---
  const [files, setFiles] = useState<Files>({ cover: null, wav: null, stems: null });
  const [fileErrors, setFileErrors] = useState<Record<FileField, string | null>>({ cover: null, wav: null, stems: null });
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const licenses = watch("licenses");
  const stemsNeeded = NEEDS_STEMS.some((code) => licenses[code].on);

  const problemText = (problem: FileProblem): string =>
    problem === "ratio" ? t("upload.badCoverRatio") : problem === "dimensions" ? t("upload.badCoverSize") : t("upload.badFile");

  const chooseFile = async (field: FileField, file: File) => {
    const problem = await checkBeatFile(field, file);
    if (problem) {
      // AC-2: a red notification, the upload does not start
      toast.show(problemText(problem), "error");
      setFileErrors((e) => ({ ...e, [field]: problemText(problem) }));
      return;
    }
    setFileErrors((e) => ({ ...e, [field]: null }));
    setFiles((f) => ({ ...f, [field]: file }));
    if (field === "cover") {
      if (coverPreview) URL.revokeObjectURL(coverPreview);
      setCoverPreview(URL.createObjectURL(file));
    }
  };

  const removeFile = (field: FileField) => {
    setFiles((f) => ({ ...f, [field]: null }));
    if (field === "cover" && coverPreview) {
      URL.revokeObjectURL(coverPreview);
      setCoverPreview(null);
    }
  };

  const filesReady = !!files.wav && !!files.cover && (!stemsNeeded || !!files.stems) && !Object.values(fileErrors).some(Boolean);

  // --- Sending and uploading (AC-4, AC-5) ---
  const [phase, setPhase] = useState<Phase>("edit");
  const [uploads, setUploads] = useState<Record<FileField, UploadState>>({ cover: { kind: "idle" }, wav: { kind: "idle" }, stems: { kind: "idle" } });
  const beatId = useRef<number | null>(null);
  const forms = useRef<Partial<Record<FileField, PresignedForm>>>({});
  const formsExpireAt = useRef(0);
  const locked = phase !== "edit";
  const sentFields = useRef<FileField[]>([]); // files declared in POST /beats
  const doneFields = useRef(new Set<FileField>()); // files that reached the storage

  // Leaving the page in the middle of an upload asks for a confirmation
  useEffect(() => {
    if (!locked) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = t("upload.leaveWarning");
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [locked, t]);

  const reissueForms = async (fields: FileField[]) => {
    const fresh = await api<UploadsReissued>(`/beats/${beatId.current}/uploads`, { method: "POST", body: { files: fields } });
    forms.current = { ...forms.current, ...fresh.uploads };
    formsExpireAt.current = Date.parse(fresh.upload_expires_at);
  };

  const uploadOne = async (field: FileField, allowReissue = true): Promise<boolean> => {
    const file = files[field];
    if (!file) return true;
    try {
      // FR-6: forms live 1 hour; take new ones a minute before they expire
      if (Date.now() > formsExpireAt.current - 60_000) await reissueForms([field]);
      setUploads((u) => ({ ...u, [field]: { kind: "uploading", percent: 0 } }));
      await uploadToS3(forms.current[field]!, file, (percent) =>
        setUploads((u) => ({ ...u, [field]: { kind: "uploading", percent } })),
      ).promise;
      setUploads((u) => ({ ...u, [field]: { kind: "done" } }));
      doneFields.current.add(field);
      return true;
    } catch (error) {
      const text = error instanceof Error ? error.message : "";
      if (allowReissue && /AccessDenied|expired/i.test(text)) {
        // The policy expired while the page was open: new forms and one more attempt
        try {
          await reissueForms([field]);
          return uploadOne(field, false);
        } catch {
          /* falls through to the failure below */
        }
      }
      if (error instanceof NetworkError) toast.show(t("common.serverUnreachable"), "error"); // NFR-19
      const message = error instanceof NetworkError ? t("common.offline") : t("upload.uploadFailed");
      setUploads((u) => ({ ...u, [field]: { kind: "failed", message } }));
      return false;
    }
  };

  const confirm = async () => {
    setPhase("confirming");
    try {
      await api(`/beats/${beatId.current}/confirm`, { method: "POST" });
      toast.show(t("upload.done"), "success"); // FR-5
      navigate("/producer/beats");
    } catch (error) {
      if (error instanceof ApiError && error.errorCode === "FILES_MISSING") {
        // AC-5: say which file did not reach the storage
        for (const detail of error.details) {
          const field = detail.field.replace("files.", "") as FileField;
          doneFields.current.delete(field);
          setUploads((u) => ({ ...u, [field]: { kind: "failed", message: detail.issue } }));
        }
        toast.show(t("upload.filesMissing"), "error");
        setPhase("uploading");
      } else if (error instanceof ApiError && error.errorCode === "INVALID_STATUS") {
        navigate("/producer/beats"); // already confirmed (e.g. a double click)
      } else {
        toast.show(errorText(error), "error");
        setPhase("uploading");
      }
    }
  };

  const uploadAndConfirm = async (fields: FileField[]) => {
    setPhase("uploading");
    await Promise.all(fields.map((field) => uploadOne(field)));
    // confirm only when every declared file is in the storage
    if (sentFields.current.every((f) => doneFields.current.has(f))) await confirm();
  };

  const retryFailed = () => {
    const failed = sentFields.current.filter((f) => uploads[f].kind === "failed");
    void uploadAndConfirm(failed);
  };


  const onSubmit = async (values: FormValues) => {
    const included = FIELDS.filter((f) => files[f]);
    const body = {
      title: values.title,
      genres: values.genres,
      bpm: Number(values.bpm),
      musical_key: values.musical_key,
      description: values.description.trim() || null,
      licenses: LICENSES.filter((c) => values.licenses[c].on).map((code) => ({ code, price: Number(values.licenses[code].price) })),
      files: Object.fromEntries(
        included.map((f) => [f, { name: files[f]!.name, size_bytes: files[f]!.size, content_type: contentTypeFor(f, files[f]!) }]),
      ),
    };
    setPhase("creating");
    try {
      const created = await api<BeatCreated>("/beats", { method: "POST", body });
      beatId.current = created.id;
      forms.current = created.uploads;
      formsExpireAt.current = Date.parse(created.upload_expires_at);
      sentFields.current = included;
      await uploadAndConfirm(included);
    } catch (error) {
      setPhase("edit");
      if (error instanceof ApiError && error.errorCode === "VALIDATION_ERROR") {
        // AC-5: highlight the fields from `details`, the text goes right under each one
        const activeCodes = body.licenses.map((l) => l.code);
        for (const { field, issue } of error.details) {
          const license = field.match(/^licenses\[(\d+)\]/);
          const file = field.match(/^files\.(wav|stems|cover)/);
          if (license) setError(`licenses.${activeCodes[Number(license[1])]}.price` as never, { message: issue });
          else if (file) setFileErrors((e) => ({ ...e, [file[1]]: issue }));
          else if (field.startsWith("genres")) setError("genres", { message: issue });
          else if (["title", "bpm", "musical_key", "description"].includes(field)) setError(field as never, { message: issue });
        }
      } else {
        toast.show(errorText(error), "error");
      }
    }
  };

  const genres = watch("genres");
  const descriptionLength = watch("description")?.length ?? 0;
  const bpmField = register("bpm");
  const canSubmit = isValid && filesReady && phase === "edit";

  const toggleGenre = useCallback(
    (name: string, selected: string[]) =>
      setValue("genres", selected.includes(name) ? selected.filter((g) => g !== name) : [...selected, name], {
        shouldValidate: true,
        shouldTouch: true,
      }),
    [setValue],
  );

  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle>{t("upload.title")}</PageTitle>
      {source && <p className="mb-4 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-soft">{t("upload.reuploadNote")}</p>}

      <form className="space-y-5" onSubmit={handleSubmit(onSubmit)} noValidate>
        {/* File zones stay outside disabled fieldsets: their "Retry" buttons must work during the upload */}
        <div className="card grid gap-5 md:grid-cols-[14rem_1fr]">
          {/* 1. Cover */}
          <Dropzone
            id="cover"
            label={t("upload.cover")}
            hint={t("upload.coverHint")}
            accept={FILE_LIMITS.cover.accept}
            file={files.cover}
            preview={coverPreview}
            error={fileErrors.cover}
            upload={uploads.cover}
            locked={locked}
            onFile={(f) => void chooseFile("cover", f)}
            onRemove={() => removeFile("cover")}
            onRetry={() => void uploadAndConfirm(["cover"])}
          />

          <fieldset disabled={locked} className="min-w-0 space-y-4">
            {/* 2. Title */}
            <Field label={t("upload.titleLabel")} htmlFor="title" error={errors.title?.message}>
              <input id="title" className={`input ${errors.title ? "input-error" : ""}`} maxLength={80} {...register("title")} />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              {/* 3. BPM: only digits can be typed */}
              <Field label={t("upload.bpm")} htmlFor="bpm" error={errors.bpm?.message}>
                <input
                  id="bpm"
                  inputMode="numeric"
                  className={`input ${errors.bpm ? "input-error" : ""}`}
                  {...bpmField}
                  onChange={(e) => {
                    // Filter first, then cut: maxLength would cut a pasted "bpm 120" before the filter runs
                    e.target.value = e.target.value.replace(/\D/g, "").slice(0, 3);
                    return bpmField.onChange(e);
                  }}
                />
              </Field>

              {/* 4. Key: no default value */}
              <Field label={t("upload.key")} htmlFor="musical_key" error={errors.musical_key?.message}>
                <select id="musical_key" className={`input ${errors.musical_key ? "input-error" : ""}`} {...register("musical_key")}>
                  <option value="">{t("upload.keyPlaceholder")}</option>
                  {dictionaries.musical_keys.map((key) => (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            {/* 5. Genres: after the third one the rest are blocked */}
            <div className="space-y-1">
              <span className="block text-sm font-medium text-cyan">{t("upload.genres")}</span>
              <Controller
                control={control}
                name="genres"
                render={() => (
                  <div className="flex flex-wrap gap-2">
                    {dictionaries.genres.map(({ name }) => {
                      const selected = genres.includes(name);
                      const blocked = !selected && genres.length >= 3;
                      return (
                        <button
                          key={name}
                          type="button"
                          aria-pressed={selected}
                          disabled={blocked || locked}
                          onClick={() => toggleGenre(name, genres)}
                          className={`rounded-full border px-3 py-1 text-xs transition ${
                            selected ? "border-accent bg-accent/20 text-cyan" : "border-line bg-panel-2 text-soft hover:border-accent/50"
                          } disabled:cursor-not-allowed disabled:opacity-40`}
                        >
                          {name}
                        </button>
                      );
                    })}
                  </div>
                )}
              />
              {errors.genres ? <p className="text-sm text-danger">{errors.genres.message}</p> : <p className="text-xs text-muted">{t("upload.genresHint")}</p>}
            </div>
          </fieldset>

          {/* 6. Description with a counter */}
          <fieldset disabled={locked} className="md:col-span-2">
            <Field
              label={t("upload.description")}
              htmlFor="description"
              error={errors.description?.message}
              hint={t("profile.charsLeft", { count: Math.max(0, DESCRIPTION_MAX - descriptionLength) })}
            >
              <textarea id="description" rows={3} className={`input ${errors.description ? "input-error" : ""}`} {...register("description")} />
            </Field>
          </fieldset>
        </div>

        {/* 7–8. Master WAV and Stems ZIP */}
        <div className="card grid gap-5 md:grid-cols-2">
          <Dropzone
            id="wav"
            label={t("upload.wav")}
            hint={t("upload.wavHint")}
            accept={FILE_LIMITS.wav.accept}
            file={files.wav}
            error={fileErrors.wav}
            upload={uploads.wav}
            locked={locked}
            onFile={(f) => void chooseFile("wav", f)}
            onRemove={() => removeFile("wav")}
            onRetry={() => void uploadAndConfirm(["wav"])}
          />
          <Dropzone
            id="stems"
            label={t("upload.stems")}
            hint={stemsNeeded && !files.stems ? <span className="text-orange">{t("upload.stemsRequired")}</span> : t("upload.stemsHint")}
            accept={FILE_LIMITS.stems.accept}
            file={files.stems}
            error={fileErrors.stems}
            upload={uploads.stems}
            locked={locked}
            onFile={(f) => void chooseFile("stems", f)}
            onRemove={() => removeFile("stems")}
            onRetry={() => void uploadAndConfirm(["stems"])}
          />
        </div>

        {/* 9. License grid: 4 fixed rows */}
        <fieldset disabled={locked} className="card space-y-3">
          <legend className="sr-only">{t("upload.licenses")}</legend>
          <p className="text-sm font-medium text-cyan">{t("upload.licenses")}</p>
          {LICENSES.map((code) => {
            const on = licenses[code].on;
            const priceError = errors.licenses?.[code]?.price?.message;
            return (
              <div key={code} className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1 sm:grid-cols-[10rem_12rem_1fr]">
                <label className="flex items-center gap-2 pt-2 text-sm">
                  <input type="checkbox" {...register(`licenses.${code}.on`, { onChange: () => void trigger("licenses") })} />
                  {LICENSE_NAMES[code]}
                </label>
                <div>
                  <input
                    aria-label={`${LICENSE_NAMES[code]} — ${t("upload.price")}`}
                    inputMode="numeric"
                    placeholder={t("upload.price")}
                    disabled={!on || locked}
                    className={`input ${priceError ? "input-error" : ""}`}
                    {...register(`licenses.${code}.price`, {
                      onChange: (e) => {
                        e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6);
                      },
                    })}
                  />
                  {on && priceError && <p className="mt-1 text-sm text-danger">{priceError}</p>}
                </div>
              </div>
            );
          })}
          {errors.licenses?.root?.message || (errors.licenses as { message?: string } | undefined)?.message ? (
            <p className="text-sm text-danger">{errors.licenses?.root?.message ?? (errors.licenses as { message?: string }).message}</p>
          ) : (
            <p className="text-xs text-muted">{t("upload.licensesHint")}</p>
          )}
        </fieldset>

        {/* 10. Submit */}
        <div className="flex flex-wrap items-center gap-3">
          {phase === "uploading" && sentFields.current.some((f) => uploads[f].kind === "failed") ? (
            <button type="button" className="btn-primary" onClick={retryFailed}>
              {t("upload.retryAll")}
            </button>
          ) : (
            <button type="submit" className="btn-primary" disabled={!canSubmit}>
              {phase !== "edit" && <Spinner />}
              {phase === "creating" ? t("upload.sending") : phase === "uploading" ? t("upload.uploadingFiles") : phase === "confirming" ? t("upload.confirming") : t("upload.submit")}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
