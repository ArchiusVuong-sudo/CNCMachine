"""Citation grammar + validator for the agentic engine.

Every numeric or routing claim the agent emits must be backed by a
citation token. The grammar is intentionally minimal so the model can
emit it verbatim from whatever tool result it consulted:

  * ``kb:<relative-path>``        — file read via ``kb_read`` (always
                                    relative to ``KNOWLEDGE_BASE/``)
  * ``csv:<file>[#row=N]``        — row from ``kb_query_csv`` /
                                    ``kb_find_analogues``
  * ``raw:<path>[#L<line>]``      — raw customer file under the raw-data
                                    roots (NC programs, source text)
  * ``pdf:<path>#page=N``         — page reference inside a drawing PDF
  * ``xls:<path>#sheet=<...>``    — spreadsheet cell / range
  * ``catalog:<table>/<id>``      — row id returned by ``catalog_lookup``

Why a regex grammar instead of structured fields? The agent emits JSON
turn-by-turn under tight token budgets; a string token is cheaper and
survives schema drift. The tool layer attaches ``citation_hint`` blobs
to every result so the model can copy them verbatim — no string-building
required on its side.

Validators here are advisory at call-time and **enforced** post-final by
``tool_loop.run_tool_loop``: the loop refuses to return a ``final``
payload whose evidence list is empty or whose tokens don't match the
grammar.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote as _urlquote

# Public so other modules can extend (e.g. raw_file tool adding 'pdf').
SCHEMES: tuple[str, ...] = ("kb", "csv", "raw", "pdf", "xls", "catalog")

_SCHEMES_ALT = "|".join(SCHEMES)

# Characters allowed in the body of a citation token. Excludes ASCII
# punctuation that commonly trails a token in prose (",", ";", ")", "]",
# "}", quotes) so the scraper doesn't grab them. Includes:
#   "!" for Excel sheet refs like `xls:foo.xlsx#sheet=OP30!A12`
#   "\" for Windows raw paths
#   "%" for percent-encoded path chars (raw/pdf/xls hints percent-encode
#       customer paths so spaces / parens / commas don't break the grammar)
_TOKEN_BODY_CHARS = r"\w./#=!%\\\-+"

# Anchored — validate a single evidence token. Strict but allows the
# punctuation we care about; rejects whitespace, commas, etc.
EVIDENCE_TOKEN_RE = re.compile(
    rf"^({_SCHEMES_ALT}):[{_TOKEN_BODY_CHARS}]+$",
    re.IGNORECASE,
)

# Unanchored — scrape citations out of free-text rationale.
# (?<![A-Za-z0-9]) prevents matching the tail of an unrelated word.
INLINE_CITATION_RE = re.compile(
    rf"(?<![A-Za-z0-9])({_SCHEMES_ALT}):[{_TOKEN_BODY_CHARS}]+",
    re.IGNORECASE,
)

CITATION_GRAMMAR_SUMMARY = """\
## Citation grammar (mandatory)

Every `final` payload MUST include a non-empty `evidence` array whose
entries are citation tokens drawn from this grammar:

  - `kb:<path>`                  e.g. `kb:patterns/cutting_parameters.md`
  - `csv:<file>[#row=N]`         e.g. `csv:extracted/tools.csv#row=12`
  - `raw:<path>[#L<n>]`          e.g. `raw:OneDrive_/PROG/OP30.NC#L120`
  - `pdf:<path>#page=N`          e.g. `pdf:OneDrive_/drawing.pdf#page=2`
  - `xls:<path>#sheet=<name>`    e.g. `xls:OneDrive_/jobcost.xlsx#sheet=OP30!A12`
  - `catalog:<table>/<id>`       e.g. `catalog:machines/M-CNCV-FAN`

Rules:
1. Use tokens VERBATIM from tool results — every tool result carries a
   `citation_hint` field; copy it into `evidence` rather than building
   strings yourself.
2. Every numeric output (rates, dims, times, machine pick) needs at
   least one supporting token in `evidence` AND must reference it inside
   `rationale` (e.g. "...feed band per kb:patterns/cutting_parameters.md").
3. If you cite raw customer data (NC text, drawing PDF, spreadsheet),
   the token MUST point at the specific file — never a generic "raw".
