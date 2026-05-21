"""Customer-raw → RAG-ready: load the KB into one dict per part_number.

Joins three CSVs (``parts.csv``, ``operations.csv``, ``jobcost.csv``) and
the per-part markdown page so the descriptor builder has everything in
one place.

Why a separate loader
---------------------
The agentic engine reads CSVs ad-hoc through :func:`kb_query_csv` and
:func:`kb_find_analogues` (see ``server/engines/agentic/tools/kb.py``).
The RAG ingestion only runs offline, so it joins everything up-front
into a denormalized record per part. That record gets turned into the
embedded descriptor and dumped into ``rag_part_embeddings.metadata`` for
the retriever to hand back at query time.

This file has zero coupling to the agentic engine. It only depends on
the KB filesystem layout under ``KNOWLEDGE_BASE/``.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("cncserver.engines.rag.ingestion.parts_loader")

# parts_loader.py → ingestion → rag → engines → server → repo
_REPO_ROOT = Path(__file__).resolve().parents[4]
KB_ROOT = (_REPO_ROOT / "KNOWLEDGE_BASE").resolve()

PARTS_CSV     = KB_ROOT / "extracted" / "parts.csv"
OPS_CSV       = KB_ROOT / "extracted" / "operations.csv"
JOBCOST_CSV   = KB_ROOT / "extracted" / "jobcost.csv"
PARTS_MD_DIR  = KB_ROOT / "parts"
PATTERNS_DIR  = KB_ROOT / "patterns"


# ---------------------------------------------------------------------------
# Material family normalization
# ---------------------------------------------------------------------------

_FAMILY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("aluminum", "aluminium", "al6061", "al 6061", "6061", "7075", "2024"), "aluminum"),
    (("stainless", "304", "316", "303"),                                      "stainless"),
    (("4140", "1018", "steel", "a36", "a572"),                                "steel"),
    (("brass", "c360", "c260", "naval"),                                      "brass"),
    (("ti-6al", "titanium"),                                                  "titanium"),
    (("peek",),                                                               "peek"),
    (("acetal", "delrin", "pom"),                                             "acetal"),
    (("nylon", "pa6", "pa66"),                                                "nylon"),
    (("cpvc",),                                                               "cpvc"),
    (("pvc",),                                                                "pvc"),
    (("petg", "pet"),                                                         "pet"),
    (("uhmw",),                                                               "uhmw"),
    (("hdpe",),                                                               "hdpe"),
    (("semitron", "esd"),                                                     "semitron"),
    (("silicone",),                                                           "silicone"),
    (("polycarbonate", "pc "),                                                "polycarbonate"),
    (("npp", "polypropylene", "pp "),                                         "polypropylene"),
    (("ptfe", "teflon"),                                                      "ptfe"),
)


def material_family(material: str | None) -> str:
    """Bucket free-text material into a coarse family used as a hard filter."""
    if not material:
        return "unknown"
    s = material.lower()
    for hints, fam in _FAMILY_HINTS:
        for h in hints:
            if h in s:
                return fam
    return "unknown"


# ---------------------------------------------------------------------------
# Per-part record
# ---------------------------------------------------------------------------

@dataclass
class PartRecord:
    """Everything we know about one analogue part, denormalized.

    Built by :func:`load_all_parts`; consumed by
    :func:`server.engines.rag.ingestion.descriptors.build_descriptor`.
    """

    part_number: str
    rev: str = ""
    parts_row: dict = field(default_factory=dict)
    operations: list[dict] = field(default_factory=list)
    jobcost: list[dict] = field(default_factory=list)
    markdown: str = ""
    md_path: str | None = None

    # Derived fields (filled in by ``_finalize``)
    material: str = ""
    material_family: str = ""
    part_type: str = ""
    complexity_class: str = ""
    envelope_mm: str = ""
    bbox_volume_mm3: float | None = None
    stock_form: str = ""
    n_features: int | None = None
    n_ops: int | None = None
    n_tools: int | None = None
    total_run_min_pc: float | None = None
    total_setup_hr: float | None = None
    cost_ea_act: float | None = None
    unit_price: float | None = None
    currency: str = "RM"

    def to_metadata(self) -> dict[str, Any]:
        """Pack into a JSON-safe dict for rag_part_embeddings.metadata."""
        return {
            "parts_row": self.parts_row,
            "operations": self.operations,
            "jobcost": self.jobcost,
            "md_path": self.md_path,
        }


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        logger.warning("CSV missing: %s", path)
        return []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


def _to_float(value: Any) -> float | None:
    """Best-effort numeric coercion. Returns ``None`` for empty/garbage cells."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # The KB sometimes uses '~10' or '<5' as approximations; strip the prefix.
    s = re.sub(r"^[~<>≈]+", "", s)
    s = s.replace(",", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    if f is None:
        return None
    return int(f)


# ---------------------------------------------------------------------------
# Currency inference
# ---------------------------------------------------------------------------

_USD_PART_PREFIXES = ("0022-", "0023-")  # COFAB customer = USD per KB note


def _infer_currency(part_number: str, source_folder: str = "") -> str:
    if any(part_number.startswith(p) for p in _USD_PART_PREFIXES):
        return "USD"
    if "COFAB" in (source_folder or "").upper():
        return "USD"
    return "RM"


# ---------------------------------------------------------------------------
# Markdown extraction
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(##+)\s+(.+?)\s*$", re.MULTILINE)


def extract_md_section(md_text: str, heading_substr: str, max_chars: int = 1200) -> str:
    """Pull the body under the first H2/H3 whose title contains ``heading_substr``.

    Stops at the next heading of the same or higher level. Used to copy
    the "Analogue notes" or "Identity" blocks from a part page into the
    embedded descriptor.
    """
    if not md_text:
        return ""
    needle = heading_substr.lower()
    matches = list(_HEADING_RE.finditer(md_text))
    for i, m in enumerate(matches):
        title = m.group(2).lower()
        if needle in title:
            start = m.end()
            level = len(m.group(1))
            end = len(md_text)
            for n in matches[i + 1:]:
                if len(n.group(1)) <= level:
                    end = n.start()
                    break
            chunk = md_text[start:end].strip()
            return chunk[:max_chars]
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all_parts() -> list[PartRecord]:
    """Build one PartRecord per part_number found in parts.csv.

    Operations + jobcost rows are bucketed by ``part_number`` and attached.
    The per-part markdown page (when it exists) is read verbatim and the
    "Analogue notes" / "Identity" sections are extracted into the descriptor
    pipeline by ``descriptors.build_descriptor``.
    """
    parts_rows = _read_csv(PARTS_CSV)
    ops_rows   = _read_csv(OPS_CSV)
    job_rows   = _read_csv(JOBCOST_CSV)

    ops_by_pn: dict[str, list[dict]] = {}
    for row in ops_rows:
        pn = (row.get("part_number") or "").strip()
        if pn:
            ops_by_pn.setdefault(pn, []).append(row)

    job_by_pn: dict[str, list[dict]] = {}
    for row in job_rows:
        pn = (row.get("part_number") or "").strip()
        if pn:
            job_by_pn.setdefault(pn, []).append(row)

    records: list[PartRecord] = []
    for row in parts_rows:
        pn = (row.get("part_number") or "").strip()
        if not pn:
            continue
        md_path = PARTS_MD_DIR / f"{pn}.md"
        md_text = ""
        md_rel: str | None = None
        if md_path.exists():
            try:
                md_text = md_path.read_text(encoding="utf-8", errors="replace")
                md_rel = f"parts/{pn}.md"
            except OSError as exc:
                logger.warning("md read failed for %s: %s", pn, exc)

        record = PartRecord(
            part_number=pn,
            rev=(row.get("rev") or "").strip(),
            parts_row=dict(row),
            operations=ops_by_pn.get(pn, []),
            jobcost=job_by_pn.get(pn, []),
            markdown=md_text,
            md_path=md_rel,
        )
        _finalize(record)
        records.append(record)
    logger.info("load_all_parts: %d part records loaded", len(records))
    return records


def _finalize(record: PartRecord) -> None:
    """Populate the structural fields used as pgvector columns."""
    row = record.parts_row
    record.material         = (row.get("material") or "").strip()
    record.material_family  = material_family(record.material)
    record.part_type        = (row.get("part_type") or "").strip()
    record.complexity_class = (row.get("class") or "").strip()
    record.envelope_mm      = (row.get("envelope_mm") or "").strip()
    record.stock_form       = (row.get("stock_form") or "").strip()
    record.n_features       = _to_int(row.get("n_features"))
    record.n_ops            = _to_int(row.get("n_ops"))
    record.n_tools          = _to_int(row.get("n_tools"))
    record.total_run_min_pc = _to_float(row.get("total_run_min_pc"))
    record.total_setup_hr   = _to_float(row.get("total_setup_hr"))
    record.cost_ea_act      = _to_float(row.get("cost_ea_rm_act"))
    record.unit_price       = _to_float(row.get("unit_price_rm"))
    record.currency         = _infer_currency(record.part_number, row.get("source_folder", ""))

    # Best-effort envelope volume — parses "~184x63x51" style strings.
    env_volume = _parse_envelope_volume(record.envelope_mm)
    if env_volume is not None:
        record.bbox_volume_mm3 = env_volume


_ENVELOPE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)"
)


