// Administration (FR-35 … FR-37, REST API §2.13): types and the small rules of the filter menus.

export interface AuditEntry {
  id: number;
  occurred_at: string;
  action: string;
  entity: string;
  entity_id: number | null;
  actor: { id: number; email: string | null } | null;
  ip: string | null;
  details: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditEntry[];
  next_cursor: string | null;
}

export interface GenreAdmin {
  id: number;
  name: string;
  beats_count: number;
}

export interface StopWord {
  id: number;
  word: string;
  created_at: string;
}

export interface ProcessingBeat {
  id: number;
  title: string;
  producer: string;
  producer_id: number;
  processing_since: string;
  stuck: boolean;
}

export interface AuditFilters {
  action: string;
  entity: string;
  entity_id: string;
  from: string;
  to: string;
}

export const EMPTY_AUDIT_FILTERS: AuditFilters = { action: "", entity: "", entity_id: "", from: "", to: "" };

/** Groups for the action menu: "payment.created", "payment.succeeded" → "payment." (GAP-75). */
export function actionGroups(actions: string[]): string[] {
  const groups = new Set(actions.filter((a) => a.includes(".")).map((a) => `${a.split(".")[0]}.`));
  return [...groups].sort();
}

/** Only filled filters go to the query string. */
export function auditParams(filters: AuditFilters, cursor?: string | null): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value.trim()) params.set(key, value.trim());
  if (cursor) params.set("cursor", cursor);
  return params;
}
