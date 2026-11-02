"""Limits and reference values of a beat (FR_NFR.md header, NFR-3, REST API §2.1)."""

MB = 1024 * 1024

# ASSUMPTION: GAP-14 — the "system dictionary of keys": 12 major and 12 minor keys
MUSICAL_KEYS = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
    "Cm", "C#m", "Dm", "D#m", "Em", "Fm", "F#m", "Gm", "G#m", "Am", "A#m", "Bm",
]

LICENSE_CODES = ("basic", "premium", "trackout", "exclusive")
LICENSES_NEEDING_STEMS = {"trackout", "exclusive"}  # FR-1

PRICE_MIN, PRICE_MAX = 100, 500_000
TITLE_MIN, TITLE_MAX = 3, 60
BPM_MIN, BPM_MAX = 40, 300
DESCRIPTION_MAX = 1000
GENRES_MIN, GENRES_MAX = 1, 3


class FileRule:
    def __init__(self, kind: str, max_bytes: int, content_types: dict[str, str], extensions: dict[str, str]):
        self.kind = kind  # beat_files.kind
        self.max_bytes = max_bytes
        # Content type sent by the browser -> canonical one (ASSUMPTION: GAP-17)
        self.content_types = content_types
        # Allowed extension -> extension of the stored object
        self.extensions = extensions


WAV_TYPES = {"audio/wav": "audio/wav", "audio/x-wav": "audio/wav", "audio/wave": "audio/wav", "audio/vnd.wave": "audio/wav"}
ZIP_TYPES = {
    "application/zip": "application/zip",
    "application/x-zip-compressed": "application/zip",
    "application/x-zip": "application/zip",
}
IMAGE_TYPES = {"image/jpeg": "image/jpeg", "image/png": "image/png", "image/webp": "image/webp"}

# API field name in `files` -> rule
FILE_RULES = {
    "wav": FileRule("master", 200 * MB, WAV_TYPES, {"wav": "wav"}),
    "stems": FileRule("stems", 1024 * MB, ZIP_TYPES, {"zip": "zip"}),
    "cover": FileRule("cover", 5 * MB, IMAGE_TYPES, {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp"}),
}
FIELD_BY_KIND = {rule.kind: field for field, rule in FILE_RULES.items()}

# Extension must agree with the declared image type
IMAGE_EXTENSIONS = {"image/jpeg": {"jpg", "jpeg"}, "image/png": {"png"}, "image/webp": {"webp"}}
