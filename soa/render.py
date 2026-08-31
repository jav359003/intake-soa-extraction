"""Render protocol pages to images for the vision extractor.

Resolution is the whole game here. SoA footnote markers are superscript letters
set at 5-6pt; at 150 DPI they are 6-7 pixels tall and the model cannot tell an
'a' from an 'c' -- and marker identity is the thing footnote linkage depends on.
300 DPI puts them at ~13px, which reads reliably. Above that the image blows
past the API size limit without helping.

Pages are rendered exactly as they display. pymupdf's page.rect already
accounts for the /Rotate entry, so a landscape SoA (protocol5, protocol9) comes
out upright on its own -- rotating it again lays the table on its side. The
`rotated` flag is kept as metadata for the extractor prompt, not acted on.
"""

from __future__ import annotations

import base64, io
from dataclasses import dataclass

import pymupdf

DPI = 300
MAX_PIXELS = 1_150_000     # Anthropic downsamples above ~1.15Mpx; pre-scale instead


@dataclass
class RenderedPage:
    page: int
    png: bytes
    width: int
    height: int
    rotated: bool
    scale: float           # image px per PDF point, for mapping bboxes back

    @property
    def b64(self) -> str:
        return base64.standard_b64encode(self.png).decode()

    def to_source(self) -> dict:
        """An Anthropic image content block."""
        return {"type": "base64", "media_type": "image/png", "data": self.b64}


def render(pdf_path: str, page_no: int, dpi: int = DPI) -> RenderedPage:
    doc = pymupdf.open(pdf_path)
    page = doc[page_no - 1]
    rect = page.rect
    rotated = rect.width > rect.height

    zoom = dpi / 72.0
    # Keep the long edge under the API's downsample threshold. Letting the API
    # scale for us throws away the superscripts we raised DPI to capture.
    est = (rect.width * zoom) * (rect.height * zoom)
    if est > MAX_PIXELS:
        zoom *= (MAX_PIXELS / est) ** 0.5

    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return RenderedPage(
        page=page_no, png=pix.tobytes("png"),
        width=pix.width, height=pix.height,
        rotated=rotated, scale=zoom,
    )


def render_span(pdf_path: str, pages: list[int], dpi: int = DPI) -> list[RenderedPage]:
    return [render(pdf_path, p, dpi) for p in pages]


if __name__ == "__main__":
    import sys, pathlib
    out = pathlib.Path("scratch/pages"); out.mkdir(parents=True, exist_ok=True)
    for spec in sys.argv[1:]:
        name, pg = spec.rsplit(":", 1)
        r = render(f"protocols/{name}", int(pg))
        f = out / f"{name.replace('.pdf','')}_p{pg}.png"
        f.write_bytes(r.png)
        print(f"{f}  {r.width}x{r.height}  rotated={r.rotated}  {len(r.png)/1024:.0f}KB")
