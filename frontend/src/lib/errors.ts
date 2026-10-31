// Turning API errors into what the user sees.
import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError, NetworkError } from "../api/client";
import i18n from "../i18n";

/** AC-5 / NFR-11: highlight the fields listed in `details` and put the text under each of them.
 *  Returns true when at least one field got an error. */
export function applyFieldErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  knownFields: readonly string[],
): boolean {
  if (!(error instanceof ApiError)) return false;
  let applied = false;
  for (const detail of error.details) {
    if (knownFields.includes(detail.field)) {
      setError(detail.field as Path<T>, { type: "server", message: detail.issue });
      applied = true;
    }
  }
  return applied;
}

export function errorText(error: unknown): string {
  if (error instanceof NetworkError) return i18n.t("common.serverUnreachable");
  if (error instanceof ApiError) return error.message;
  return i18n.t("common.errorGeneric");
}
