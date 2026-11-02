"""FR-9: checks by content, not by extension. Each failed check raises RejectError
with a code and a message the Producer sees in "My beats"."""

import json
import os
import subprocess
import zipfile

from PIL import Image, UnidentifiedImageError

from worker.antivirus import MockAntivirus
from worker.errors import RejectError

MAX_WAV_SECONDS = 10 * 60  # FR_NFR.md header: master WAV up to 10 minutes
MAX_UNPACKED_BYTES = 3 * 1024**3  # ASSUMPTION: GAP-18 — protection against ZIP bombs
MAX_COVER_SIDE = 2048
COVER_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def probe(path: str) -> dict:
    """What is really inside the file, according to ffprobe (it reads the data, not the name)."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_type,codec_name",
         "-of", "json", path],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        return {}
    return json.loads(result.stdout or "{}")


def pcm_duration(path: str) -> float | None:
    """Duration in seconds if the file is a WAV with PCM audio, otherwise None."""
    info = probe(path)
    fmt = info.get("format", {})
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if "wav" not in fmt.get("format_name", "") or len(audio) != 1:
        return None
    if not str(audio[0].get("codec_name", "")).startswith("pcm_"):
        return None
    try:
        return float(fmt["duration"])
    except (KeyError, ValueError):
        return None


def check_master_wav(path: str) -> float:
    duration = pcm_duration(path)
    if duration is None:
        raise RejectError("INVALID_WAV", "Мастер-файл не является WAV с PCM-звуком")
    if duration > MAX_WAV_SECONDS:
        minutes, seconds = divmod(round(duration), 60)
        raise RejectError("WAV_TOO_LONG", f"Длительность WAV {minutes}:{seconds:02d}, допустимо не больше 10 минут")
    return duration


def check_cover(path: str) -> str:
    """Returns the extension matching the real format of the image."""
    try:
        with Image.open(path) as img:
            fmt, (width, height) = img.format, img.size
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise RejectError("INVALID_COVER", "Обложка не является изображением JPG, PNG или WebP") from None
    if fmt not in COVER_FORMATS:
        raise RejectError("INVALID_COVER", "Обложка должна быть в формате JPG, PNG или WebP")
    if width != height:
        raise RejectError("INVALID_COVER", f"Обложка должна быть квадратной (1:1), а она {width}×{height}")
    if width > MAX_COVER_SIDE:
        raise RejectError("INVALID_COVER", f"Обложка {width}×{height} px, допустимо не больше 2048×2048")
    return COVER_FORMATS[fmt]


def _is_stem_name(name: str) -> bool:
    """A WAV name that is not macOS service junk: "__MACOSX/._drums.wav" also ends with .wav (GAP-18)."""
    base = os.path.basename(name)
    return name.lower().endswith(".wav") and "__MACOSX/" not in name and not base.startswith("._")


def check_stems(zip_path: str, unpack_dir: str, antivirus: MockAntivirus) -> None:
    """Archive integrity, only WAV inside, size limit, antivirus, every WAV is valid PCM."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        raise RejectError("ARCHIVE_CORRUPTED", "ZIP-архив повреждён и не открывается") from None

    with archive:
        files = [i for i in archive.infolist() if not i.is_dir()]
        non_audio = [i.filename for i in files if not _is_stem_name(i.filename)]
        if non_audio:
            shown = ", ".join(os.path.basename(n.rstrip("/")) or n for n in non_audio[:5])
            more = f" и ещё {len(non_audio) - 5}" if len(non_audio) > 5 else ""
            raise RejectError("ARCHIVE_CONTAINS_NON_AUDIO", f"В архиве найдены файлы, кроме WAV: {shown}{more}")
        if not files:
            raise RejectError("ARCHIVE_EMPTY", "В архиве нет WAV-файлов")
        if sum(i.file_size for i in files) > MAX_UNPACKED_BYTES:
            raise RejectError("ARCHIVE_TOO_LARGE", "Распакованный архив больше 3 ГБ")

        # testzip() reads every entry and checks its CRC: a damaged entry is found here
        try:
            broken = archive.testzip()
        except (zipfile.BadZipFile, OSError, EOFError):
            broken = "?"
        if broken is not None:
            raise RejectError("ARCHIVE_CORRUPTED", "ZIP-архив повреждён: не сходятся контрольные суммы")

        for index, info in enumerate(files):
            # Own file names inside the temp dir: protection from "../" paths in the archive (zip slip)
            target = os.path.join(unpack_dir, f"stem_{index}.wav")
            with archive.open(info) as src, open(target, "wb") as dst:
                while chunk := src.read(4 * 1024 * 1024):
                    dst.write(chunk)
            name = os.path.basename(info.filename)
            if antivirus.is_infected(target):
                raise RejectError("VIRUS_FOUND", f"Антивирус обнаружил угрозу в файле {name}")
            if pcm_duration(target) is None:
                raise RejectError("INVALID_STEM", f"Файл {name} в архиве не является WAV с PCM-звуком")
            os.remove(target)
