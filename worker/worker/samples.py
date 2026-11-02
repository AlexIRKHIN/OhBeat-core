"""Sample files for manual checks and tests: good ones and every kind of bad one.

    docker compose run --rm media-worker python -m worker.samples     ->  ./samples/

Audio is synthesized by FFmpeg (tones and a pulse), images are drawn by Pillow.
The "virus" sample uses our own test marker, not EICAR, so the antivirus of your
computer does not quarantine it (see worker/antivirus.py).
"""

import os
import shutil
import subprocess
import sys
import zipfile

from PIL import Image, ImageDraw

from worker.antivirus import OHBEAT_TEST_SIGNATURE


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def make_wav(path: str, seconds: float, frequency: int = 220, rate: int = 44100, channels: int = 2, codec: str = "pcm_s16le") -> str:
    """A small "beat": a tone plus a pulse every half second, so the voice tag is easy to hear over it."""
    expr = f"0.25*sin(2*PI*{frequency}*t)+0.35*sin(2*PI*55*t)*exp(-12*mod(t\\,0.5))"
    _ffmpeg("-f", "lavfi", "-i", f"aevalsrc={expr}:s={rate}:d={seconds}", "-ac", str(channels), "-c:a", codec, path)
    return path


def make_mp3_named_wav(path: str, seconds: float = 10) -> str:
    """An MP3 with a .wav name: the check must look at the content."""
    tmp = path + ".tmp.mp3"
    make_wav(path + ".tmp.wav", seconds)
    _ffmpeg("-i", path + ".tmp.wav", "-c:a", "libmp3lame", "-b:a", "128k", tmp)
    os.replace(tmp, path)
    os.remove(path + ".tmp.wav")
    return path


def make_image(path: str, width: int, height: int, fmt: str = "JPEG") -> str:
    img = Image.new("RGB", (width, height), (34, 35, 38))
    draw = ImageDraw.Draw(img)
    draw.ellipse((width * 0.2, height * 0.2, width * 0.8, height * 0.8), fill=(62, 170, 234))
    img.save(path, format=fmt)
    return path


def make_stems_zip(path: str, work: str, extra: dict[str, bytes] | None = None) -> str:
    """Three short WAV stems in a folder, plus optional extra entries."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, freq in (("drums", 60), ("bass", 110), ("melody", 440)):
            stem = make_wav(os.path.join(work, f"{name}.wav"), 5, frequency=freq)
            zf.write(stem, f"stems/{name}.wav")
            os.remove(stem)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path


def make_corrupted_zip(path: str, work: str) -> str:
    make_stems_zip(path, work)
    with open(path, "r+b") as f:
        f.seek(200)
        f.write(b"\x00" * 64)  # damages compressed data: the CRC check fails
    return path


def generate(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, ".work")
    os.makedirs(work, exist_ok=True)
    p = lambda name: os.path.join(out_dir, name)  # noqa: E731
    made = [
        make_wav(p("good_master.wav"), 40),
        # 11 minutes, 8 kHz mono 8 bit: still a valid PCM WAV, but only ~5 MB
        make_wav(p("bad_too_long.wav"), 11 * 60, rate=8000, channels=1, codec="pcm_u8"),
        make_mp3_named_wav(p("bad_mp3_renamed.wav")),
        make_image(p("good_cover.jpg"), 1000, 1000),
        make_image(p("bad_cover_wide.jpg"), 1200, 800),
        make_image(p("bad_cover_too_big.png"), 3000, 3000, "PNG"),
        make_stems_zip(p("good_stems.zip"), work),
        make_stems_zip(p("bad_stems_with_exe.zip"), work, {"stems/readme.exe": b"MZ\x90\x00 not really a program"}),
        make_stems_zip(p("bad_stems_virus.zip"), work, {"stems/infected.wav": b"RIFF" + OHBEAT_TEST_SIGNATURE}),
        make_stems_zip(p("bad_stems_fake_wav.zip"), work, {"stems/notes.wav": b"just text, not audio"}),
        make_corrupted_zip(p("bad_stems_corrupted.zip"), work),
    ]
    shutil.rmtree(work, ignore_errors=True)
    return made


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/samples"
    for path in generate(target):
        print(f"{os.path.getsize(path):>10} bytes  {os.path.basename(path)}")
