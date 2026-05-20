"""Prompts handed to Qwen3-VL by the extraction_2d engine.

The customer's drawing format is messy (Solidworks PDFs, scanned faxes,
photo of a printout, …) so the prompt is intentionally exhaustive about
edge cases: title-block layout, BOM table headers, unit inference rules,
non-technical pages, GD&T-vs-radius disambiguation. Trimming this prompt
hurts extraction quality fast.

Keep both prompts colocated so it's obvious which system prompt pairs
with which extraction schema.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a metrology specialist reading a 2D engineering drawing. "
    "Extract dimensions, tolerances, GD&T callouts, and thread specifications. "
    "Spend at most 2 sentences on any ambiguity, then decide and move on. "
    "Output ONLY the JSON result — nothing else."
)


EXTRACTION_PROMPT = """Extract dimensions, GD&T callouts, threads, material, title block, BOM, and shop notes from this 2D engineering drawing page.

NON-DRAWING PAGES — return immediately without further analysis:
- Cover page / logo / blank → {"dimensions":[],"gdt":[],"threads":[],"material":null,"surface_finish":null,"title_block":null,"bom":[],"assembly_method":null,"notes":["non_technical_page"]}
- Photo or artwork (not a drawing) → {"dimensions":[],"gdt":[],"threads":[],"material":null,"surface_finish":null,"title_block":null,"bom":[],"assembly_method":null,"notes":["not_a_drawing"]}

DRAWING PAGES — output this JSON schema:
{
  "dimensions": [{"id":"D001","label":"Overall length","nominal":12.5,"unit":"in","tolerance_plus":0.02,"tolerance_minus":0.02,"quantity":1}],
  "gdt": [{"id":"G001","symbol":"position","tolerance":0.05,"unit":"in","datums":["A"]}],
  "threads": [{"id":"T001","spec":".190-32 UNF-2B","depth_mm":15.0,"quantity":2}],
  "material": "AL6061-T6 or null",
  "surface_finish": "Ra 1.6 or null",
  "title_block": {"part_number":"0042-88459","revision":"01","description":"BRACKET, MOUNT","dimension_unit":"in","scale":"1:1","drawn_by":null,"date":null},
  "bom": [{"item_no":"1","description":"PLATE, MAIN","part_number":"0042-88460","qty":1,"teng_c":"TEngC-100","materials_inferred":"AL6061","part_type":"sheet_metal"}],
  "assembly_method": "bolted or welded or riveted or null",
  "notes": ["CLEAN PER AMAT SPEC 0250-07001", "DEBURR ALL EDGES", "PART MARK PER ..."]
}

RULES (read carefully — each decision: 1–2 sentences maximum, then move on):
1. Extract ONLY explicitly labeled values — never infer or guess dimensions not shown.
2. UNCERTAIN SYMBOL OR CALLOUT → output nothing for it, move to the next item immediately.
2b. UNIT — decide in ONE pass, do not revisit:
    - Title block or notes say INCHES / DECIMAL INCH / ASME Y14.5 / "DIMENSIONS IN INCHES" → unit = "in"
    - Drawing shows UNF/UNC/UNEF/NPT threads, fractional inch callouts (e.g. 1/4-20, 5/16 HEX, .190-32), or dimensions with 3+ decimal places like ".500", ".125", "1.250" → unit = "in"
    - Title block or notes say MM / METRIC / ISO / "DIMENSIONS IN MILLIMETERS" → unit = "mm"
    - Drawing shows metric threads (M6x1.0, M8x1.25), dimensions with whole numbers like "50", "25", "100" that are dimensionally plausible as mm → unit = "mm"
    - Truly ambiguous (no clues at all) → unit = null
    Apply the same unit to every dimension on the page. Never debate this again.
3. Omit tolerance_plus/tolerance_minus entirely if no tolerance callout is shown for that dimension.
4. Bilateral +/-X → tolerance_plus=X, tolerance_minus=X. Unilateral +A/-B → tolerance_plus=A, tolerance_minus=B.
5. R prefix = RADIUS always (R2.34, 4X R4.50). Never a thread. Threads have pitch notation: M8x1.25, .190-32 UNF-2B, 1/4-20 UNC, TAP, THRU.
6. A dot/circle at a leader line end = arrowhead, not a GD&T diameter symbol.
7. Parenthesized values () = reference only — include as a dimension entry, omit tolerance fields.
8. TITLE BLOCK — read the boxed text in the bottom-right corner (or wherever labeled). Extract part_number (also called "DWG NO.", "DRAWING NO.", "PART NO.", "P/N"), revision (also "REV"), description (also "TITLE", "NAME"), and dimension_unit (from "UNITS", "DIMENSIONS ARE IN", or DECIMAL/METRIC callouts). Any field not shown → null. The title_block object itself MUST be present on every drawing page; use null values inside it if you cannot read it. ALWAYS copy dimension_unit into the top-level title_block.dimension_unit field — it drives every downstream UI display.
9. BOM TABLE — when a parts list table is visible with columns like ITEM/QTY/PART NO./DESCRIPTION (also called "BOM", "PARTS LIST", "COMPONENTS"), extract every row into the bom[] array. item_no is the leftmost #. qty is an integer (default 1 if blank). Infer materials from the material column if present, else null. Infer part_type from description keywords (bracket/plate/panel → sheet_metal; block/housing/manifold → cnc_machined; bolt/screw/nut/washer → hardware; tube/pipe → tube_pipe) else null. TEngC# is a customer-specific cross-reference code — copy it if you see it under a "TEngC", "T-ENG-C", or similar column, else null. If no BOM visible → bom is [].
10. ASSEMBLY_METHOD — if a BOM or multiple components visible, set to "bolted" / "welded" / "riveted" / "bonded" based on visible fastener callouts, weld symbols, or notes. Single-piece drawings → null.
11. Same nominal in N locations = ONE dimension entry with quantity=N.
12. Thread depth_mm always in mm (inches * 25.4). Omit depth_mm if not shown.
13. NOTES — capture every shop-instruction note visible on the drawing. Each note is one short string in the notes[] array. INCLUDE: cleaning specs (e.g. "CLEAN PER AMAT SPEC 0250-07001", "AMAT PKG", "FRONTKEN CLEAN"), deburr callouts, part-mark callouts, surface-finish instructions, heat-treat / plating / anodize specs, packaging callouts, GENERAL NOTES table rows, and vendor-outsourced operations. Copy each note verbatim (or as close to verbatim as you can read). EXCLUDE: boilerplate company headers, drafting standards references ("PER ASME Y14.5"), and the title block itself. If the drawing is a pure non-technical cover/photo page, use ["non_technical_page"] or ["not_a_drawing"] instead.
14. BIAS TOWARD INCLUSION: when uncertain whether to include a dimension or a note, include it. A dimension with unit=null is better than a missing dimension; a note copied imperfectly is better than a silent drop.
15. Response MUST be ONLY the JSON object. No text before or after."""