4. Empty `evidence` will be rejected; the loop will ask you to retry."""


def extract_citations(text: str) -> list[str]:
    """Scrape citation tokens out of free-text (rationale, thought, etc.).

    Order-preserving, de-duped. Used both for validation and so the
    coordinator can roll an audit list up to the assembly.
    """
    if not isinstance(text, str) or not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in INLINE_CITATION_RE.finditer(text):
        token = match.group(0)
        key = token.lower()
        if key not in seen:
            seen.add(key)
            out.append(token)
    return out


def is_valid_token(token: Any) -> bool:
    """Single-token grammar check. Non-strings always fail."""
    if not isinstance(token, str):
        return False
    return bool(EVIDENCE_TOKEN_RE.match(token.strip()))


def validate_evidence_list(evidence: Any) -> tuple[bool, str | None]:
    """Validate a ``final.evidence`` field.

    Returns
    -------
    ``(True, None)`` if every entry is a well-formed citation token.
    ``(False, <reason>)`` otherwise — the reason is bubbled back to the
    model verbatim so it can correct itself on retry.
    """
    if evidence is None:
        return False, "missing `evidence` array - every final must cite >=1 source"
    if not isinstance(evidence, list):
        return False, f"`evidence` must be an array, got {type(evidence).__name__}"
    if not evidence:
        return False, "empty `evidence` array - cite >=1 source from kb/csv/raw/pdf/xls/catalog"
    bad: list[str] = []
    for i, tok in enumerate(evidence):
        if not is_valid_token(tok):
            bad.append(f"[{i}]={tok!r}")
    if bad:
        return False, (
            "invalid citation token(s): " + ", ".join(bad)
            + f". Allowed schemes: {SCHEMES}. Example: 'kb:patterns/cutting_parameters.md'."
        )
    return True, None


def validate_final_output(
    final: Any,
    *,
    require_rationale: bool = True,
) -> tuple[bool, str | None]:
    """Validate the shape of a phase ``final`` payload.

    Enforces:
      * ``final`` is a dict.
      * ``evidence`` is a non-empty list of well-formed tokens.
      * ``rationale`` is a non-empty string (unless ``require_rationale=False``).
      * Numeric-bearing payloads (``final`` containing ``top_machines``,
        ``operations``, ``tools_per_operation``, ``parameters_per_operation``,
        or ``total_run_min_per_part``) cite at least one token relevant
        to that payload type — we leave that semantic check to the prompt
        plus the inline scrape; here we only enforce the structural rules.
    """
    if not isinstance(final, dict):
        return False, f"`final` must be an object, got {type(final).__name__}"

    if require_rationale:
        rationale = final.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            return False, "missing `rationale` - write 2-4 sentences referencing your evidence tokens"

    ok, err = validate_evidence_list(final.get("evidence"))
    if not ok:
        return False, err

    return True, None


def citation_hint_for_kb(rel_path: str) -> str:
    """Build a ``kb:`` token from a KB-relative path."""
    return f"kb:{rel_path.lstrip('/').replace(chr(92), '/')}"


def citation_hint_for_csv(rel_path: str, row_index: int | None = None) -> str:
    """Build a ``csv:`` token, optionally pinning a 0-based row index."""
    base = f"csv:{rel_path.lstrip('/').replace(chr(92), '/')}"
    if row_index is None:
        return base
    return f"{base}#row={int(row_index)}"


def citation_hint_for_catalog(table: str, row_id: str | None) -> str:
    """Build a ``catalog:`` token. Falls back to ``catalog:<table>`` if id missing."""
    table = (table or "").strip() or "unknown"
    if not row_id:
        return f"catalog:{table}"
    return f"catalog:{table}/{row_id}"


def _percent_encode_path(rel_path: str) -> str:
    """URL-encode a customer-file path so it survives the citation grammar.

    Real raw paths (OneDrive dumps) contain spaces, parens, commas, square
    brackets — none of which are in :data:`EVIDENCE_TOKEN_RE`. Encoding to
    percent-form keeps `/`, `.`, `-` readable while making the rest of the
    path token-safe. The model copies the encoded form verbatim from
    ``citation_hint`` so it never has to handle escaping itself.
    """
    norm = (rel_path or "").lstrip("/").replace(chr(92), "/")
    return _urlquote(norm, safe="/.-_")


def citation_hint_for_raw(rel_path: str, *, line: int | None = None,
                          line_end: int | None = None) -> str:
    """Build a ``raw:`` token, optionally pinning a line or line window."""
    base = f"raw:{_percent_encode_path(rel_path)}"
    if line is None:
        return base
    if line_end is None or int(line_end) <= int(line):
        return f"{base}#L{int(line)}"
    return f"{base}#L{int(line)}-{int(line_end)}"


def citation_hint_for_pdf(rel_path: str, page: int) -> str:
    """Build a ``pdf:`` token pinning a 1-based page."""
    return f"pdf:{_percent_encode_path(rel_path)}#page={int(page)}"


def citation_hint_for_xls(rel_path: str, sheet: str) -> str:
    """Build an ``xls:`` token pinning a sheet name. Sheet is percent-encoded."""
    sheet_enc = _urlquote((sheet or ""), safe="!.-_")
    return f"xls:{_percent_encode_path(rel_path)}#sheet={sheet_enc}"


__all__ = [
    "SCHEMES",
    "EVIDENCE_TOKEN_RE",
    "INLINE_CITATION_RE",
    "CITATION_GRAMMAR_SUMMARY",
    "extract_citations",
    "is_valid_token",
    "validate_evidence_list",
    "validate_final_output",
    "citation_hint_for_kb",
    "citation_hint_for_csv",
    "citation_hint_for_catalog",
    "citation_hint_for_raw",
    "citation_hint_for_pdf",
    "citation_hint_for_xls",
]
