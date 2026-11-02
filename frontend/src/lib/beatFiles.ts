// Client-side checks of beat files before any upload starts (UI spec §1 items 1, 7, 8; AC-2; NFR-3, NFR-22).
// The same limits are checked again by Core API (FR-6) and by Media Worker on the content (FR-9).
import type { FileField } from "../api/types";
import { MAX_IMAGE_SIDE, readImageSize } from "./validation";

const MB = 1024 * 1024;

export const FILE_LIMITS: Record<FileField, { maxBytes: number; extensions: string[]; accept: string }> = {
  wav: { maxBytes: 200 * MB, extensions: ["wav"], accept: ".wav,audio/wav,audio/x-wav" },
  stems: { maxBytes: 1024 * MB, extensions: ["zip"], accept: ".zip,application/zip" },
  cover: { maxBytes: 5 * MB, extensions: ["jpg", "jpeg", "png", "webp"], accept: ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" },
};

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

const COVER_TYPES: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp" };

/** Content type for the API. Browsers sometimes give an empty type for .wav/.zip, so it is derived from the extension. */
export function contentTypeFor(field: FileField, file: File): string {
  if (field === "wav") return file.type && file.type.includes("wav") ? file.type : "audio/wav";
  if (field === "stems") return file.type && file.type.includes("zip") ? file.type : "application/zip";
  return COVER_TYPES[extensionOf(file.name)] ?? file.type;
}

export type FileProblem = "format" | "size" | "ratio" | "dimensions";

/** Returns the problem or null. Covers are also checked for 1:1 and 2048 px (AC-2). */
export async function checkBeatFile(field: FileField, file: File): Promise<FileProblem | null> {
  const rule = FILE_LIMITS[field];
  if (!rule.extensions.includes(extensionOf(file.name))) return "format";
  if (file.size > rule.maxBytes) return "size";
  if (field === "cover") {
    try {
      const { width, height } = await readImageSize(file);
      if (width !== height) return "ratio";
      if (width > MAX_IMAGE_SIDE) return "dimensions";
    } catch {
      return "format";
    }
  }
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
