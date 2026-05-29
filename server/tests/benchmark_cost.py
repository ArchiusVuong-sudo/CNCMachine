"""Cost-engine benchmark vs ground-truth production data.

Brief objective (Project Brief page 1): "Achieve costing accuracy >90%,
benchmark with user's production information." The KB ships the user's
own jobcost history in ``KNOWLEDGE_BASE/extracted/parts.csv`` (one row
per part_number with both ``cost_ea_rm_est`` and ``cost_ea_rm_act``)
and ``operations.csv`` (per-op breakdown with ``run_min_pc_act`` and
``machine``). Together they let us replay the cost-engine formula
against known truth without spinning up the LLM agent.

This script is NOT a unit test in the strict sense — it is a
regression benchmark. Run it from the repo root::

    python -m server.tests.benchmark_cost

It prints:

  - Per-part predicted-vs-actual (sorted by absolute %-error).
  - Pooled MAPE (mean absolute percent error).
  - Pass rate at three accuracy tiers: ±20%, ±10%, ±5%.

It exits 0 if the ±20% tier passes ≥ 70% of parts (a loose initial bar
for novel parts where the agent reasons from analogues). The >90%-of-
parts-within-±10% goal from the brief is the long-term target — when we
hit it, tighten the threshold here.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path
from typing import Iterable


KB_ROOT = Path(__file__).resolve().parents[2] / "KNOWLEDGE_BASE" / "extracted"


def _float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # filter NaN


def load_parts() -> dict[str, dict]:
    """Read parts.csv → {part_number: row_dict}."""
    path = KB_ROOT / "parts.csv"
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pn = (row.get("part_number") or "").strip()
            if pn:
                out[pn] = row
    return out


def load_operations() -> dict[str, list[dict]]:
    """Read operations.csv → {part_number: [op_rows…]}."""
    path = KB_ROOT / "operations.csv"
    out: dict[str, list[dict]] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pn = (row.get("part_number") or "").strip()
            if pn:
                out.setdefault(pn, []).append(row)
    return out


def predict_part_cost(part_row: dict, ops: list[dict], *, hourly_rate_usd: float) -> float | None:
    """Simplified cost prediction: replay machining + setup + material.

    Uses ACTUAL per-op run-minutes from operations.csv so this benchmarks
    the FORMULA (rate × time → USD) — separately from the agent's
    cycle-time prediction error. A second benchmark using ``nc_est_min``
    instead would measure end-to-end accuracy; this one isolates the
    cost-engine layer per the brief's stage-4 scope.
    """
    if not ops:
        return None

    total_run_min = 0.0
    for op in ops:
        rm = _float(op.get("run_min_pc_act")) or _float(op.get("run_min_pc_est"))
        if rm and rm > 0:
            total_run_min += rm
    if total_run_min <= 0:
        return None

    machining_usd = (total_run_min / 60.0) * hourly_rate_usd

    material_usd = _float(part_row.get("material_pc_rm")) or 0.0

    qty = int(_float(part_row.get("order_qty")) or 1)
    setup_min_per_lot = 20.0  # _FIXED_LOT_SETUP_MIN
    n_tools = int(_float(part_row.get("n_tools")) or 0)
    preset_min = n_tools * 3.0  # _TOOL_PRESET_MIN_PER_TOOL
    setup_usd = ((setup_min_per_lot + preset_min) / 60.0 * hourly_rate_usd) / qty

    return round(machining_usd + material_usd + setup_usd, 2)


def percent_error(predicted: float, actual: float) -> float:
    if actual <= 0:
        return float("inf")
    return abs(predicted - actual) / actual * 100.0


def run(args: argparse.Namespace) -> int:
    parts = load_parts()
    operations = load_operations()

    rows: list[tuple[str, float, float, float]] = []  # (pn, predicted, actual, err%)
    skipped: list[tuple[str, str]] = []

    for pn, part_row in parts.items():
        actual = _float(part_row.get("cost_ea_rm_act"))
        if actual is None or actual <= 0:
            skipped.append((pn, "no_actual_cost"))
            continue
        ops = operations.get(pn, [])
        predicted = predict_part_cost(part_row, ops, hourly_rate_usd=args.hourly_rate)
        if predicted is None:
            skipped.append((pn, "no_predicted_cost"))
            continue
        rows.append((pn, predicted, actual, percent_error(predicted, actual)))

    if not rows:
        print("BENCHMARK: no comparable rows found — check parts.csv / operations.csv")
        return 1

    rows.sort(key=lambda r: r[3], reverse=True)

    print(f"\n=== Cost-engine benchmark ({len(rows)} parts) ===")
    print(f"{'PART':<28} {'PRED':>10} {'ACT':>10} {'%ERR':>8}")
    print("-" * 58)
    for pn, pred, act, err in rows[: args.show]:
        print(f"{pn:<28} {pred:>10.2f} {act:>10.2f} {err:>7.1f}%")
    if len(rows) > args.show:
        print(f"... ({len(rows) - args.show} more)")

    errs = [r[3] for r in rows]
    mape = statistics.mean(errs)
    median = statistics.median(errs)

    tiers = [5.0, 10.0, 20.0]
    pass_rates = {tier: sum(1 for e in errs if e <= tier) / len(errs) * 100.0 for tier in tiers}

    print("\n=== Summary ===")
    print(f"n              : {len(rows)} parts ({len(skipped)} skipped)")
    print(f"MAPE           : {mape:.1f}%")
    print(f"Median %err    : {median:.1f}%")
    for tier in tiers:
        marker = "PASS" if pass_rates[tier] >= 70 else "FAIL"
        print(f"<= +/-{int(tier):>2}% accurate : {pass_rates[tier]:5.1f}%   [{marker}]")
    print(f"\nBrief target   : >90% of parts within +/-10% (currently {pass_rates[10.0]:.1f}%)")

    if skipped and args.verbose:
        print(f"\nSkipped {len(skipped)}: {skipped[:5]}...")

    return 0 if pass_rates[20.0] >= 70.0 else 2


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cost-engine benchmark vs jobcost.csv")
    p.add_argument(
        "--hourly-rate", type=float, default=110.0,
        help="Blended hourly rate USD/hr (default 110, matches typical CNCM_PROFILE machining cost).",
    )
    p.add_argument("--show", type=int, default=20, help="Show top-N worst rows.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
