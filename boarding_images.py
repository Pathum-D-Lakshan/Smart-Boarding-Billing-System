"""Validate and normalize cover images without trusting uploaded names or metadata."""

from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import uuid
import warnings

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_COVER_BYTES = 5 * 1024 * 1024
MAX_COVER_PIXELS = 20_000_000
MAX_COVER_DIMENSION = 6000
STORED_COVER_SIZE = (1920, 1920)
COVER_FILENAME = re.compile(r"[a-f0-9]{32}\.webp")


class InvalidCoverImage(ValueError):
    pass


def cover_image_path(filename):
    if not isinstance(filename, str) or not COVER_FILENAME.fullmatch(filename):
        return None
    root = Path(current_app.config.get(
        "BOARDING_UPLOAD_ROOT", Path(current_app.root_path) / "uploads" / "boardings",
    )).resolve()
    return root / filename


def remove_cover_image(filename):
    path = cover_image_path(filename)
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning("Could not clean up a boarding cover file.")


def save_cover_image(upload):
    if upload is None or not upload.filename:
        return None
    data = upload.stream.read(MAX_COVER_BYTES + 1)
    if len(data) > MAX_COVER_BYTES:
        raise InvalidCoverImage("Choose a photo no larger than 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
                width, height = image.size
                if width > MAX_COVER_DIMENSION or height > MAX_COVER_DIMENSION or width * height > MAX_COVER_PIXELS:
                    raise InvalidCoverImage("Choose a photo up to 6,000 pixels per side and 20 megapixels.")
                if getattr(image, "is_animated", False):
                    raise InvalidCoverImage("Choose a still photo rather than an animated image.")
                image.verify()
            with Image.open(BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                rgba = oriented.convert("RGBA")
                normalized = Image.new("RGB", rgba.size, "white")
                normalized.paste(rgba, mask=rgba.getchannel("A"))
                normalized.thumbnail(STORED_COVER_SIZE, Image.Resampling.LANCZOS)
                rgba.close()
                oriented.close()
    except InvalidCoverImage:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidCoverImage("Choose a valid, complete JPEG, PNG or WebP photo.") from None

    filename = uuid.uuid4().hex + ".webp"
    destination = cover_image_path(filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        # Publish a complete new file before committing its name; never overwrite the old cover.
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        normalized.save(temporary_path, format="WEBP", quality=85, exif=b"", icc_profile=None)
        os.replace(temporary_path, destination)
    finally:
        normalized.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return filename
