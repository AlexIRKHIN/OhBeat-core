"""Demo catalog: 12 beats of the seeded Producer and 4 of the second one (SEED_PRODUCER2_*, to show
the split of a payment between two sellers), with different genres, BPM, keys and prices, published
through the real path (POST /beats -> direct upload to MinIO -> confirm -> Media Worker).

    docker compose exec api python -m seeds.demo_beats

Audio is synthesized here (a chord plus a kick on every beat of the given tempo), covers are drawn
with Pillow. Running it again skips beats that already exist (matched by title).
"""

import io
import math
import os
import struct
import sys
import time
import wave
import zipfile

import httpx
from PIL import Image, ImageDraw

API = "http://localhost:8000/v1"
RATE = 44100
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

# title, genres, bpm, key, licenses (code -> price), stems, cover colour
BEATS = [
    ("Midnight Neon", ["Synthwave"], 100, "Am", {"basic": 1500, "premium": 3000, "trackout": 6000, "exclusive": 30000}, True, (62, 170, 234)),
    ("Trap Lord", ["Trap"], 140, "Cm", {"basic": 2000, "premium": 4000, "exclusive": 40000}, True, (240, 106, 114)),
    ("Lo-Fi Morning", ["Lo-Fi", "Hip-Hop"], 80, "F", {"basic": 900, "premium": 1800}, False, (242, 164, 58)),
    ("Drill Season", ["Drill"], 142, "F#m", {"basic": 2500, "trackout": 7000}, True, (120, 210, 242)),
    ("Boom Bap Days", ["Boom Bap"], 90, "Dm", {"basic": 1200, "premium": 2500, "trackout": 5000}, True, (169, 195, 207)),
    ("Afro Sunset", ["Afrobeats"], 105, "G", {"basic": 1800, "premium": 3500}, False, (79, 191, 225)),
    ("Velvet R&B", ["R&B"], 70, "D#m", {"basic": 2200, "exclusive": 35000}, True, (42, 114, 170)),
    ("House Party", ["House"], 124, "A", {"basic": 1600, "premium": 3200}, False, (62, 170, 234)),
    ("Reggaeton Calor", ["Reggaeton"], 96, "Bm", {"basic": 1400, "premium": 2800, "trackout": 5500}, True, (242, 164, 58)),
    ("Rock Anthem", ["Rock"], 128, "E", {"basic": 3000}, False, (240, 106, 114)),
    ("Pop Sugar", ["Pop"], 118, "C", {"basic": 1000, "premium": 2000, "trackout": 4500, "exclusive": 25000}, True, (120, 210, 242)),
    ("Dark Trap", ["Trap", "Drill"], 150, "Gm", {"basic": 2800, "premium": 5000}, False, (79, 191, 225)),
]

# The second Producer (Nova Sound); prices like 999 give a fee with kopecks (99.90, GAP-42)
BEATS_2 = [
    ("Nova Pulse", ["Synthwave", "House"], 122, "Em", {"basic": 1750, "premium": 3255, "exclusive": 28000}, True, (242, 164, 58)),
    ("Cold Drill", ["Drill"], 144, "A#m", {"basic": 2100, "trackout": 6400}, True, (120, 210, 242)),
    ("Sunday Lo-Fi", ["Lo-Fi"], 76, "D", {"basic": 999, "premium": 1995}, False, (169, 195, 207)),
    ("Gold Chains", ["Trap"], 136, "Fm", {"basic": 2400, "premium": 4600, "exclusive": 45000}, True, (240, 106, 114)),
]


def _key_frequency(key: str) -> float:
    """Root note of the key in the octave from C3 to B3 (A3 = 220 Hz)."""
    root = key.removesuffix("m")
    return 220.0 * 2 ** ((NOTE[root] - NOTE["A"]) / 12)