def _parse_envelope_volume(envelope_mm: str) -> float | None:
    """Parse '~184x63x51' / '155x19x19' / 'Ø19x34.5' → volume in mm³.

    The KB envelope column is free-form; this is a best-effort regex pull.
    Returns ``None`` if no triple is found.
    """
    if not envelope_mm:
        return None
    m = _ENVELOPE_RE.search(envelope_mm)
    if not m:
        # Try Ø-prefixed cylinder pattern: "Ø19 x 34.5"
        cyl = re.search(r"Ø\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", envelope_mm)
        if cyl:
            d = float(cyl.group(1))
            L = float(cyl.group(2))
            import math
            return math.pi * (d / 2.0) ** 2 * L
        return None
    a, b, c = (float(m.group(i)) for i in (1, 2, 3))
    return a * b * c


# ---------------------------------------------------------------------------
# Pattern docs
# ---------------------------------------------------------------------------

@dataclass
class PatternChunk:
    kb_path: str
    section_heading: str
    chunk_order: int
    content: str


def load_pattern_chunks(max_chunk_chars: int = 3000) -> list[PatternChunk]:
    """Walk KNOWLEDGE_BASE/patterns/ and chunk each MD by H2.

    Each chunk is at most ``max_chunk_chars``; oversize sections are split
    on paragraph boundaries.
    """
    if not PATTERNS_DIR.exists():
        return []
    chunks: list[PatternChunk] = []
    for md_path in sorted(PATTERNS_DIR.glob("*.md")):
        rel = f"patterns/{md_path.name}"
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        sections = _split_md_by_h2(text)
        order = 0
        for heading, body in sections:
            if not body.strip():
                continue
            for sub in _wrap_paragraphs(body, max_chunk_chars):
                chunks.append(PatternChunk(
                    kb_path=rel, section_heading=heading,
                    chunk_order=order, content=sub,
                ))
                order += 1
    logger.info("load_pattern_chunks: %d chunks from %s", len(chunks), PATTERNS_DIR)
    return chunks


def _split_md_by_h2(text: str) -> list[tuple[str, str]]:
    """Split a markdown doc into (heading, body) pairs at H2 boundaries.

    Content before the first H2 is bucketed under a synthetic "preamble"
    heading so we don't lose it.
    """
    parts: list[tuple[str, str]] = []
    current_h = "preamble"
    current_body: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current_body or current_h != "preamble":
                parts.append((current_h, "\n".join(current_body).strip()))
            current_h = m.group(1).strip()
            current_body = []
        else:
            current_body.append(line)
    parts.append((current_h, "\n".join(current_body).strip()))
    return parts


def _wrap_paragraphs(body: str, max_chars: int) -> list[str]:
    """Split a body into <= max_chars sub-chunks on paragraph boundaries."""
    if len(body) <= max_chars:
        return [body]
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", body):
        if size + len(para) + 2 > max_chars and buf:
            out.append("\n\n".join(buf).strip())
            buf, size = [], 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        out.append("\n\n".join(buf).strip())
    return out


__all__ = [
    "KB_ROOT",
    "PartRecord",
    "PatternChunk",
    "material_family",
    "extract_md_section",
    "load_all_parts",
    "load_pattern_chunks",
]
