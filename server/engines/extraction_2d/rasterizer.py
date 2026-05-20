"""PDF / image → base64 PNG pages for the VLM.

Two rasterization paths:
  * **poppler / pdftoppm** is preferred when available (faster, runs in a
    child process, doesn't pin pypdfium to a specific cadquery-ocp build).
  * **pypdfium2** is the cross-platform fallback that ships with the
    Python wheel — works on Windows where poppler is rarely installed.

Both paths feed the same long-side cap (default 2000 px) so the VLM
input size is bounded regardless of the source PDF DPI.
"""
from __future__ import annotations

import base64
import glob
import logging
import os
import subprocess
import tempfile
from io import BytesIO

from ...core.settings import get_settings

logger = logging.getLogger("cncserver.engines.extraction_2d.rasterizer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _natural_sort_key(filename: str) -> int:
    digits = "".join(c for c in filename if c.isdigit())
    return int(digits) if digits else 0


def _cap_long_side(png_bytes: bytes, max_long: int) -> bytes:
    """Resize so the longest side is <= ``max_long``. No-op if already small."""
    try:
        from PIL import Image
        img = Image.open(BytesIO(png_bytes))
        w, h = img.size
        longest = max(w, h)
        if longest <= max_long:
            return png_bytes
        scale = max_long / longest
        new_w = round(w * scale)
        new_h = round(h * scale)
        logger.info("resize %dx%d → %dx%d (cap %d)", w, h, new_w, new_h, max_long)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("_cap_long_side failed (%s) — using original", exc)
        return png_bytes


# ---------------------------------------------------------------------------
# Poppler / pdftoppm path
# ---------------------------------------------------------------------------

def _poppler_render(pdf_bytes: bytes, *, max_pages: int, max_long: int, dpi: int) -> list[str]:
    """Use ``pdftoppm`` to render the PDF — only path that works in some Docker images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "input.pdf")
        out_prefix = os.path.join(tmpdir, "page")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        cmd = ["pdftoppm", "-png", "-r", str(dpi), "-f", "1"]
        if max_pages > 0:
            cmd += ["-l", str(max_pages)]
        cmd += [pdf_path, out_prefix]
        subprocess.run(cmd, check=True, timeout=600, capture_output=True)
        png_files = sorted(
            glob.glob(os.path.join(tmpdir, "page*.png")),
            key=lambda p: _natural_sort_key(os.path.basename(p)),
        )
        if not png_files:
            raise RuntimeError("pdftoppm produced no PNG output")
        pages: list[str] = []
        for png_path in png_files:
            with open(png_path, "rb") as f:
                raw = f.read()
            resized = _cap_long_side(raw, max_long)
            pages.append(base64.b64encode(resized).decode())
        return pages


# ---------------------------------------------------------------------------
# pypdfium2 path
# ---------------------------------------------------------------------------

def _pypdfium_render(pdf_bytes: bytes, *, max_pages: int, max_long: int, dpi: int) -> list[str]:
    """Render PDF with pypdfium2. Always available on the Python side."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_bytes)
    pages: list[str] = []
    page_limit = len(doc) if max_pages <= 0 else min(len(doc), max_pages)
    for i in range(page_limit):
        page = doc[i]
        w_pt, h_pt = page.get_size()
        longest_pt = max(w_pt, h_pt)
        scale_dpi = dpi / 72.0
        scale_cap = max_long / (longest_pt * scale_dpi)
        scale = min(scale_dpi, scale_dpi * scale_cap)
        bitmap = page.render(scale=scale)
        pil_img = bitmap.to_pil()
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        resized = _cap_long_side(buf.getvalue(), max_long)
        pages.append(base64.b64encode(resized).decode())
    return pages


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pdf_to_base64_pages(pdf_bytes: bytes, *, max_pages: int = 0) -> list[str]:
    """Render a PDF to one base64 PNG per page. Tries poppler, then pypdfium2."""
    s = get_settings().extraction
    try:
        return _poppler_render(
            pdf_bytes,
            max_pages=max_pages,
            max_long=s.pdf_long_side_px,
            dpi=s.pdf_target_dpi,
        )
    except Exception as exc:
        logger.warning("pdftoppm unavailable (%s) — falling back to pypdfium2", exc)
    return _pypdfium_render(
        pdf_bytes,
        max_pages=max_pages,
        max_long=s.pdf_long_side_px,
        dpi=s.pdf_target_dpi,
    )


def file_to_base64_pages(
    file_bytes: bytes,
    *,
    filename: str = "",
    max_pages: int = 0,
) -> list[str]:
    """Render a drawing file (PDF or raster image) to base64 PNG pages.

    Detection is by magic bytes — ``%PDF`` is treated as PDF, anything
    else is assumed to be a single-page image and passed through as-is.
    ``max_pages <= 0`` means "process every page" (PDF only).
    """
    if file_bytes[:4] == b"%PDF":
        return pdf_to_base64_pages(file_bytes, max_pages=max_pages)
    return [base64.b64encode(file_bytes).decode()]