def synth_wav(bpm: int, key: str, seconds: float, stereo: bool = True, only: str | None = None) -> bytes:
    """16-bit PCM: a triad of the key and a kick drum on every beat."""
    root = _key_frequency(key)
    minor = key.endswith("m")
    chord = [root, root * 2 ** ((3 if minor else 4) / 12), root * 2 ** (7 / 12)]
    beat = 60.0 / bpm
    frames = bytearray()
    for i in range(int(RATE * seconds)):
        t = i / RATE
        phase = t % beat
        kick = math.sin(2 * math.pi * 55 * phase * (1 + 2 * math.exp(-30 * phase))) * math.exp(-8 * phase)
        pad = sum(math.sin(2 * math.pi * f * t) for f in chord) / 3
        sample = (0.45 * kick if only != "chords" else 0) + (0.3 * pad if only != "drums" else 0)
        value = struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 30000))
        frames += value * (2 if stereo else 1)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(2 if stereo else 1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return buffer.getvalue()


def stems_zip(bpm: int, key: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("stems/drums.wav", synth_wav(bpm, key, 8, stereo=False, only="drums"))
        zf.writestr("stems/chords.wav", synth_wav(bpm, key, 8, stereo=False, only="chords"))
    return buffer.getvalue()


def cover(title: str, colour: tuple[int, int, int]) -> bytes:
    size = 800
    img = Image.new("RGB", (size, size), (27, 28, 30))
    draw = ImageDraw.Draw(img)
    for r in range(360, 0, -40):  # concentric rings, a nod to the Neptunian theme
        shade = tuple(int(c * (1 - r / 500)) for c in colour)
        draw.ellipse((size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r), fill=shade)
    draw.text((40, 40), title, fill=(217, 238, 247))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def upload(form: dict, name: str, data: bytes) -> None:
    # The form is signed for the browser address (localhost:9000); inside docker MinIO is minio:9000.
    # A POST policy does not depend on the host, so the same form works on the internal address.
    url = form["url"].replace(os.environ.get("S3_PUBLIC_ENDPOINT", "http://localhost:9000"),
                              os.environ.get("S3_INTERNAL_ENDPOINT", "http://minio:9000"))
    response = httpx.post(url, data=form["fields"], files={"file": (name, data)}, timeout=120)
    response.raise_for_status()


def main() -> None:
    publish("SEED_PRODUCER", BEATS)
    if os.environ.get("SEED_PRODUCER2_EMAIL"):
        publish("SEED_PRODUCER2", BEATS_2)


def publish(prefix: str, beats: list) -> None:
    """Publishes `beats` as the Producer whose login is <prefix>_EMAIL / <prefix>_PASSWORD in .env."""
    with httpx.Client(base_url=API, timeout=60) as api:
        token = api.post("/auth/login", json={
            "email": os.environ[f"{prefix}_EMAIL"], "password": os.environ[f"{prefix}_PASSWORD"],
        }).raise_for_status().json()["access_token"]
        api.headers["Authorization"] = f"Bearer {token}"

        existing, cursor = set(), None
        while True:
            page = api.get("/users/me/beats", params={"limit": 100, **({"cursor": cursor} if cursor else {})}).json()
            existing |= {b["title"] for b in page["items"]}
            if not (cursor := page["next_cursor"]):
                break

        created = []
        for title, genres, bpm, key, prices, with_stems, colour in beats:
            if title in existing:
                print(f"skip   {title} (already exists)")
                continue
            files = {"wav": ("master.wav", synth_wav(bpm, key, 24), "audio/wav"),
                     "cover": ("cover.jpg", cover(title, colour), "image/jpeg")}
            if with_stems:
                files["stems"] = ("stems.zip", stems_zip(bpm, key), "application/zip")
            body = {
                "title": title, "genres": genres, "bpm": bpm, "musical_key": key,
                "description": f"Демо-бит OhBeat: {', '.join(genres)}, {bpm} BPM, {key}.",
                "licenses": [{"code": c, "price": p} for c, p in prices.items()],
                "files": {k: {"name": n, "size_bytes": len(d), "content_type": ct} for k, (n, d, ct) in files.items()},
            }
            beat = api.post("/beats", json=body).raise_for_status().json()
            for field, (name, data, _) in files.items():
                upload(beat["uploads"][field], name, data)
            api.post(f"/beats/{beat['id']}/confirm").raise_for_status()
            created.append(beat["id"])
            print(f"sent   {title}: beat {beat['id']}")

        # Wait for Media Worker
        deadline = time.monotonic() + 180
        while created and time.monotonic() < deadline:
            items = api.get("/users/me/beats", params={"limit": 100}).json()["items"]
            states = {b["id"]: b for b in items if b["id"] in created}
            if all(b["status"] != "processing" for b in states.values()):
                for b in states.values():
                    print(f"{b['status']:<10} {b['title']}" + (f" — {b['rejection_reason']}" if b["rejection_reason"] else ""))
                return
            time.sleep(2)
        if created:
            print("Some beats are still processing; check 'My beats' later", file=sys.stderr)


if __name__ == "__main__":
    main()
