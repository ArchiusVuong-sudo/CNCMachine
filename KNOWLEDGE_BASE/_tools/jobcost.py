#!/usr/bin/env python
"""Parse FORESIGHT 'Job Cost - Detail' PDFs (cost & time calibration ground truth).
Reconstructs the positional table by clustering words into rows by Y coordinate,
so the Work-Center labor table (Setup/Run hours Est vs Act, Labor $) is readable.

Usage:
  python jobcost.py rows "<pdf>"      # coordinate-reconstructed rows (best for tables)
  python jobcost.py summary "<pdf>"   # regex-extracted headline fields

Job Cost columns (per Work Center / Operation):
  St | OpCode | Labor$ Est | Labor$ Act | QtyRun | Scrap | Variance |
  WorkCenter | SetupHrs Est | SetupHrs Act | RunHrs Est | RunHrs Act
Run/Setup Hours are TOTAL for the job (divide by Order Qty for per-piece).
'Estimate' column = the shop's original quote; 'Actual' = realized."""
import fitz, sys, re

def rows(pdf, ytol=3.0):
    d = fitz.open(pdf)
    for pi, pg in enumerate(d):
        ws = pg.get_text("words")  # x0,y0,x1,y1,word,block,line,wordno
        ws.sort(key=lambda w: (round(w[1] / ytol), w[0]))
        line, cy, out = [], None, []
        for w in ws:
            if cy is None or abs(w[1] - cy) <= ytol:
                line.append(w); cy = w[1] if cy is None else cy
            else:
                out.append(line); line = [w]; cy = w[1]
        if line:
            out.append(line)
        print(f"\n===== PAGE {pi+1}/{len(d)} =====")
        for ln in out:
            ln.sort(key=lambda w: w[0])
            s = "  ".join(t[4] for t in ln).strip()
            if s:
                print(s)
    d.close()

def summary(pdf):
    d = fitz.open(pdf); t = "\n".join(p.get_text() for p in d); d.close()
    def g(pat):
        m = re.search(pat, t, re.I)
        return m.group(1).strip() if m else None
    fields = {
        "Job": g(r"Job:\s*([A-Z0-9\-]+)"),
        "Part": g(r"Part:\s*\n?\s*([0-9A-Z\-]+)"),
        "Customer": g(r"(Lam Research[^\n]*|[A-Z][A-Za-z ]+Corporation)"),
        "Order Qty": g(r"Order Qty[:\s]*\n?\s*([0-9]+)"),
        "Unit Price": g(r"([0-9,]+\.\d+)\s*/\s*each"),
    }
    for k, v in fields.items():
        print(f"{k}: {v}")
    print("\n-- money lines --")
    for ln in t.splitlines():
        if re.search(r"(RM[\d,]+\.\d|Profit|Revenue|Cost/EA|Total Cost|Variance|"
                     r"Setup Hours|Run Hours|Labor)", ln, re.I):
            s = ln.strip()
            if s:
                print(s)

if __name__ == "__main__":
    (rows if sys.argv[1] == "rows" else summary)(sys.argv[2])
