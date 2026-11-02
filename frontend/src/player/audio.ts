// Rules of the preview player from RFC_Audio_Streaming.md §4, kept apart from React so they can be tested.

/** The part of HTMLAudioElement the player uses. */
export interface MediaElement {
  src: string;
  currentTime: number;
  preload: string;
  pause(): void;
  load(): void;
  play(): Promise<void>;
  removeAttribute(name: string): void;
}

/** Nothing is downloaded until Play is pressed (RFC §4 "lazy loading"). */
export function prepare(el: MediaElement): void {
  el.preload = "none";
}

/**
 * Switch to another preview. RFC §4 "correct disconnection": pause(), remove the `src` attribute
 * and call load() — this aborts the background download of the previous track. Only then the new
 * source is set; the browser itself asks MinIO for byte ranges (HTTP 206).
 */
export function switchTo(el: MediaElement, src: string): Promise<void> {
  el.pause();
  el.removeAttribute("src");
  el.load();
  el.src = src;
  return el.play();
}

/** Seeking: the browser requests the missing byte range itself (RFC §3.2). */
export function seek(el: MediaElement, seconds: number): void {
  el.currentTime = Math.max(0, seconds);
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
