"""Public Engine 4 (CAM) entry: STEP bytes + ProcessPlan → ``.nc`` files.

Mirrors the public surface of the other engines (``async run(...) -> Pydantic``)
so the orchestrator and the on-demand REST endpoint can share the same
implementation.

Outputs
-------
Each call writes one ``.nc`` per material-removal :class:`ManufacturingProcess`
into ``<runs_root>/<analysis_id>/<component_name>/seq_<NN>_<op_code>.nc``.
The function returns a :class:`CAMOutput` listing every file it wrote
plus per-component diagnostic info.

Failure policy
--------------
Like the other engines, :func:`run` **never raises** — a missing FreeCAD
install, a subprocess timeout, or a malformed plan all collapse to
``CAMOutput(ok=False, error=...)``. The orchestrator can treat the engine
as best-effort and still emit ``done`` to the SSE stream.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...core.events import OnEvent, safe_emit
from ...core.schemas import ProcessPlan
from ...core.settings import get_settings
from .freecad_runner import run_cam_subprocess
from .op_mapping import is_cam_op, lookup as op_lookup

logger = logging.getLogger("cncserver.engines.cam")


# ---------------------------------------------------------------------------
# Public result shape
# ---------------------------------------------------------------------------

class CAMOpOutput(BaseModel):
    """One .nc file the FreeCAD script wrote."""

    model_config = ConfigDict(extra="allow")

    sequence: int
    op_code:  str
    path:     str
    size:     int = 0


class CAMComponentResult(BaseModel):
    """Per-component CAM result."""

    model_config = ConfigDict(extra="allow")

    component_index: int
    component_name:  str
    ok:              bool = True
    outputs:         list[CAMOpOutput] = Field(default_factory=list)
    error:           str | None = None
    per_op_error_count: int = 0


class CAMOutput(BaseModel):
    """Engine 4's top-level output, returned to the orchestrator."""

    model_config = ConfigDict(extra="allow")

    ok:              bool = True
    analysis_id:     str
    runs_dir:        str
    by_component:    list[CAMComponentResult] = Field(default_factory=list)
    total_files:     int = 0
    elapsed_seconds: float = 0.0
    error:           str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Component / op names land in directory paths; strip anything that isn't a
# safe filename character before joining.
_PATH_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_path_segment(name: str, fallback: str) -> str:
    cleaned = _PATH_SAFE_RE.sub("_", (name or "").strip())
    return cleaned or fallback


def _runs_root() -> str:
    """Absolute base directory for .nc output. Defaults to ``<repo>/runs``."""
    override = os.environ.get("CAM_RUNS_DIR")
    if override:
        return override
    return str(get_settings().repo_root / "runs")


def _component_solid_index(components: list[dict], comp_idx: int) -> int | None:
    """STEP solid index for ``components[comp_idx]``.

    When the OCC stage drops COMPOUND wrappers the surviving components
    are re-indexed contiguously, so the position in ``components`` lines
    up with the position in ``shape.Solids`` *after* the same filter is
    applied. We pass that integer down to FreeCAD as a hint; the script
    falls back to the full compound when the index doesn't resolve.
    """
    if comp_idx < 0 or comp_idx >= len(components):
        return None
    return comp_idx


