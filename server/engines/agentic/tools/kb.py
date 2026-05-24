"""Knowledge-Base read tools for the agentic engine.

Three read-only tools surface the KB to the agent during reasoning:

  * :func:`kb_read`          — fetch a markdown/text file under KB
  * :func:`kb_find_analogues` — rank analogue parts from ``extracted/parts.csv``
  * :func:`kb_query_csv`     — filter rows from any ``extracted/*.csv``

All paths are validated to stay under ``KNOWLEDGE_BASE/`` — traversal
attempts come back as ``{"error": "..."}`` rather than raising, so the
agent loop can keep going.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from ....infra.materials import DEFAULT_MATERIAL, MATERIALS, match_material
from .citation import (
    citation_hint_for_csv,
    citation_hint_for_kb,
)

logger = logging.getLogger("cncserver.engines.agentic.tools.kb")

# tools/kb.py → tools → agentic → engines → server → data
_REPO_ROOT = Path(__file__).resolve().parents[4]
KB_ROOT = (_REPO_ROOT / "KNOWLEDGE_BASE").resolve()


def normalize_part_id(raw: str) -> str:
    """Normalize a part_number for holdout comparison.

    Strips a trailing dash-suffix (``-001``, ``-A01``, ``-XXX``) when the
    base stem has at least 2 tokens, so ``"839-323453"``, ``"839-323453-001"``
    and ``"839-323453-XXX"`` all collapse to the same stem ``"839-323453"``.
    Returns lower-case.
    """
    s = (raw or "").strip().lower()
    if not s:
        return ""
    parts = s.split("-")
    if len(parts) >= 3:
        tail = parts[-1]
        if 1 <= len(tail) <= 4 and all(c.isalnum() for c in tail):
            return "-".join(parts[:-1])
    return s


def _safe_kb_path(relative_path: str) -> Path | None:
    """Resolve ``relative_path`` under :data:`KB_ROOT` or return ``None``.

    Returning ``None`` (rather than raising) lets the tool layer translate
    traversal attempts into a clean error dict for the agent.
    """
    if not relative_path:
        return None
    try:
        candidate = (KB_ROOT / relative_path).resolve()
        candidate.relative_to(KB_ROOT)
    except (ValueError, OSError):
        return None
    return candidate


def kb_read(path: str, max_chars: int = 24000) -> dict[str, Any]:
    """Read a text file under ``KNOWLEDGE_BASE/``.

    Returns ``{"path", "content", "truncated", "total_chars"}`` or
    ``{"error": "..."}``. Output is truncated to ``max_chars`` (default
    24k) to keep the agent's context window in check.
    """
    target = _safe_kb_path(path)
    if target is None:
        return {"error": f"path escapes KB root: {path!r}"}
    if not target.exists():
        return {"error": f"file not found: {path!r}"}
    if not target.is_file():
        return {"error": f"not a file: {path!r}"}
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"read failed: {exc}"}
    cap = max(512, int(max_chars))
    truncated = len(raw) > cap
    return {
        "path": path,
        "content": raw[:cap],
        "truncated": truncated,
        "total_chars": len(raw),
        "citation_hint": citation_hint_for_kb(path),
    }


# Coarse family bucket per MATERIALS key — used for analogue scoring.
_KEY_TO_FAMILY: dict[str, str] = {
    "6061-T6":   "aluminum",
    "7075-T6":   "aluminum",
    "2024-T3":   "aluminum",
    "1018":      "steel",
    "4140":      "steel",
    "304_ss":    "stainless",
    "316_ss":    "stainless",
    "C360":      "brass",
    "Ti-6Al-4V": "titanium",
    "PEEK":      "peek",
    "Acetal":    "acetal",
    "Nylon":     "nylon",
    "PVC":       "pvc",
    "CPVC":      "cpvc",
    "PET":       "pet",
    "UHMW":      "uhmw",
    "HDPE":      "hdpe",
    "Semitron":  "semitron",
    "Silicone":  "silicone",
}


def _material_family(material: str) -> str:
    """Bucket free-text material into a coarse family used for analogue scoring.

    Delegates to :func:`server.infra.materials.match_material` so case-
    insensitive substring matching (e.g. ``"AL 6061"`` → 6061-T6) and the
    family-keyword hints (e.g. ``"303 Stainless"`` → 304_ss) are reused.
    """
    if not (material or "").strip():
        return "unknown"
    matched = match_material(material)
    if matched is DEFAULT_MATERIAL:
        return "unknown"
    for key, row in MATERIALS.items():
        if row is matched:
            return _KEY_TO_FAMILY.get(key, key.lower())
    return "unknown"


# Fuzzy-score thresholds that classify how close an analogue is. The
# agent uses the tier to decide copy-verbatim vs reason-and-scale:
#   exact  — same part identity (injected by make_self_aware_find_analogues)
#   strong — material + part_type + complexity all match (≥ 8 / 10)
#   weak   — looser family cousin; reason from it, don't copy blindly
_TIER_STRONG_FLOOR = 8.0
_EXACT_MATCH_SCORE = 100.0


def _score_to_tier(score: float) -> str:
    """Map a fuzzy analogue score to a copy/reason match-quality tier."""
    if score >= _EXACT_MATCH_SCORE:
        return "exact"
    if score >= _TIER_STRONG_FLOOR:
        return "strong"
    return "weak"


def kb_find_analogues(
    part_type: str,
    material: str,
    n_features: int | None = None,
    complexity: str | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """Rank analogue parts from ``extracted/parts.csv``.

    Scoring (higher = closer):
      * material family match  → +3
      * part_type match        → +3
      * complexity match       → +2
      * n_features within ±2   → +2 graded by distance
    Rows scoring 0 are dropped.

    Each returned analogue carries a ``match_tier`` (``strong`` / ``weak``)
    derived from its score. When the in-flight part itself exists in the
    corpus, :func:`make_self_aware_find_analogues` injects it at rank 1 with
    ``match_tier="exact"`` so the agent copies the known part verbatim
    instead of re-deriving it from a looser cousin.
    """
    parts_csv = _safe_kb_path("extracted/parts.csv")
    if parts_csv is None or not parts_csv.exists():
        return {"error": "extracted/parts.csv not found under KB_ROOT"}

    target_fam = _material_family(material)
    target_pt = (part_type or "").lower().strip()
    target_cx = (complexity or "").lower().strip()

    scored: list[tuple[float, dict]] = []
    try:
        with parts_csv.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                score = 0.0
                row_fam = _material_family(row.get("material", ""))
                if row_fam != "unknown" and row_fam == target_fam:
                    score += 3.0
                row_pt = (row.get("part_type", "") or "").lower().strip()
                if row_pt and target_pt and row_pt == target_pt:
                    score += 3.0
                row_cx = (row.get("class", "") or "").lower().strip()
                if row_cx and target_cx and row_cx == target_cx:
                    score += 2.0
                if n_features is not None:
                    try:
                        delta = abs(int(row.get("n_features", "") or 0) - int(n_features))
                        if delta <= 2:
                            score += 2.0 - (delta * 0.5)
                    except (TypeError, ValueError):
                        pass
                if score > 0:
                    scored.append((score, row))
    except OSError as exc:
        return {"error": f"parts.csv read failed: {exc}"}

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: max(1, int(top_k))]
    analogues_out: list[dict] = []
    for s, r in top:
        pn = (r.get("part_number") or "").strip()
        # Each analogue carries TWO hints — the CSV row it came from AND
        # the parts/<pn>.md page that has its measured tools/params.
        hints = ["csv:extracted/parts.csv"]
        if pn:
            hints.append(citation_hint_for_kb(f"parts/{pn}.md"))
        analogues_out.append({
            "score": round(s, 2),
            "match_tier": _score_to_tier(s),
            **r,
            "citation_hints": hints,
        })
    return {
        "query": {
            "part_type": part_type,
            "material": material,
            "material_family": target_fam,
            "n_features": n_features,
            "complexity": complexity,
        },
        "analogues": analogues_out,
        "total_scored": len(scored),
        "citation_hint": "csv:extracted/parts.csv",
    }


_ALLOWED_CSV_SUBDIRS = ("extracted",)


def _filter_row(row: dict, filters: dict) -> bool:
    """Apply per-column predicate dict to one CSV row."""
    for col, spec in filters.items():
        cell = row.get(col, "")
        if isinstance(spec, dict):
            if "eq" in spec and str(cell) != str(spec["eq"]):
                return False
            if "contains" in spec and str(spec["contains"]).lower() not in str(cell).lower():
                return False
            if "min" in spec:
                try:
                    if float(cell) < float(spec["min"]):
                        return False
                except (TypeError, ValueError):
                    return False
            if "max" in spec:
                try:
                    if float(cell) > float(spec["max"]):
                        return False
                except (TypeError, ValueError):
                    return False
        else:
            if str(cell).lower() != str(spec).lower():
                return False
    return True


def kb_query_csv(file: str, filters: dict | None = None, limit: int = 50) -> dict[str, Any]:
    """Filter rows from a KB CSV under ``extracted/``.

    ``filters`` is either ``{col: value}`` (case-insensitive exact match)
    or ``{col: {eq|contains|min|max: value}}`` for richer predicates.
    """
    target = _safe_kb_path(file)
    if target is None or not target.exists():
        return {"error": f"file not found: {file!r}"}
    try:
        rel_parts = target.relative_to(KB_ROOT).parts
    except ValueError:
        return {"error": f"file escapes KB root: {file!r}"}
    if not rel_parts or rel_parts[0] not in _ALLOWED_CSV_SUBDIRS:
        return {"error": f"kb_query_csv only allowed under {_ALLOWED_CSV_SUBDIRS}"}

    filters = filters or {}
    cap = max(1, int(limit))
    rows: list[dict] = []
    try:
        with target.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for source_idx, row in enumerate(csv.DictReader(fh)):
                if _filter_row(row, filters):
                    rows.append({
                        **row,
                        "_row_index": source_idx,
                        "citation_hint": citation_hint_for_csv(file, source_idx),
                    })
                    if len(rows) >= cap:
                        break
    except OSError as exc:
        return {"error": f"csv read failed: {exc}"}
    return {
        "file": file,
        "filters": filters,
        "rows": rows,
        "count": len(rows),
        "citation_hint": citation_hint_for_csv(file),
    }


def make_holdout_aware_kb_tools(
    holdout_part_number: str | None,
) -> dict[str, Any]:
    """Return holdout-filtered versions of kb_read / kb_find_analogues /
    kb_query_csv.

    When ``holdout_part_number`` is set (typically by the eval harness via
    ``A4_EVAL_HOLDOUT_PART_NUMBER`` or the agent dispatcher), the wrapped
    tools refuse to return the in-flight part's own KB entries so the
    evaluation actually measures generalization rather than recall on the
    answer key.

    Matching uses :func:`normalize_part_id` so ``"839-323453"`` and
    ``"839-323453-001"`` are treated as the same part.

    When ``holdout_part_number`` is empty / None, returns the plain tools
    unchanged — production behavior.
    """
    holdout = normalize_part_id(holdout_part_number or "")
    if not holdout:
        return {
            "kb_read": kb_read,
            "kb_find_analogues": kb_find_analogues,
            "kb_query_csv": kb_query_csv,
        }

    def _matches_holdout(pn: str) -> bool:
        return normalize_part_id(pn) == holdout

    def _path_targets_holdout(path: str) -> bool:
        normalized = (path or "").replace("\\", "/").strip().lower()
        for prefix in ("parts/", "parts/_shards/"):
            if normalized.startswith(prefix):
                tail = normalized[len(prefix):].rsplit("/", 1)[-1]
                if tail.endswith(".md"):
                    tail = tail[:-3]
                if normalize_part_id(tail) == holdout:
                    return True
        return False

    def _holdout_kb_read(path: str, max_chars: int = 24000) -> dict[str, Any]:
        if _path_targets_holdout(path):
            return {
                "error": (
                    f"holdout: {path!r} maps to in-flight test fixture "
                    f"{holdout!r} — refusing to leak the answer key. "
                    f"Use kb_find_analogues to discover OTHER analogues."
                ),
                "holdout_part_number": holdout,
            }
        return kb_read(path, max_chars)

    def _holdout_kb_find_analogues(
        part_type: str,
        material: str,
        n_features: int | None = None,
        complexity: str | None = None,
        top_k: int = 3,
    ) -> dict[str, Any]:
        bumped = max(1, int(top_k or 3))
        # Over-fetch by a small margin so we can drop the holdout row and
        # still return the caller's requested top_k.
        raw = kb_find_analogues(part_type, material, n_features, complexity,
                                top_k=bumped + 4)
        if "error" in raw:
            return raw
        filtered: list[dict] = []
        dropped = 0
        for a in raw.get("analogues") or []:
            if _matches_holdout(a.get("part_number") or ""):
                dropped += 1
                continue
            filtered.append(a)
            if len(filtered) >= bumped:
                break
        raw["analogues"] = filtered
        if dropped:
            raw["holdout_filtered"] = {
                "holdout_part_number": holdout,
                "dropped": dropped,
            }
        return raw

    def _holdout_kb_query_csv(
        file: str,
        filters: dict | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        bumped = max(1, int(limit or 50))
        raw = kb_query_csv(file, filters, bumped + 25)
        if "error" in raw:
            return raw
        filtered: list[dict] = []
        dropped = 0
        for row in raw.get("rows") or []:
            if _matches_holdout(row.get("part_number") or ""):
                dropped += 1
                continue
            filtered.append(row)
            if len(filtered) >= bumped:
                break
        raw["rows"] = filtered
        raw["count"] = len(filtered)
        if dropped:
            raw["holdout_filtered"] = {
                "holdout_part_number": holdout,
                "dropped": dropped,
            }
        return raw

    return {
        "kb_read": _holdout_kb_read,
        "kb_find_analogues": _holdout_kb_find_analogues,
        "kb_query_csv": _holdout_kb_query_csv,
    }


def _lookup_part_row(part_number: str) -> dict | None:
    """Fetch a single ``parts.csv`` row by (normalized) part_number.

    Independent of the fuzzy scorer — used to surface the in-flight part's
    OWN row even when its thin 3D feature signature would have ranked a
    simpler cousin higher. Returns the raw CSV row dict or ``None``.
    """
    target = normalize_part_id(part_number or "")
    if not target:
        return None
    parts_csv = _safe_kb_path("extracted/parts.csv")
    if parts_csv is None or not parts_csv.exists():
        return None
    try:
        with parts_csv.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                if normalize_part_id(row.get("part_number") or "") == target:
                    return row
    except OSError:
        return None
    return None


def make_self_aware_find_analogues(
    inner_find_analogues: Any,
    self_part_number: str | None,
) -> Any:
    """Wrap a ``kb_find_analogues`` fn so the in-flight part's OWN page,
    when it exists in the corpus, is surfaced at rank 1 as an ``exact``
    match — implementing the "copy a known part verbatim" branch.

    The fuzzy scorer builds its query from a thin 3D feature signature
    (material / part_type / n_features), which frequently ranks a simpler
    cousin above the part's own (richer) page. This wrapper bypasses that:
    it looks the self part up by identity and prepends it with
    ``match_tier="exact"`` and a dominant score, plus a top-level
    ``exact_match`` directive telling the agent to adopt it verbatim.

    ``self_part_number`` MUST be ``None`` in holdout/eval mode (the harness
    is deliberately measuring generalization, so the part's own answer key
    must stay hidden). Production runs pass the real in-flight part number.
    """
    self_id = normalize_part_id(self_part_number or "")
    if not self_id:
        return inner_find_analogues

    def _self_aware(
        part_type: str,
        material: str,
        n_features: int | None = None,
        complexity: str | None = None,
        top_k: int = 3,
    ) -> dict[str, Any]:
        raw = inner_find_analogues(part_type, material, n_features,
                                   complexity, top_k)
        if not isinstance(raw, dict) or "error" in raw:
            return raw
        row = _lookup_part_row(self_part_number)
        if row is None:
            return raw  # novel part — not in KB; reason/scale branch
        pn = (row.get("part_number") or "").strip()
        hints = ["csv:extracted/parts.csv"]
        if pn:
            hints.append(citation_hint_for_kb(f"parts/{pn}.md"))
        exact = {
            "score": _EXACT_MATCH_SCORE,
            "match_tier": "exact",
            **row,
            "citation_hints": hints,
        }
        # Drop any fuzzy duplicate of the self row, then prepend exact at #1.
        rest = [
            a for a in (raw.get("analogues") or [])
            if normalize_part_id(a.get("part_number") or "") != self_id
        ]
        raw["analogues"] = [exact] + rest
        raw["exact_match"] = {
            "part_number": pn,
            "directive": (
                f"This part ({pn}) ALREADY EXISTS in the KB. Call "
                f"kb_adopt_routing(part_number='{pn}') and emit that routing "
                f"VERBATIM — copy every op and run_min_per_part exactly. Do "
                f"NOT rescale, do NOT add ops (not even a final-inspection "
                f"block — take it from the adopted routing), do NOT drop ops."
            ),
        }
        return raw

    return _self_aware


KB_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "kb_read",
            "description": (
                "Read a markdown/text file from KNOWLEDGE_BASE/. "
                "Use for AGENT.md, patterns/*.md, parts/INDEX.md, methodology/*.md."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path under KNOWLEDGE_BASE, e.g. 'patterns/cycle_time_model.md'.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Truncate output after this many characters (default 24000).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_find_analogues",
            "description": (
                "Rank analogue parts from extracted/parts.csv by material family, "
                "part_type, complexity, and n_features distance. Each hit carries "
                "a 'match_tier': 'exact' (this part itself already exists in the "
                "KB — the result also has a top-level 'exact_match' directive; "
                "adopt it and copy VERBATIM), 'strong' (score >= 8; adopt and "
                "copy verbatim), or 'weak' (looser cousin; reason/scale from it)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "part_type": {"type": "string"},
                    "material": {"type": "string"},
                    "n_features": {"type": "integer"},
                    "complexity": {"type": "string", "description": "'Simple' or 'Complex'."},
                    "top_k": {"type": "integer", "description": "Default 3."},
                },
                "required": ["part_type", "material"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_query_csv",
            "description": (
                "Filter rows in a KNOWLEDGE_BASE/extracted/*.csv. "
                "Filters are {col: value} or {col: {eq|contains|min|max: value}}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "e.g. 'extracted/operations.csv', 'extracted/tools.csv', 'extracted/jobcost.csv'.",
                    },
                    "filters": {"type": "object"},
                    "limit": {"type": "integer", "description": "Default 50."},
                },
                "required": ["file"],
            },
        },
    },
]
