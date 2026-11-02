"""Processing of one `beat.media.process` command (FR-9 … FR-11, RabbitMQ_Worker.md §3–§4).

    download sources from temp-uploads
      -> check WAV, cover, ZIP (+ antivirus)        any failure -> result "rejected"
      -> clean MP3 320 + preview 128 with voice tag
      -> put files under deterministic keys          a repeated command overwrites the same objects
      -> result "processed" with the permanent keys

The function returns the result message; publishing it is the job of worker/main.py.
"""

import logging
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime

from worker.antivirus import MockAntivirus
from worker.checks import check_cover, check_master_wav, check_stems
from worker.config import Settings
from worker.errors import RejectError
from worker.media import make_clean_mp3, make_preview
from worker.storage import IMMUTABLE, Storage, sha256_of

log = logging.getLogger("worker")

COVER_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def output_keys(beat_id: int, cover_ext: str) -> dict[str, str]:
    """Deterministic keys (RabbitMQ_Worker.md §4, RFC_Audio_Streaming.md §2): a repeated command
    overwrites the same objects. The version suffix is always `_v1`: files of a published beat are not replaced."""
    return {
        "master": f"beats/{beat_id}/master.wav",
        "stems": f"beats/{beat_id}/stems.zip",
        "clean_mp3": f"beats/{beat_id}/clean.mp3",
        "preview_mp3": f"previews/{beat_id}_v1.mp3",
        "cover": f"covers/{beat_id}_v1.{cover_ext}",
    }


def _result(command: dict, result: str, **fields) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "beat.media.processed",
        "occurred_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_event_id": command["event_id"],
        "beat_id": command["beat_id"],
        "result": result,
        "duration_sec": fields.get("duration_sec"),
        "outputs": fields.get("outputs"),
        "error": fields.get("error"),
    }


def process(command: dict, settings: Settings, storage: Storage) -> dict:
    """Raises TransientError (or any unexpected exception) when the command must be retried."""
    beat_id = command["beat_id"]
    files = command["files"]
    options = command.get("options") or {}
    os.makedirs(settings.work_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix=f"beat-{beat_id}-", dir=settings.work_dir)
    try:
        master, cover = os.path.join(work, "master.wav"), os.path.join(work, "cover")
        stems = os.path.join(work, "stems.zip") if files.get("stems_key") else None
        try:
            storage.download_source(files["wav_key"], master)
            storage.download_source(files["cover_key"], cover)
            if stems:
                storage.download_source(files["stems_key"], stems)

            # FR-9: by content, not by extension
            duration = check_master_wav(master)
            cover_ext = check_cover(cover)
            if stems:
                unpack = os.path.join(work, "unpacked")
                os.makedirs(unpack)
                check_stems(stems, unpack, MockAntivirus(settings.antivirus_mode))
        except RejectError as exc:
            log.info("beat %s rejected: %s", beat_id, exc)
            return _result(command, "rejected", error={"code": exc.code, "message": exc.message})

        # FR-10: derived files
        clean = os.path.join(work, "clean.mp3")
        preview = os.path.join(work, "preview.mp3")
        make_clean_mp3(master, clean)
        if options.get("voice_tag", True):
            make_preview(master, settings.voice_tag_path, int(options.get("tag_interval_sec", 20)), work, preview)
        else:
            shutil.copy(clean, preview)

        # FR-11: originals and the clean MP3 -> private bucket; preview and cover -> public bucket
        keys = output_keys(beat_id, cover_ext)
        uploads = [
            ("master", settings.bucket_private, master, "audio/wav", None),
            ("clean_mp3", settings.bucket_private, clean, "audio/mpeg", None),
            ("preview_mp3", settings.bucket_public, preview, "audio/mpeg", IMMUTABLE),
            ("cover", settings.bucket_public, cover, COVER_TYPES[cover_ext], IMMUTABLE),
        ]
        if stems:
            uploads.append(("stems", settings.bucket_private, stems, "application/zip", None))
        for kind, bucket, path, content_type, cache in uploads:
            storage.put_file(bucket, keys[kind], path, content_type, sha256_of(path), cache)

        outputs = {kind: keys[kind] for kind, *_ in uploads}
        outputs.setdefault("stems", None)
        log.info("beat %s processed: %.1f s", beat_id, duration)
        return _result(command, "processed", duration_sec=round(duration), outputs=outputs)
    finally:
        # Sources in temp-uploads are NOT deleted here: the lifecycle rule does it (GAP-22)
        shutil.rmtree(work, ignore_errors=True)
