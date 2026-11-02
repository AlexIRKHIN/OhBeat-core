// The one preview player of the application (US-A1, UC-3, RFC_Audio_Streaming.md).
// Play buttons in cards control this single <audio> element instead of creating their own,
// so two previews never play at once and the previous download is aborted on switching.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { formatTime, prepare, seek as seekTo, switchTo } from "./audio";

export interface Track {
  id: number;
  title: string;
  producer: string;
  previewUrl: string;
  coverUrl: string | null;
  durationSec: number | null;
}

interface PlayerState {
  track: Track | null;
  playing: boolean;
  buffering: boolean;
  time: number;
  duration: number;
  toggle: (track: Track) => void;
  seek: (seconds: number) => void;
}

const PlayerContext = createContext<PlayerState | null>(null);

export function usePlayer(): PlayerState {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("usePlayer outside PlayerProvider");
  return value;
}

/** SVG icons: a text "▶" turns into a colour emoji on Windows. */
function PlayIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 translate-x-[1px]" fill="currentColor" aria-hidden>
      <path d="M4 2.5v11a.5.5 0 0 0 .77.42l8.5-5.5a.5.5 0 0 0 0-.84l-8.5-5.5A.5.5 0 0 0 4 2.5z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor" aria-hidden>
      <rect x="3.5" y="2.5" width="3" height="11" rx="0.8" />
      <rect x="9.5" y="2.5" width="3" height="11" rx="0.8" />
    </svg>
  );
}

function Spin() {
  return <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-r-transparent" aria-hidden />;
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [track, setTrack] = useState<Track | null>(null);
  const [playing, setPlaying] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  // RFC §6: time from the click on Play to the first sound ("playing" event)
  const clickedAt = useRef<number | null>(null);

  useEffect(() => {
    const el = audio.current;
    if (!el) return;
    prepare(el);
    const on = (name: string, handler: () => void) => {
      el.addEventListener(name, handler);
      return () => el.removeEventListener(name, handler);
    };
    const offs = [
      on("play", () => setPlaying(true)),
      on("pause", () => setPlaying(false)),
      on("ended", () => setPlaying(false)),
      on("waiting", () => setBuffering(true)),
      on("playing", () => {
        setBuffering(false);
        if (clickedAt.current !== null) {
          console.info(`[OhBeat] first sound in ${Math.round(performance.now() - clickedAt.current)} ms`);
          clickedAt.current = null;
        }
      }),
      on("timeupdate", () => setTime(el.currentTime)),
      on("durationchange", () => Number.isFinite(el.duration) && setDuration(el.duration)),
      on("error", () => {
        setBuffering(false);
        setPlaying(false);
      }),
    ];
    return () => offs.forEach((off) => off());
  }, []);

  const toggle = useCallback(
    (next: Track) => {
      const el = audio.current;
      if (!el) return;
      if (track?.id === next.id) {
        if (el.paused) void el.play().catch(() => undefined);
        else el.pause();
        return;
      }
      setTrack(next);
      setTime(0);
      setDuration(next.durationSec ?? 0);
      setBuffering(true);
      clickedAt.current = performance.now();
      void switchTo(el, next.previewUrl).catch(() => setBuffering(false)); // play() may be refused by the browser
    },
    [track],
  );

  const seek = useCallback((seconds: number) => {
    if (audio.current) seekTo(audio.current, seconds);
  }, []);

  const value = useMemo(
    () => ({ track, playing, buffering, time, duration, toggle, seek }),
    [track, playing, buffering, time, duration, toggle, seek],
  );

  return (
    <PlayerContext.Provider value={value}>
      {children}
      {/* The element exists from the start but has no src until the first Play */}
      <audio ref={audio} preload="none" className="hidden" />
      {track && <PlayerBar />}
    </PlayerContext.Provider>
  );
}

function PlayerBar() {
  const { t } = useTranslation();
  const { track, playing, buffering, time, duration, toggle, seek } = usePlayer();
  if (!track) return null;
  return (
    <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-panel/95 backdrop-blur" role="region" aria-label={t("player.label")}>
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2">
        <div className="h-10 w-10 shrink-0 overflow-hidden rounded bg-panel-2">
          {track.coverUrl && <img src={track.coverUrl} alt="" className="h-full w-full object-cover" />}
        </div>
        <button
          type="button"
          onClick={() => toggle(track)}
          aria-label={playing ? t("player.pause") : t("player.play")}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-[#3b8fd0] to-accent-deep text-white"
        >
          {buffering ? <Spin /> : playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <Link to={`/beats/${track.id}`} className="truncate text-sm text-ink hover:text-cyan">
              {track.title} <span className="text-muted">· {track.producer}</span>
            </Link>
            <span className="shrink-0 tabular-nums text-muted">
              {formatTime(time)} / {formatTime(duration)}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(time, duration || 0)}
            onChange={(e) => seek(Number(e.target.value))}
            aria-label={t("player.seek")}
            className="w-full accent-orange"
          />
        </div>
      </div>
    </div>
  );
}

/** Round Play button for cards and pages. */
export function PlayButton({ track, size = "md" }: { track: Track; size?: "md" | "lg" }) {
  const { t } = useTranslation();
  const { track: current, playing, buffering, toggle } = usePlayer();
  const active = current?.id === track.id;
  const dims = size === "lg" ? "h-14 w-14 [&_svg]:h-6 [&_svg]:w-6" : "h-10 w-10";
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        toggle(track);
      }}
      aria-label={active && playing ? t("player.pause") : t("player.play")}
      aria-pressed={active && playing}
      className={`flex ${dims} shrink-0 items-center justify-center rounded-full border border-accent/50 text-white shadow-panel transition ${
        active ? "bg-orange/90" : "bg-gradient-to-b from-[#3b8fd0] to-accent-deep hover:from-accent"
      }`}
    >
      {active && buffering ? <Spin /> : active && playing ? <PauseIcon /> : <PlayIcon />}
    </button>
  );
}