def _build_op_specs(
    routing_rows: list[dict],
    manufacturing_processes: list[dict],
    features: list[dict],
) -> list[dict]:
    """Build the per-op spec list the FreeCAD script consumes.

    One spec per :class:`ManufacturingProcess` (per tool). The routing
    row supplies ``feature_ids`` (resolved to key_face_ids via the
    component's features list); the manufacturing process supplies the
    cutting parameters Phase D calibrated.
    """
    # Index features by feature_id when available, else by key_face_id.
    feat_by_id: dict[str, dict] = {}
    for feat in features or []:
        if not isinstance(feat, dict):
            continue
        fid = feat.get("feature_id") or feat.get("key_face_id")
        if fid:
            feat_by_id[str(fid)] = feat

    # Bucket routing rows by sequence so we can find an op's feature_ids
    # from its sequence_order.
    rows_by_seq: dict[int, dict] = {}
    for row in routing_rows or []:
        if not isinstance(row, dict):
            continue
        try:
            seq = int(row.get("sequence") or 0)
        except (TypeError, ValueError):
            continue
        rows_by_seq[seq] = row

    specs: list[dict] = []
    for mp in manufacturing_processes or []:
        if not isinstance(mp, dict):
            continue
        try:
            seq = int(mp.get("sequence_order") or 0)
        except (TypeError, ValueError):
            seq = 0
        row = rows_by_seq.get(seq, {})
        op_code = row.get("op_code") or "CNCM_OP"

        # Skip non-CAM ops outright — deburring / inspection / sheet-cut have
        # no place in the CAM engine, and the op_mapping table is the source
        # of truth for what we know how to emit.
        if not is_cam_op(op_code):
            continue
        mapping = op_lookup(op_code)
        if mapping is None:
            continue

        # Resolve feature_ids → key_face_ids. Routing rows carry the agent's
        # feature_ids; manufacturing_process carries driven_by_features. We
        # union them so neither source's omission silently drops faces.
        feat_ids = list(row.get("feature_ids") or [])
        feat_ids.extend(mp.get("driven_by_features") or [])
        key_face_ids: list[str] = []
        seen: set[str] = set()
        for fid in feat_ids:
            sfid = str(fid)
            if sfid in seen:
                continue
            seen.add(sfid)
            feat = feat_by_id.get(sfid)
            kfid = (feat or {}).get("key_face_id") if feat else None
            # If the agent emitted a Face-style ID directly we accept it as-is;
            # if it resolves through a feature we use the feature's hash.
            if kfid:
                key_face_ids.append(str(kfid))
            elif sfid.startswith("Face"):
                key_face_ids.append(sfid)

        specs.append({
            "sequence":           seq,
            "op_code":            op_code,
            "path_op":            mapping["path_op"],
            "kind":               mapping["kind"],
            "tool_type":          mp.get("tool_type"),
            "tool_dimensions":    mp.get("tool_dimensions") or {
                "diameter_mm":      mp.get("tool_diameter_mm"),
            },
            "spindle_speed_rpm":  mp.get("spindle_speed_rpm"),
            "feed_rate_mm_min":   mp.get("feed_rate_mm_min"),
            "stepover_mm":        mp.get("stepover_mm"),
            "stepdown_mm":        mp.get("stepdown_mm"),
            "key_face_ids":       key_face_ids,
            "machine_id":         mp.get("machine_id"),
            "operation_type":     mp.get("operation_type"),
        })

    specs.sort(key=lambda s: (s.get("sequence") or 0, s.get("op_code") or ""))
    return specs


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def run(
    step_bytes: bytes,
    plan: ProcessPlan | dict,
    *,
    analysis_id: str,
    on_event: OnEvent = None,
    runs_root: str | None = None,
) -> CAMOutput:
    """Generate G-code for every CAM op in ``plan``.

    Parameters
    ----------
    step_bytes : raw STEP bytes (same artifact Engine 2 consumed).
    plan : the :class:`ProcessPlan` from Engine 3, or an equivalent dict.
    analysis_id : run identifier — used as the leaf directory under
        ``runs_root`` so concurrent runs don't collide.
    on_event : SSE callback for status updates.
    runs_root : output base directory; defaults to ``<repo>/runs``.

    Returns
    -------
    :class:`CAMOutput` — never raises.
    """
    t0 = time.monotonic()
    base = runs_root or _runs_root()
    run_dir = os.path.join(base, _safe_path_segment(analysis_id, "unknown"))

    plan_dict: dict
    if isinstance(plan, ProcessPlan):
        plan_dict = plan.as_dict()
    elif isinstance(plan, dict):
        plan_dict = plan
    else:
        return CAMOutput(
            ok=False, analysis_id=analysis_id, runs_dir=run_dir,
            error=f"unsupported plan type: {type(plan).__name__}",
        )

    components             = list(plan_dict.get("components") or [])
    processes_per_component = list(plan_dict.get("processes_per_component") or [])
    post = plan_dict.get("post_processor") \
        or get_settings().process_mapping.default_post_processor

    if not components:
        return CAMOutput(
            ok=False, analysis_id=analysis_id, runs_dir=run_dir,
            error="plan has no components",
        )
    if not step_bytes:
        return CAMOutput(
            ok=False, analysis_id=analysis_id, runs_dir=run_dir,
            error="step_bytes is empty",
        )

    try:
        os.makedirs(run_dir, exist_ok=True)
    except Exception as exc:
        return CAMOutput(
            ok=False, analysis_id=analysis_id, runs_dir=run_dir,
            error=f"mkdir failed: {exc}",
        )

    logger.info(
        "cam_engine START: analysis_id=%s components=%d runs_dir=%s post=%s",
        analysis_id, len(components), run_dir, post,
    )
    await safe_emit(on_event, "status", {
        "title":   "CAM (FreeCAD)",
        "message": f"Generating G-code for {len(components)} component(s)…",
    })

    by_component: list[CAMComponentResult] = []
    total_files = 0

    for comp_idx, component in enumerate(components):
        comp_name = (component or {}).get("name") or f"component_{comp_idx}"
        rows = (
            processes_per_component[comp_idx]
            if comp_idx < len(processes_per_component) else []
        )
        mfg = (component or {}).get("manufacturing_processes") or []
        features = (component or {}).get("features") or []

        op_specs = _build_op_specs(rows, mfg, features)
        if not op_specs:
            logger.info(
                "cam_engine: component %d (%s) — no CAM ops to emit, skipping",
                comp_idx, comp_name,
            )
            by_component.append(CAMComponentResult(
                component_index=comp_idx, component_name=comp_name,
                ok=True, outputs=[], error=None,
            ))
            continue

        comp_dir = os.path.join(run_dir, _safe_path_segment(comp_name, f"component_{comp_idx}"))
        try:
            os.makedirs(comp_dir, exist_ok=True)
        except Exception as exc:
            by_component.append(CAMComponentResult(
                component_index=comp_idx, component_name=comp_name,
                ok=False, error=f"mkdir failed: {exc}",
            ))
            continue

        job_spec = {
            "analysis_id":             analysis_id,
            "component_name":          comp_name,
            "component_index":         comp_idx,
            "component_solid_index":   _component_solid_index(components, comp_idx),
            "post_processor":          post,
            "operations":              op_specs,
        }

        await safe_emit(on_event, "tool_call", {
            "tool":      "generate_gcode",
            "iteration": 1,
            "label":     f"FreeCAD CAM — {comp_name} ({len(op_specs)} op)",
        })

        try:
            sub_result = await run_cam_subprocess(
                step_bytes, job_spec, out_dir=comp_dir,
            )
        except Exception as exc:
            logger.exception("cam_engine: subprocess raised for component %d", comp_idx)
            by_component.append(CAMComponentResult(
                component_index=comp_idx, component_name=comp_name,
                ok=False, error=f"{exc.__class__.__name__}: {exc}",
            ))
            continue

        outputs = [
            CAMOpOutput(
                sequence=int(o.get("sequence") or 0),
                op_code=str(o.get("op_code") or "UNKNOWN"),
                path=str(o.get("path") or ""),
                size=int(o.get("size") or 0),
            )
            for o in (sub_result.get("outputs") or [])
            if isinstance(o, dict)
        ]
        total_files += len(outputs)
        by_component.append(CAMComponentResult(
            component_index=comp_idx,
            component_name=comp_name,
            ok=bool(sub_result.get("ok")),
            outputs=outputs,
            error=sub_result.get("error"),
            per_op_error_count=int(sub_result.get("per_op_error_count") or 0),
        ))

        await safe_emit(on_event, "tool_result", {
            "tool":   "generate_gcode",
            "result": {
                "component":  comp_name,
                "files":      len(outputs),
                "errors":     sub_result.get("per_op_error_count") or 0,
                "ok":         bool(sub_result.get("ok")),
            },
        })

    elapsed = round(time.monotonic() - t0, 2)
    overall_ok = bool(by_component) and all(c.ok for c in by_component)
    logger.info(
        "cam_engine DONE: ok=%s components=%d files=%d elapsed=%.2fs runs_dir=%s",
        overall_ok, len(by_component), total_files, elapsed, run_dir,
    )
    await safe_emit(on_event, "status", {
        "title":     "CAM (FreeCAD)",
        "message":   f"Wrote {total_files} .nc file(s) under {run_dir}",
        "completed": True,
    })

    return CAMOutput(
        ok=overall_ok,
        analysis_id=analysis_id,
        runs_dir=run_dir,
        by_component=by_component,
        total_files=total_files,
        elapsed_seconds=elapsed,
        error=None if overall_ok else "one or more components failed CAM",
    )


__all__ = ["run", "CAMOutput", "CAMComponentResult", "CAMOpOutput"]
