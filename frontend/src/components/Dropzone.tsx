// File zone: Drag-and-Drop or the file dialog (FR-1), progress bar (FR-4, NFR-10), "Retry" after a failure.
import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { formatBytes } from "../lib/beatFiles";

export type UploadState =
  | { kind: "idle" }
  | { kind: "uploading"; percent: number }
  | { kind: "done" }
  | { kind: "failed"; message: string };

interface Props {
  id: string;
  label: string;
  hint: ReactNode;
  accept: string;
  file: File | null;
  error?: string | null;
  upload: UploadState;
  locked: boolean;
  preview?: string | null;
  onFile: (file: File) => void;
  onRemove?: () => void;
  onRetry?: () => void;
}

export function Dropzone({ id, label, hint, accept, file, error, upload, locked, preview, onFile, onRemove, onRetry }: Props) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const pick = (files: FileList | null) => {
    if (files?.[0] && !locked) onFile(files[0]);
  };

  return (
    <div className="space-y-1">
      <span id={`${id}-label`} className="block text-sm font-medium text-cyan">
        {label}
      </span>
      <div
        role="button"
        tabIndex={locked ? -1 : 0}
        aria-labelledby={`${id}-label`}
        aria-disabled={locked}
        onClick={() => !locked && input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !locked && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          if (!locked) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          pick(e.dataTransfer.files);
        }}
        className={`flex min-h-[5.5rem] items-center gap-3 rounded-md border border-dashed px-3 py-3 transition ${
          error ? "border-danger" : over ? "border-accent bg-accent/10" : "border-line bg-panel-2"
        } ${locked ? "cursor-default" : "cursor-pointer hover:border-accent/60"}`}
      >
        {preview && <img src={preview} alt="" className="h-16 w-16 shrink-0 rounded object-cover" />}
        <div className="min-w-0 flex-1 text-sm">
          {file ? (
            <>
              <p className="truncate text-ink">{file.name}</p>
              <p className="text-xs text-muted">{formatBytes(file.size)}</p>
            </>
          ) : (
            <p className="text-soft">{t("upload.dropOrChoose")}</p>
          )}
          {upload.kind === "uploading" && (
            <div className="mt-2" aria-label={`${upload.percent}%`}>
              <div className="h-1.5 overflow-hidden rounded bg-line">
                <div className="h-full bg-orange transition-all" style={{ width: `${upload.percent}%` }} />
              </div>
              <p className="mt-1 text-xs text-muted">{upload.percent}%</p>
            </div>
          )}
          {upload.kind === "done" && <p className="mt-1 text-xs text-accent-light">100% ✓</p>}
          {upload.kind === "failed" && <p className="mt-1 text-xs text-danger">{upload.message}</p>}
        </div>
        {upload.kind === "failed" && onRetry && (
          <button type="button" className="btn-secondary px-3 py-1" onClick={(e) => (e.stopPropagation(), onRetry())}>
            {t("upload.retry")}
          </button>
        )}
        {file && !locked && onRemove && (
          <button type="button" className="text-xs text-muted hover:text-danger" onClick={(e) => (e.stopPropagation(), onRemove())}>
            {t("upload.remove")}
          </button>
        )}
      </div>
      {error ? <p className="text-sm text-danger">{error}</p> : <p className="text-xs text-muted">{hint}</p>}
      <input
        ref={input}
        id={id}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          pick(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
