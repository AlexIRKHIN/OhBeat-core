"""FR-10: derived files made with FFmpeg.

* clean MP3 320 kbit/s — the file of the Basic license;
* preview MP3 128 kbit/s with the platform voice tag repeated every N seconds.
"""

import subprocess

from worker.checks import pcm_duration


class FfmpegError(Exception):
    """FFmpeg failed on a file that passed the checks — unexpected, so it is retried (RabbitMQ_Worker.md §5)."""


def _ffmpeg(*args: str) -> None:
    result = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise FfmpegError(result.stderr.strip()[-500:])


def make_clean_mp3(master: str, out: str) -> None:
    _ffmpeg("-i", master, "-vn", "-codec:a", "libmp3lame", "-b:a", "320k", out)


def make_preview(master: str, voice_tag: str, interval_sec: int, work_dir: str, out: str) -> None:
    """The tag is padded with silence to `interval_sec` and looped under the whole track."""
    tag_length = pcm_duration(voice_tag) or 1.0
    period = max(float(interval_sec), tag_length + 1.0)  # the tag must fit into its period
    padded_tag = f"{work_dir}/tag_period.wav"
    _ffmpeg("-i", voice_tag, "-af", f"apad=whole_dur={period}", "-ar", "44100", "-ac", "2", padded_tag)
    _ffmpeg(
        "-i", master,
        "-stream_loop", "-1", "-i", padded_tag,
        "-filter_complex",
        # duration=first: the result is as long as the track; normalize=0 keeps the track loudness
        "[0:a]aresample=44100,aformat=channel_layouts=stereo[track];"
        "[1:a]volume=1.4[tag];"
        "[track][tag]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]",
        "-map", "[out]", "-codec:a", "libmp3lame", "-b:a", "128k", out,
    )
