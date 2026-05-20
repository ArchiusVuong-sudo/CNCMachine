#!/usr/bin/env python
"""Parse Fanuc/Mastercam-posted NC G-code -> per-operation tools, feeds, speeds,
toolpath length, and an ESTIMATED cycle time. Ground-truth physics layer.

Usage: python nc_analyze.py "<ncfile>" [rapid_mmpm=30000] [tc_s=6]

Cycle-time model (documented assumptions, tune in patterns/cycle_time_model.md):
  feed move time  = distance(mm) / F(mm/min) * 60   [s]
  rapid move time = distance(mm) / rapid_mmpm * 60   [s]
  + tool-change time per T..M6  (tc_s, default 6 s)
  + dwell G4 P/X seconds
Arc G2/G3 length = swept-angle * radius (IJK or R form). Drilling canned cycles
(G81/82/83 ... G80) counted as feed plunge*retract per hole at last F.
Reported time is a LOWER-ish bound (no accel/decel); calibrate with the
factor in cycle_time_model.md against Job Cost 'Run Hours'."""
import sys, re, math
from pathlib import Path

def num(tok, ln):
    m = re.search(rf"{tok}(-?\d*\.?\d+)", ln)
    return float(m.group(1)) if m else None

def main():
    p = Path(sys.argv[1])
    rapid = float(sys.argv[2]) if len(sys.argv) > 2 else 30000.0
    tc_s = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
    txt = p.read_text(errors="replace")
    lines = txt.splitlines()

    tools = {}
    for ln in lines:
        m = re.match(r"\(\s*T(\d+)\s*\|\s*H\d+\s*\|\s*D\d+\s*\|(.*?)\|", ln)
        if m:
            tools[int(m.group(1))] = m.group(2).strip()

    x = y = z = a = 0.0
    have = False
    F = 0.0
    S = 0.0
    g_motion = 0
    cur_tool = None
    op_name = None
    canned = None           # active drilling cycle G8x
    rcanned = 0.0
    feed_d = rapid_d = 0.0
    feed_t = rapid_t = tc_t = dwell_t = 0.0
    ops = []                # (op_name, tool#, toolname, S, Ffirst, feed_mm, rapid_mm, secs)
    cur = None

    def flush():
        nonlocal cur
        if cur and (cur["feed"] > 0 or cur["rapid"] > 0):
            cur["secs"] = cur["ft"] + cur["rt"] + cur["dt"]
            ops.append(cur)
        cur = None

    def newop(name):
        nonlocal cur
        flush()
        cur = dict(op=name or "", tool=cur_tool,
                   tname=tools.get(cur_tool, ""), S=S, F=None,
                   feed=0.0, rapid=0.0, ft=0.0, rt=0.0, dt=0.0)

    for ln in lines:
        raw = ln.strip()
        cm = re.match(r"\((.*)\)", raw)
        if cm:
            c = cm.group(1).strip()
            up = c.upper()
            if up.startswith(("T", "MACHINE", "DATE", "NC FILE", "MCAM", "PROGRAMMER",
                              "POST", "MASTERCAM", "MODIFICATION", "LAST", "NOTE",
                              "SAFETY", "TOOL LIST")) or "|" in c:
                continue
            if 2 <= len(c) <= 60:           # operation/feature label
                newop(c)
            continue
        if not raw or raw.startswith("%"):
            continue

        if re.search(r"\bT(\d+)\b", raw) and re.search(r"\bM0?6\b", raw):
            cur_tool = int(re.search(r"\bT(\d+)\b", raw).group(1))
            tc_t += tc_s
            if cur:
                cur["tool"] = cur_tool
                cur["tname"] = tools.get(cur_tool, "")

        sp = num("S", raw)
        if sp is not None:
            S = sp
            if cur and not cur["S"]:
                cur["S"] = S
        fr = num("F", raw)
        if fr is not None and fr > 0:
            F = fr
            if cur and cur["F"] is None:
                cur["F"] = F

        for gm in re.findall(r"G(\d+)", raw):
            gi = int(gm)
            if gi in (0, 1, 2, 3):
                g_motion = gi
            if gi in (81, 82, 83, 73, 84, 85, 86):
                canned = gi
            if gi == 80:
                canned = None
            if gi == 4:
                dv = num("P", raw)
                dwell_t += (dv / 1000.0 if dv and dv > 30 else (num("X", raw) or (dv or 0)))

        nx, ny, nz = num("X", raw), num("Y", raw), num("Z", raw)
        na = num("A", raw)
        if any(v is not None for v in (nx, ny, nz)) and re.search(r"\bG?0?[0-3]\b|X|Y|Z", raw):
            tx = x if nx is None else nx
            ty = y if ny is None else ny
            tz = z if nz is None else nz
            if not have:
                x, y, z, have = tx, ty, tz, True
            else:
                if canned and nz is not None and (g_motion in (0, 1)):
                    # canned drilling: rapid to R, feed plunge to Z, retract
                    plunge = abs((rcanned or z) - tz)
                    feed_d += plunge
                    rapid_d += plunge
                    if F > 0:
                        feed_t += plunge / F * 60
                    rapid_t += plunge / rapid * 60
                    xy = math.hypot(tx - x, ty - y)
                    rapid_d += xy
                    rapid_t += xy / rapid * 60
                else:
                    d = math.sqrt((tx-x)**2 + (ty-y)**2 + (tz-z)**2)
                    if g_motion in (2, 3):  # arc
                        r = num("R", raw)
                        I, J = num("I", raw), num("J", raw)
                        rr = r if r else (math.hypot(I or 0, J or 0) or None)
                        if rr and d <= 2*abs(rr):
                            ang = 2 * math.asin(min(1.0, d / (2*abs(rr))))
                            d = abs(rr) * (ang if ang else 0) or d
                    if g_motion == 0:
                        rapid_d += d
                        rapid_t += d / rapid * 60
                        if cur:
                            cur["rapid"] += d; cur["rt"] += d / rapid * 60
                    else:
                        feed_d += d
                        if F > 0:
                            feed_t += d / F * 60
                            if cur:
                                cur["ft"] += d / F * 60
                        if cur:
                            cur["feed"] += d
                x, y, z = tx, ty, tz
            if na is not None:
                a = na
        rc = num("R", raw)
        if canned and rc is not None:
            rcanned = rc
    flush()

    total = feed_t + rapid_t + tc_t + dwell_t
    print(f"FILE: {p.name}")
    mm = re.search(r"\(MACHINE NAME[^)]*\)", txt)
    if mm:
        print(mm.group(0))
    print(f"tools_in_header={len(tools)}  operations={len(ops)}")
    print(f"feed_dist={feed_d/1000:.1f} m  rapid_dist={rapid_d/1000:.1f} m")
    print(f"EST_CYCLE: feed={feed_t/60:.1f}m rapid={rapid_t/60:.1f}m "
          f"toolchg={tc_t/60:.1f}m dwell={dwell_t/60:.1f}m "
          f"TOTAL={total/60:.1f} min  (rapid={rapid:.0f}mm/min tc={tc_s:.0f}s, no accel)")
    print("--- per operation ---")
    print("idx | op | T# | Sspeed | Ffeed | feed_mm | rapid_mm | est_min | tool")
    for i, o in enumerate(ops):
        print(f"{i:>3} | {o['op'][:34]:34} | T{o['tool']} | {o['S'] or 0:.0f} | "
              f"{o['F'] or 0:.0f} | {o['feed']:.0f} | {o['rapid']:.0f} | "
              f"{o['secs']/60:.2f} | {o['tname'][:42]}")

if __name__ == "__main__":
    main()
