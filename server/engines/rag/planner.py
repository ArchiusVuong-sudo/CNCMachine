"""Per-component RAG planner.

Glue layer:

   target component
        │
        ▼
   build_query_text  ──►  retrieve_analogues  (pgvector ANN)
                             │
                             ├──► retrieve_patterns (optional, weak match)
                             ▼
                       build_user_prompt
                             │
                             ▼
                       generate_plan (one LLM call, JSON mode)
                             │
                             ▼
                       snap_machine_to_catalog
                       snap_plan_to_catalog
                             │
                             ▼
                       build_routing_rows
                             │
                             ▼
                  (routing_rows, manufacturing_processes,
                   rag_meta dict with retrieval + snap stats)

Failures here mirror the agentic policy ("agent only, no fallback"):
the offending component is marked failed, the rest of the assembly
continues. The coordinator catches the RagPlannerError.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .generator import RagGenerationError, generate_plan
from .projection import build_routing_rows
from .prompts import build_system_prompt, build_user_prompt
from .retriever import retrieve_analogues, retrieve_patterns
from .tool_snap import snap_machine_to_catalog, snap_plan_to_catalog

logger = logging.getLogger("cncserver.engines.rag.planner")

OnThinking = Callable[[str], Awaitable[None]] | None

# Cosine similarity below this on the top-1 analogue means coverage is
# weak — we fetch pattern chunks as a fallback context.
_WEAK_ANALOGUE_THRESHOLD = 0.60


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------

def _build_query_text(drawing: dict, component: dict) -> str:
    """Compose the short natural-language query we embed for retrieval.

    Keep this in the same prose style as the descriptors stored in the
    index — the embedding cosine is biased by surface form.
    """
    pn = drawing.get("part_number") or ""
    bom_pt = component.get("bom_part_type") or component.get("part_type") or ""
    material = component.get("material") or drawing.get("material") or ""
    name = component.get("name") or ""

    features = component.get("features") or []
    feature_type_counts: dict[str, int] = {}
    for f in features:
        ft = (f or {}).get("type") or (f or {}).get("feature_type") or "unknown"
        feature_type_counts[ft] = feature_type_counts.get(ft, 0) + 1
    fp_bits = [f"{n} {ft}" for ft, n in sorted(feature_type_counts.items(), key=lambda kv: -kv[1])][:8]

    bbox = component.get("bbox") or component.get("bounding_box") or {}
    envelope_bits = []
    if isinstance(bbox, dict):
        for ax in ("dx_mm", "dy_mm", "dz_mm"):
            v = bbox.get(ax)
            if v is not None:
                try:
                    envelope_bits.append(f"{float(v):.1f}")
                except (TypeError, ValueError):
                    continue
    envelope_str = "x".join(envelope_bits) if envelope_bits else None

    parts: list[str] = []
    if name:
        parts.append(f"Component {name}")
    if pn:
        parts.append(f"of part {pn}")
    if material:
        parts.append(f"in {material}")
    if bom_pt:
        parts.append(f"({bom_pt})")
    if envelope_str:
        parts.append(f"envelope {envelope_str} mm")
    if len(features):
        parts.append(f"{len(features)} features")
    if fp_bits:
        parts.append("(" + ", ".join(fp_bits) + ")")

    return " ".join(parts) or "Generic CNC component"


# ---------------------------------------------------------------------------
# Material family bucketing (used as a hard filter on the analogue ANN)
# ---------------------------------------------------------------------------

_MATERIAL_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("peek", "pp ", "pvc", "acetal", "nylon", "uhmw", "hdpe", "pet ", "semitron", "delrin", "ptfe"), "plastics"),
    (("alum", "al60", "al70", "6061", "7075", "2024", "5052"), "aluminum"),
    (("stainless", "ss30", "ss31", "ss41", "ss42", "303", "304", "316", "17-4", "17-7"), "stainless"),
    (("steel", "10", "11", "12", "41", "42", "43", "44", "45", "46", "47", "48", "49", "8620", "4140"), "steels"),
    (("brass", "bronze", "copper", "cu "), "copper_alloys"),
    (("titan", "ti-", "ti6", "grade 5"), "titanium"),
    (("inconel", "hastel", "monel", "waspaloy"), "superalloys"),
]


def _material_family(material: str | None) -> str | None:
    if not material:
        return None
    m = material.lower()
    for hints, fam in _MATERIAL_HINTS:
        if any(h in m for h in hints):
            return fam
    return None


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def plan_one_component(
    drawing: dict,
    component: dict,
    *,
    catalog: dict | None,
    batch_size: int = 1,
    on_thinking: OnThinking = None,
    top_k: int | None = None,
    top_k_patterns: int | None = None,
    model: str | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """Run the RAG pipeline for one component.

    Returns ``(rag_meta, routing_rows, manufacturing_processes)``.

    ``rag_meta`` is a small summary dict the coordinator attaches to the
    component (mirrors how the agentic engine attaches ``component["agentic"]``).
    It carries machine choice, totals, rationale, evidence, retrieval
    counters, and tool-snap stats so the SSE final_answer surfaces the
    same info both engines emit.
    """
    # ── 1. Retrieve ─────────────────────────────────────────────────────────
    query_text = _build_query_text(drawing, component)
    target_material = component.get("material") or drawing.get("material")
    target_family = _material_family(target_material)
    target_pt = component.get("bom_part_type") or component.get("part_type")

    analogues = await retrieve_analogues(
        query_text=query_text,
        part_type=target_pt,
        material_family=target_family,
        top_k=top_k,
    )

    patterns: list[dict] = []
    weak = (
        not analogues
        or float((analogues[0] or {}).get("similarity") or 0.0) < _WEAK_ANALOGUE_THRESHOLD
        or all(a.get("_filter_fallback") for a in analogues)
    )
    if weak:
        try:
            patterns = await retrieve_patterns(
                query_text=query_text, top_k=top_k_patterns,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan_one_component: retrieve_patterns failed: %s", exc)
            patterns = []

    top_sim = float((analogues[0] or {}).get("similarity") or 0.0) if analogues else 0.0
    logger.info(
        "plan_one_component[%s]: query=%r analogues=%d patterns=%d "
        "top_sim=%.3f filter_fallback=%d",
        component.get("name") or component.get("component_index"),
        query_text[:120],
        len(analogues), len(patterns), top_sim,
        sum(1 for a in analogues if a.get("_filter_fallback")),
    )

    # ── 2. Generate ─────────────────────────────────────────────────────────
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(
        drawing, component,
        analogues=analogues,
        patterns=patterns or None,
        catalog=catalog,
        batch_size=batch_size,
    )

    try:
        plan = await generate_plan(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            on_thinking=on_thinking,
            model=model,
        )
    except RagGenerationError as exc:
        raise RagPlannerError(f"generator: {exc}") from exc

    # ── 3. Snap to catalog ─────────────────────────────────────────────────
    snap_machine_to_catalog(plan, catalog)
    snap_plan_to_catalog(plan, catalog)

    # ── 4. Project to routing rows ─────────────────────────────────────────
    routing_rows, manufacturing_processes = build_routing_rows(
        plan,
        default_machine_id=plan.get("chosen_machine_id"),
    )
    if not routing_rows:
        raise RagPlannerError(
            "projection produced 0 routing rows — plan had no usable operations"
        )

    # ── 5. Assemble the meta dict surface ───────────────────────────────────
    meta: dict[str, Any] = {
        "machine_class":          plan.get("machine_class"),
        "top_machines":           plan.get("top_machines"),
        "chosen_machine_id":      plan.get("chosen_machine_id"),
        "total_run_min_per_part": plan.get("total_run_min_per_part"),
        "setup_min_per_lot":      plan.get("setup_min_per_lot"),
        "rationale":              plan.get("rationale"),
        "evidence":               plan.get("evidence") or [],
        "confidence_band_pct":    plan.get("confidence_band_pct"),
        "retrieval": {
            "query_text":              query_text,
            "analogues_count":         len(analogues),
            "top_similarity":          top_sim,
            "filter_fallback_count":   sum(1 for a in analogues if a.get("_filter_fallback")),
            "patterns_count":          len(patterns),
            "analogue_part_numbers":   [a.get("part_number") for a in analogues],
            "weak_coverage":           bool(weak),
        },
        "tool_snap_stats":        plan.get("_tool_snap_stats"),
    }
    return meta, routing_rows, manufacturing_processes


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RagPlannerError(RuntimeError):
    """Raised when planning a single component fails terminally.

    Caught by the RAG coordinator: the component is marked failed and
    the rest of the assembly continues. Mirrors agentic's "agent only,
    no fallback" policy so engine comparison is fair.
    """


__all__ = ["plan_one_component", "RagPlannerError"]
