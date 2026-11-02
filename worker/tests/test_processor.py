"""Processing of a command against real MinIO and FFmpeg: FR-9 … FR-11, RabbitMQ_Worker.md §3–§4."""

import json
import subprocess
import uuid

import pytest

from worker.processor import process


def _upload_sources(storage, settings, beat_id, samples, wav="good_master.wav", cover="good_cover.jpg",
                    stems: str | None = "good_stems.zip") -> dict:
    keys = {"wav_key": f"raw/{beat_id}/master.wav", "cover_key": f"raw/{beat_id}/cover.jpg",
            "stems_key": f"raw/{beat_id}/stems.zip" if stems else None}
    storage.client.upload_file(samples[wav], settings.bucket_temp, keys["wav_key"])
    storage.client.upload_file(samples[cover], settings.bucket_temp, keys["cover_key"])
    if stems:
        storage.client.upload_file(samples[stems], settings.bucket_temp, keys["stems_key"])
    return keys


def _command(beat_id: int, files: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()), "event_type": "beat.media.process", "occurred_at": "2026-11-02T10:00:00Z",
        "beat_id": beat_id, "producer_id": 1, "files": files,
        "options": {"voice_tag": True, "tag_interval_sec": 20},
    }


def _probe_remote(storage, bucket: str, key: str, tmp_path) -> dict:
    local = tmp_path / key.replace("/", "_")
    storage.client.download_file(bucket, key, str(local))
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,bit_rate:stream=codec_name",
                          "-of", "json", str(local)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_fr10_fr11_processed_outputs(storage, settings, beat_id, samples, tmp_path):
    command = _command(beat_id, _upload_sources(storage, settings, beat_id, samples))
    result = process(command, settings, storage)

    assert result["result"] == "processed"
    assert result["source_event_id"] == command["event_id"]
    assert result["duration_sec"] == 40
    assert result["outputs"] == {
        "master": f"beats/{beat_id}/master.wav",
        "stems": f"beats/{beat_id}/stems.zip",
        "clean_mp3": f"beats/{beat_id}/clean.mp3",
        "preview_mp3": f"previews/{beat_id}_v1.mp3",
        "cover": f"covers/{beat_id}_v1.jpg",
    }

    # FR-11: private vs public bucket; GAP-50: sha256 in the object metadata
    s3 = storage.client
    for kind in ("master", "stems", "clean_mp3"):
        head = s3.head_object(Bucket=settings.bucket_private, Key=result["outputs"][kind])
        assert len(head["Metadata"]["sha256"]) == 64
    preview = s3.head_object(Bucket=settings.bucket_public, Key=result["outputs"]["preview_mp3"])
    assert preview["ContentType"] == "audio/mpeg"
    assert preview["CacheControl"] == "public, max-age=31536000, immutable"  # RFC_Audio_Streaming §2

    # FR-10: clean MP3 320 kbit/s, preview MP3 128 kbit/s, both as long as the master
    clean = _probe_remote(storage, settings.bucket_private, result["outputs"]["clean_mp3"], tmp_path)
    prev = _probe_remote(storage, settings.bucket_public, result["outputs"]["preview_mp3"], tmp_path)
    assert clean["streams"][0]["codec_name"] == prev["streams"][0]["codec_name"] == "mp3"
    assert int(clean["format"]["bit_rate"]) == pytest.approx(320_000, rel=0.05)
    assert int(prev["format"]["bit_rate"]) == pytest.approx(128_000, rel=0.05)
    assert float(prev["format"]["duration"]) == pytest.approx(40, abs=0.5)


def test_fr10_voice_tag_changes_the_preview(storage, settings, beat_id, samples, tmp_path):
    """With the tag the preview differs from the clean track (the tag is mixed in)."""
    files = _upload_sources(storage, settings, beat_id, samples, stems=None)
    with_tag = process(_command(beat_id, files), settings, storage)
    tagged = tmp_path / "tagged.mp3"
    storage.client.download_file(settings.bucket_public, with_tag["outputs"]["preview_mp3"], str(tagged))

    command = _command(beat_id, files)
    command["options"]["voice_tag"] = False
    process(command, settings, storage)
    plain = tmp_path / "plain.mp3"
    storage.client.download_file(settings.bucket_public, with_tag["outputs"]["preview_mp3"], str(plain))
    assert tagged.read_bytes() != plain.read_bytes()


def test_repeated_command_writes_the_same_keys(storage, settings, beat_id, samples):
    """MANDATORY (worker side): a command delivered twice overwrites the same objects."""
    command = _command(beat_id, _upload_sources(storage, settings, beat_id, samples))
    first = process(command, settings, storage)
    second = process(command, settings, storage)
    assert first["outputs"] == second["outputs"]
    listed = storage.client.list_objects_v2(Bucket=settings.bucket_private, Prefix=f"beats/{beat_id}/")["Contents"]
    assert len(listed) == 3  # master, stems, clean — no duplicates


def test_beat_without_stems(storage, settings, beat_id, samples):
    result = process(_command(beat_id, _upload_sources(storage, settings, beat_id, samples, stems=None)), settings, storage)
    assert result["result"] == "processed"
    assert result["outputs"]["stems"] is None


@pytest.mark.parametrize(
    ("sources", "code"),
    [
        ({"wav": "bad_mp3_renamed.wav"}, "INVALID_WAV"),
        ({"wav": "bad_too_long.wav"}, "WAV_TOO_LONG"),
        ({"cover": "bad_cover_wide.jpg"}, "INVALID_COVER"),
        ({"stems": "bad_stems_with_exe.zip"}, "ARCHIVE_CONTAINS_NON_AUDIO"),
        ({"stems": "bad_stems_virus.zip"}, "VIRUS_FOUND"),
    ],
)
def test_fr9_rejected_result_format(storage, settings, beat_id, samples, sources, code):
    result = process(_command(beat_id, _upload_sources(storage, settings, beat_id, samples, **sources)), settings, storage)
    # RabbitMQ_Worker.md §4: rejected -> duration and outputs are null, error has code and message
    assert result["result"] == "rejected"
    assert result["duration_sec"] is None and result["outputs"] is None
    assert result["error"]["code"] == code
    assert result["error"]["message"]


def test_gap22_missing_sources_rejected(storage, settings, beat_id):
    files = {"wav_key": f"raw/{beat_id}/master.wav", "cover_key": f"raw/{beat_id}/cover.jpg", "stems_key": None}
    result = process(_command(beat_id, files), settings, storage)
    assert result["error"]["code"] == "SOURCE_FILES_EXPIRED"
