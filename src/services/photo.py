"""Image processing for progress photos. Pure computation — no DB access."""

import io
import logging

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Security: limit decompression bomb risk
Image.MAX_IMAGE_PIXELS = 5_000_000  # ~2236x2236 max

MAX_DIMENSION = 1080
JPEG_QUALITY = 85
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_FORMATS = {"JPEG", "PNG"}
MAX_PIXEL_DIM = 4096


def process_photo(raw_bytes: bytes) -> dict:
    """Process an uploaded image: fix orientation, resize, strip EXIF.

    Returns {"photo": bytes, "width": int, "height": int, "file_size": int}.
    Raises ValueError on invalid/unsupported image.
    """
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Image exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")

    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        raise ValueError("Cannot decode image. Supported formats: JPEG, PNG.")

    if img.format not in ALLOWED_FORMATS:
        raise ValueError(f"Unsupported image format: {img.format}. Use JPEG or PNG.")

    w, h = img.size
    if w > MAX_PIXEL_DIM or h > MAX_PIXEL_DIM:
        raise ValueError(f"Image dimensions too large ({w}x{h}). Max {MAX_PIXEL_DIM}px.")

    # Fix EXIF orientation (phone photos are often rotated in metadata)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass  # If EXIF is missing or corrupt, continue as-is

    # Convert to RGB (handles RGBA PNGs, palette images)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Resize to max dimension
    w, h = img.size
    if w > MAX_DIMENSION or h > MAX_DIMENSION:
        if w > h:
            new_w = MAX_DIMENSION
            new_h = int(h * (MAX_DIMENSION / w))
        else:
            new_h = MAX_DIMENSION
            new_w = int(w * (MAX_DIMENSION / h))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Encode as JPEG, stripping ALL EXIF data
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, exif=b"")
    photo_bytes = buf.getvalue()
    final_w, final_h = img.size
    buf.close()
    img.close()

    return {
        "photo": photo_bytes,
        "width": final_w,
        "height": final_h,
        "file_size": len(photo_bytes),
    }
