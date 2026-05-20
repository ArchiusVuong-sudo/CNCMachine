#!/usr/bin/env python
"""Phase-4 aggregate miner over extracted/*.csv. Prints the high-signal patterns
needed to write patterns/*.md: machine burden rates, NC calibration k by
machine/material, material $/pc by form, feeds/speeds bands by material+tooltype,
setup-hr and cost-structure by class, profit/loss distribution.
Usage: python analyze.py [kb_root]"""
import sys, csv, statistics as st
from pathlib import Path
from collections import defaultdict

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\data\KNOWLEDGE_BASE")
EX = ROOT / "extracted"

def rd(name):
    with open(EX / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def fnum(s):
    if s is None: return None
    s = str(s).replace("RM", "").replace(",", "").replace("~", "").strip()
    if s in ("", "-", "—", "?", "n/a", "NA", "unknown"): return None
    try: return float(s.split()[0].split("-")[0].split("/")[0])
    except Exception:
        try: return float(s)
        except Exception: return None

parts = rd("parts.csv"); jc = rd("jobcost.csv")
tools = rd("tools.csv"); ops = rd("operations.csv")

print(f"\n#### DATASET: {len(parts)} parts | {len(jc)} jobcost rows | "
      f"{len(tools)} tool rows | {len(ops)} op rows\n")

# 1. Machine burden rates RM/hr (from jobcost.rate_rm_hr)
print("== MACHINE BURDEN RATES RM/hr (median [min..max], n) ==")
mr = defaultdict(list)
for r in jc:
    rate = fnum(r.get("rate_rm_hr"))
    m = (r.get("machine") or r.get("work_center") or "").strip()
    if rate and 30 < rate < 500 and m:
        mr[m].append(rate)
for m, v in sorted(mr.items(), key=lambda kv: -st.median(kv[1])):
    print(f"  {m:22s} {st.median(v):6.0f}  [{min(v):.0f}..{max(v):.0f}] n={len(v)}")

# 2. NC calibration k by machine (from operations.nc_calib_k)
print("\n== NC CALIBRATION k = actual/NC-est, by machine (median, n) ==")
kk = defaultdict(list)
for r in ops:
    k = fnum(r.get("nc_calib_k")); m = (r.get("machine") or "").strip()
    if k and 0.3 < k < 5 and m:
        kk[m].append(k)
for m, v in sorted(kk.items()):
    print(f"  {m:22s} k≈{st.median(v):.2f}  [{min(v):.2f}..{max(v):.2f}] n={len(v)}")

# 3. Material $/pc by stock form + material family
print("\n== MATERIAL RM/pc by family x form (median, n) ==")
mat = defaultdict(list)
for r in parts:
    mp = fnum(r.get("material_pc_rm"))
    fam = "PEEK" if "PEEK" in (r.get("material") or "").upper() else (
          "PP" if "PP" in (r.get("material") or "").upper() or "POLYPROP" in (r.get("material") or "").upper() else "other")
    form = (r.get("stock_form") or "?").upper()
    if mp:
        mat[(fam, form)].append(mp)
for k, v in sorted(mat.items()):
    print(f"  {k[0]:5s} {k[1]:7s} RM {st.median(v):8.2f}  [{min(v):.2f}..{max(v):.2f}] n={len(v)}")

# 4. Feeds/speeds bands by material family x tool_type
print("\n== FEED mm/min & SPEED rpm by material x tool_type (median[min..max] n) ==")
fs = defaultdict(lambda: ([], []))
for r in tools:
    fam = "PEEK" if "PEEK" in (r.get("material") or "").upper() else (
          "PP" if "PP" in (r.get("material") or "").upper() else "")
    tt = (r.get("tool_type") or "").strip().lower()
    f = fnum(r.get("feed_mm_min")); s = fnum(r.get("speed_rpm"))
    if not fam or not tt: continue
    if f: fs[(fam, tt)][0].append(f)
    if s: fs[(fam, tt)][1].append(s)
for k, (F, S) in sorted(fs.items()):
    if len(F) + len(S) < 2: continue
    fp = f"F {st.median(F):5.0f}[{min(F):.0f}..{max(F):.0f}]n{len(F)}" if F else "F –"
    sp = f"S {st.median(S):5.0f}[{min(S):.0f}..{max(S):.0f}]n{len(S)}" if S else "S –"
    print(f"  {k[0]:4s} {k[1]:20s} {fp:30s} {sp}")

# 5. Setup hr & cost structure by class
print("\n== SETUP hr/job & COST by CLASS (median) ==")
cl = defaultdict(lambda: defaultdict(list))
for r in parts:
    c = (r.get("class") or "?").strip()
    for fld in ("total_setup_hr","total_run_min_pc","cost_ea_rm_act",
                "cost_ea_rm_est","unit_price_rm","material_pc_rm","order_qty"):
        v = fnum(r.get(fld))
        if v is not None: cl[c][fld].append(v)
for c, d in cl.items():
    print(f"  [{c}] n={len(d.get('unit_price_rm',[]))}")
    for fld in ("order_qty","total_setup_hr","total_run_min_pc","material_pc_rm",
                "cost_ea_rm_act","unit_price_rm"):
        v = d.get(fld, [])
        if v: print(f"     {fld:20s} med {st.median(v):9.2f}  [{min(v):.2f}..{max(v):.2f}]")

# 6. Profit/loss: unit_price vs cost_ea_act
print("\n== PROFIT/LOSS (unit_price - cost_ea_act) ==")
loss = win = 0; deltas = []
for r in parts:
    up = fnum(r.get("unit_price_rm")); ca = fnum(r.get("cost_ea_rm_act")) or fnum(r.get("cost_ea_rm_est"))
    if up is None or ca is None or up == 0: continue
    d = up - ca; deltas.append((d/ca*100) if ca else 0)
    if d < 0: loss += 1
    else: win += 1
if deltas:
    print(f"  parts priced: {win+loss} | LOSS-making: {loss} | profitable: {win}")
    print(f"  margin% median {st.median(deltas):.0f}  [{min(deltas):.0f}..{max(deltas):.0f}]")
print()
