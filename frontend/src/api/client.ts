// HTTP client of the SPA.
// * The access token lives only in memory; the refresh token in localStorage
//   (the API takes it in the request body, so an httpOnly cookie is not an option).
// * On 401 the client refreshes the pair once and repeats the request.
// * Refresh tokens rotate (REST API §2.8): presenting an already used token revokes
//   the whole session. So only one refresh may run at a time, also across browser tabs.
import i18n from "../i18n";

export interface ApiErrorDetail {
  field: string;
  issue: string;
  // 409 PRICE_CHANGED / BEAT_RESERVED of POST /orders name the beat and the new price
  beat_id?: number;
  license?: string;
  price?: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public errorCode: string,
    message: string,
    public details: ApiErrorDetail[] = [],
  ) {
    super(message);
  }
}

/** The server could not be reached at all (no internet, API is down). */
export class NetworkError extends Error {}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  expires_in: number;
}

const REFRESH_KEY = "ohbeat.refresh";
let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
const sessionListeners = new Set<() => void>();

function readRefresh(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function writeRefresh(token: string | null): void {
  try {
    if (token) localStorage.setItem(REFRESH_KEY, token);
    else localStorage.removeItem(REFRESH_KEY);
  } catch {
    // private mode: the session will not survive a reload
  }
}

export const session = {
  setTokens(pair: TokenPair): void {
    accessToken = pair.access_token;
    writeRefresh(pair.refresh_token);
  },
  clear(): void {
    accessToken = null;
    writeRefresh(null);
    sessionListeners.forEach((listener) => listener());
  },
  hasRefreshToken(): boolean {
    return readRefresh() !== null;
  },
  refreshToken(): string | null {
    return readRefresh();
  },
  /** Called when the session ends by itself (refresh failed). */
  onExpired(listener: () => void): () => void {
    sessionListeners.add(listener);
    return () => sessionListeners.delete(listener);
  },
};

async function doRefresh(): Promise<boolean> {
  const token = readRefresh();
  if (!token) return false;
  const response = await fetch("/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }),
  });
  if (!response.ok) {
    // Another tab may have rotated the token meanwhile: then a newer one is already stored
    if (readRefresh() !== token) return doRefresh();
    session.clear();
    return false;
  }
  session.setTokens((await response.json()) as TokenPair);
  return true;
}

/** Refresh the token pair; parallel callers share one request. */
export function refreshTokens(): Promise<boolean> {
  if (!refreshInFlight) {
    const run = () => doRefresh().catch(() => false);
    // Web Locks serialize refreshes between tabs (Safari 15.4+, Chrome, Firefox); older browsers just run
    const locked =
      typeof navigator !== "undefined" && "locks" in navigator
        ? navigator.locks.request("ohbeat-refresh", run)
        : run();
    refreshInFlight = locked.finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
}

export async function api<T>(path: string, { method = "GET", body, auth = true }: RequestOptions = {}): Promise<T> {
  const send = () => {
    const headers: Record<string, string> = { "Accept-Language": i18n.language };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
    return fetch(`/v1${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  };

  let response: Response;
  try {
    if (auth && !accessToken && session.hasRefreshToken()) await refreshTokens();
    response = await send();
    if (response.status === 401 && auth && session.hasRefreshToken() && (await refreshTokens())) {
      response = await send();
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new NetworkError(String(error));
  }

  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    // A proxy answers 502/504 when Core API is down: treat as "server unreachable"
    if (!data?.error_code && response.status >= 502) throw new NetworkError(`HTTP ${response.status}`);
    throw new ApiError(
      response.status,
      data?.error_code ?? "INTERNAL_ERROR",
      data?.message ?? i18n.t("common.errorGeneric"),
      data?.details ?? [],
    );
  }
  return data as T;
}

/** Upload a file straight to S3 by a presigned POST form, with progress (FR-4, NFR-10).
 *  XMLHttpRequest is used because fetch has no upload progress events. */
export function uploadToS3(
  form: { url: string; fields: Record<string, string> },
  file: File,
  onProgress: (percent: number) => void,
): { promise: Promise<void>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<void>((resolve, reject) => {
    const data = new FormData();
    Object.entries(form.fields).forEach(([key, value]) => data.append(key, value));
    data.append("file", file); // the file must be the last field of the form
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(xhr.responseText)));
    xhr.onerror = () => reject(new NetworkError("upload failed"));
    xhr.onabort = () => reject(new NetworkError("upload aborted"));
    xhr.open("POST", form.url);
    xhr.send(data);
  });
  return { promise, abort: () => xhr.abort() };
}
