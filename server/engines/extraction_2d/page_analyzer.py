"""Per-page VLM analysis: one base64 PNG → one parsed dict.

The page-level outcome (``"ok" | "soft_skip" | "hard_reject" | "unparseable"``)
drives the engine's retry policy. ``unparseable`` triggers a single retry
(default) before we give up on the page; the others fall through to the
merger immediately.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from ...core.settings import get_settings
from ...infra import llm
from .prompts import EXTRACTION_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger("cncserver.engines.extraction_2d.page_analyzer")

OnThinking = Callable[[str], Awaitable[None]] | None

_EMPTY_PAGE: dict = {
    "dimensions": [],
    "gdt":        [],
    "threads":    [],
    "material":   None,
    "notes":      [],
    "raw_model_output": "",
}


def classify(parsed: dict) -> str:
    """Bucket a parsed page into ok / soft_skip / hard_reject / unparseable."""
    if parsed.get("raw_model_output"):
        return "unparseable"
    if (parsed.get("dimensions") or []) or (parsed.get("threads") or []):
        return "ok"
    notes_str = " ".join(str(n).lower() for n in (parsed.get("notes") or []))
    if "not_a_drawing" in notes_str:
        return "hard_reject"
    return "soft_skip"


async def analyze_one_page(
    page_b64: str,
    *,
    on_thinking: OnThinking = None,
) -> tuple[dict, str]:
    """Run the VLM on one page; retry once on unparseable output.

    Returns ``(parsed_dict, outcome)``. Never raises — transport errors
    are captured into the parsed dict's ``raw_model_output`` field so the
    merger can skip them without disrupting the rest of the document.
    """
    retries = max(int(get_settings().extraction.per_page_retries), 0)
    parsed: dict = {**_EMPTY_PAGE}
    outcome: str = "unparseable"

    for attempt in range(retries + 1):
        try:
            result = await llm.vision_chat(
                page_b64,
                SYSTEM_PROMPT,
                EXTRACTION_PROMPT,
                on_thinking=on_thinking,
            )
            content = (result.get("content") or "").strip()
            if not content:
                parsed = {**_EMPTY_PAGE, "raw_model_output": "(empty)"}
                outcome = "unparseable"
            else:
                parsed = llm.parse_model_json(content)
                outcome = classify(parsed)
        except Exception as exc:
            logger.warning("VLM page attempt %d failed: %s", attempt, exc)
            parsed = {**_EMPTY_PAGE, "raw_model_output": str(exc)}
            outcome = "unparseable"

        if outcome != "unparseable":
            return parsed, outcome
        if attempt < retries:
            logger.info("page analyzer: retrying (attempt %d)", attempt + 1)

    return parsed, outcome
