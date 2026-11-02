"""FR-9: checks by content. Every rejection code of slice-1-plan.md §8."""

import zipfile

import pytest

from worker import checks
from worker.antivirus import EICAR, MockAntivirus
from worker.checks import check_cover, check_master_wav, check_stems
from worker.errors import RejectError, TransientError
from worker.samples import make_stems_zip


def _code(fn, *args) -> str:
    with pytest.raises(RejectError) as exc:
        fn(*args)
    return exc.value.code


def test_fr9_good_wav_duration(samples):
    assert check_master_wav(samples["good_master.wav"]) == pytest.approx(40, abs=0.1)


def test_fr9_mp3_with_wav_extension_rejected(samples):
    assert _code(check_master_wav, samples["bad_mp3_renamed.wav"]) == "INVALID_WAV"


def test_fr9_wav_longer_than_10_minutes_rejected(samples):
    with pytest.raises(RejectError) as exc:
        check_master_wav(samples["bad_too_long.wav"])
    assert exc.value.code == "WAV_TOO_LONG"
    assert "11:00" in exc.value.message


def test_fr9_text_file_is_not_wav(tmp_path):
    fake = tmp_path / "fake.wav"
    fake.write_bytes(b"not audio at all")
    assert _code(check_master_wav, str(fake)) == "INVALID_WAV"


def test_fr9_good_cover(samples):
    assert check_cover(samples["good_cover.jpg"]) == "jpg"


@pytest.mark.parametrize("name", ["bad_cover_wide.jpg", "bad_cover_too_big.png"])
def test_fr9_bad_covers(samples, name):
    assert _code(check_cover, samples[name]) == "INVALID_COVER"


def test_fr9_cover_renamed_text_rejected(tmp_path):
    fake = tmp_path / "cover.jpg"
    fake.write_bytes(b"<html>not an image</html>")
    assert _code(check_cover, str(fake)) == "INVALID_COVER"


def test_fr9_good_stems(samples, tmp_path):
    check_stems(samples["good_stems.zip"], str(tmp_path), MockAntivirus())


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("bad_stems_with_exe.zip", "ARCHIVE_CONTAINS_NON_AUDIO"),
        ("bad_stems_virus.zip", "VIRUS_FOUND"),
        ("bad_stems_fake_wav.zip", "INVALID_STEM"),
        ("bad_stems_corrupted.zip", "ARCHIVE_CORRUPTED"),
    ],
)
def test_fr9_bad_stems(samples, tmp_path, name, code):
    assert _code(check_stems, samples[name], str(tmp_path), MockAntivirus()) == code


def test_fr9_non_audio_message_names_the_file(samples, tmp_path):
    with pytest.raises(RejectError) as exc:
        check_stems(samples["bad_stems_with_exe.zip"], str(tmp_path), MockAntivirus())
    assert exc.value.message == "В архиве найдены файлы, кроме WAV: readme.exe"


def test_fr9_real_eicar_test_string_detected(tmp_path):
    """The standard EICAR string, assembled in memory inside the Linux container."""
    archive = make_stems_zip(str(tmp_path / "eicar.zip"), str(tmp_path), {"stems/eicar.wav": EICAR})
    unpack = tmp_path / "unpack"
    unpack.mkdir()
    assert _code(check_stems, archive, str(unpack), MockAntivirus()) == "VIRUS_FOUND"


def test_fr9_gap18_macosx_junk_counts_as_non_audio(tmp_path):
    archive = make_stems_zip(str(tmp_path / "mac.zip"), str(tmp_path), {"__MACOSX/._drums.wav": b"junk"})
    assert _code(check_stems, archive, str(tmp_path), MockAntivirus()) == "ARCHIVE_CONTAINS_NON_AUDIO"


def test_fr9_empty_archive(tmp_path):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("stems/", "")
    assert _code(check_stems, str(path), str(tmp_path), MockAntivirus()) == "ARCHIVE_EMPTY"


def test_fr9_gap18_zip_bomb_limit(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "MAX_UNPACKED_BYTES", 1000)  # the real limit is 3 GB
    assert _code(check_stems, samples["good_stems.zip"], str(tmp_path), MockAntivirus()) == "ARCHIVE_TOO_LARGE"


def test_antivirus_unavailable_is_temporary(samples, tmp_path):
    with pytest.raises(TransientError):
        check_stems(samples["good_stems.zip"], str(tmp_path), MockAntivirus("unavailable"))
