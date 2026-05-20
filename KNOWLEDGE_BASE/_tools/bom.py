#!/usr/bin/env python
"""Parse BOM_*.csv (UTF-16, tab-ish). These list purchased hardware/inserts/specs
NOT the raw machined stock (raw stock = the part itself; stock size is on the
drawing / setup sheet / Job Cost 'Material' section).
Usage: python bom.py "<BOM csv>" """
import sys, csv, io

def main(p):
    raw = open(p, "rb").read()
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except Exception:
            continue
    txt = txt.replace("\x00", "")
    # collapse the wide-spaced glyphs some exports use
    rows = list(csv.reader(io.StringIO(txt), delimiter="\t"))
    for r in rows:
        cells = [c.strip() for c in r if c.strip()]
        if cells:
            print(" | ".join(cells)[:300])

if __name__ == "__main__":
    main(sys.argv[1])
