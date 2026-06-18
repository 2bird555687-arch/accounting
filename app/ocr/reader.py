"""OCR Reader — แปลงไฟล์ต่างๆ เป็น base64 image สำหรับส่ง Claude Vision API."""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path


# media_type → allowed for direct base64 upload
_DIRECT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _to_bytes(source: str | bytes | Path) -> tuple[bytes, str | None]:
    """คืน (bytes, extension) จาก source."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_bytes(), path.suffix.lower()
    return source, None


def _encode(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()


def _read_image(data: bytes, ext: str) -> list[dict[str, str]]:
    media_type = _DIRECT_TYPES.get(ext, "image/jpeg")
    return [{"media_type": media_type, "data": _encode(data)}]


def _read_heic(data: bytes) -> list[dict[str, str]]:
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        raise ImportError("pillow-heif is required for HEIC support: pip install pillow-heif")

    from PIL import Image
    img = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=90)
    return [{"media_type": "image/jpeg", "data": _encode(buf.getvalue())}]


def _read_pdf(data: bytes) -> list[dict[str, str]]:
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError("pymupdf is required for PDF support: pip install pymupdf")

    doc = fitz.open(stream=data, filetype="pdf")
    pages: list[dict[str, str]] = []
    for page in doc:
        mat = fitz.Matrix(2, 2)  # 2x zoom → ~144 DPI
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg")
        pages.append({"media_type": "image/jpeg", "data": _encode(img_bytes)})
    return pages


def read_file(source: str | bytes | Path) -> list[dict[str, str]]:
    """แปลงไฟล์เป็น list ของ image pages.

    Returns:
        list of {"media_type": str, "data": base64_str}
        PDF → หนึ่ง entry ต่อหน้า, ไฟล์อื่น → list ที่มี 1 entry
    """
    data, ext = _to_bytes(source)

    if ext is None:
        # guess from bytes magic
        if data[:4] == b"%PDF":
            ext = ".pdf"
        elif data[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1"):
            ext = ".jpg"
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        else:
            ext = ".jpg"

    if ext == ".pdf":
        return _read_pdf(data)
    if ext in (".heic", ".heif"):
        return _read_heic(data)
    if ext in _DIRECT_TYPES:
        return _read_image(data, ext)

    # fallback: try Pillow for WebP and others
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        return [{"media_type": "image/jpeg", "data": _encode(buf.getvalue())}]
    except Exception:
        raise ValueError(f"Unsupported file format: {ext}")
