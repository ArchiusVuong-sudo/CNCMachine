#!/usr/bin/env python
"""PDF text + region rendering for vision.
  text:   python pdf_tool.py text "<file>" [maxchars]
  render: python pdf_tool.py render "<file>" <outdir> <dpi> <tag> [pageStart pageEnd]
  crop:   python pdf_tool.py crop "<file>" <page0idx> x0 y0 x1 y1 <dpi> <outdir> <tag>
Engineering drawings/setup sheets are faint at full page -> crop quadrants at 300 dpi.
NOTE: pass outdir as a shell arg (MSYS path translation); never hardcode /tmp in python."""
import fitz, sys
from pathlib import Path

def text(p, mx=8000):
    d = fitz.open(p); out = []
    for i, pg in enumerate(d):
        out.append(f"--- page {i+1}/{len(d)} {pg.rect.width:.0f}x{pg.rect.height:.0f} "
                    f"imgs={len(pg.get_images())} ---\n{pg.get_text().strip()}")
    d.close()
    print("\n".join(out)[:mx])

def render(p, outdir, dpi, tag, ps=None, pe=None):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    d = fitz.open(p)
    for i, pg in enumerate(d):
        if ps is not None and not (ps <= i + 1 <= pe):
            continue
        fp = outdir / f"{tag}_p{i+1}.png"
        pg.get_pixmap(dpi=dpi).save(fp)
        print(fp)
    d.close()

def crop(p, page, x0, y0, x1, y1, dpi, outdir, tag):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    d = fitz.open(p); pg = d[page]; r = pg.rect
    clip = fitz.Rect(r.x0 + r.width * x0, r.y0 + r.height * y0,
                      r.x0 + r.width * x1, r.y0 + r.height * y1)
    fp = outdir / f"{tag}.png"
    pg.get_pixmap(dpi=dpi, clip=clip).save(fp)
    print(fp)
    d.close()

if __name__ == "__main__":
    c = sys.argv[1]
    if c == "text":
        text(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 8000)
    elif c == "render":
        a = sys.argv
        render(a[2], a[3], int(a[4]), a[5],
               int(a[6]) if len(a) > 7 else None, int(a[7]) if len(a) > 7 else None)
    elif c == "crop":
        a = sys.argv
        crop(a[2], int(a[3]), *map(float, a[4:8]), int(a[8]), a[9], a[10])
