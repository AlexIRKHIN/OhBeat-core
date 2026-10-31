"""Image checks by content, not by extension (NFR-22; FR-9 uses the same rules for covers)."""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_SIDE = 2048

# Pillow format name -> (content type, file extension)
ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}
EXTENSIONS_BY_CONTENT_TYPE = {
    "image/jpeg": {"jpg", "jpeg"},
    "image/png": {"png"},
    "image/webp": {"webp"},
}


@dataclass(frozen=True)
class ImageInfo:
    content_type: str
    extension: str
    width: int
    height: int


class ImageRejected(Exception):
    def __init__(self, issue_key: str):
        super().__init__(issue_key)
        self.issue_key = issue_key


def inspect_image(data: bytes) -> ImageInfo:
    """Pillow reads the file signature (first bytes), so a renamed file is detected."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageRejected("file_too_large")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt, (width, height) = img.format, img.size
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ImageRejected("image_invalid") from None
    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected("image_invalid")
    if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
        raise ImageRejected("image_too_big")
    content_type, extension = ALLOWED_FORMATS[fmt]
    return ImageInfo(content_type=content_type, extension=extension, width=width, height=height)


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
