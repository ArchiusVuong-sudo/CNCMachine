#!/usr/bin/env python
"""Merge per-batch shard CSVs (extracted/_shards/<X>_<type>.csv) into the master
extracted/<type>.csv for each type in {parts,operations,tools,jobcost}.
The first line of every shard is its header; we keep ONE header (from the master
file if it already has one, else the first shard) and append all data rows,
sorted by part_number then natural order. Idempotent: rebuilds master from shards.
Usage: python merge_shards.py [kb_root]"""
import sys, csv, glob, os
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\data\KNOWLEDGE_BASE")
EX = ROOT / "extracted"
SH = EX / "_shards"
TYPES = ["parts", "operations", "tools", "jobcost"]

for t in TYPES:
    master = EX / f"{t}.csv"
    header = None
    rows = []
    # prefer the existing master header (canonical column order)
    if master.exists():
        with open(master, newline="", encoding="utf-8") as f:
            r = list(csv.reader(f))
            if r:
                header = r[0]
    shard_files = sorted(glob.glob(str(SH / f"*_{t}.csv")))
    for sf in shard_files:
        with open(sf, newline="", encoding="utf-8") as f:
            r = list(csv.reader(f))
        if not r:
            continue
        if header is None:
            header = r[0]
        for row in r[1:]:
            if not any(c.strip() for c in row):
                continue
            rows.append(row)
    if header is None:
        print(f"[{t}] no header found, skipped")
        continue
    # stable sort by part_number (col 0) preserving op/seq order within a part
    rows.sort(key=lambda x: (x[0] if x else ""))
    with open(master, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    parts_n = len({x[0] for x in rows})
    print(f"[{t}] {len(shard_files)} shards -> {len(rows)} rows, "
          f"{parts_n} distinct part_numbers -> {master.name}")
