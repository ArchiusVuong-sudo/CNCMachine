# MEMORY.md — Engine 3 learned heuristics (agent-maintained)

> **This is your memory.** It is loaded into your system prompt next to
> `AGENT.md` on every run. It holds GENERALIZABLE lessons learned from past
> runs and tuning iterations — not part-specific answers.
>
> **You maintain it yourself** via the `memory_update` tool. Rules:
> - Write a lesson ONLY if it would help an *unseen* part. No part numbers,
>   no per-fixture fudge factors (same bar as the anti-overfit rules).
> - Keep it tight — every line here is paid for in every future prompt.
>   Each section has a cap; when full, replace the weakest entry, don't append.
> - New lessons go to **Candidate** (a holding area, not trusted yet). A
>   lesson is moved up to **Validated** only after a holdout re-run shows it
>   lowered deviation vs the customer ground truth. Until then, treat
>   Validated as strong and Candidate as tentative.

---

## Validated heuristics (proven; trust these)

1. **Anchor to real measured numbers, not first principles.** Reasoning a
   cycle time from scratch (feeds × path) systematically *under*-estimates,
   because non-CNC work (admin, hardware install, bonding, weld, lot
   inspection, packing) gets dropped. Always pull a measured analogue or an
   empirical prior (below). When you have a near-exact analogue (same
   material + part_type, similar size), COPY its run-minutes VERBATIM — only
   scale by the governing dim when the analogue differs materially in size.
   Rescaling a near-exact match is the #1 source of cost error.
2. **Do NOT model setup time.** Setup is a fixed system constant (a flat
   20 min/batch the pipeline applies automatically) and is **excluded**
   from cost-accuracy scoring. Emit `setup_min_per_lot: 0` on every op —
   whatever you put there is overwritten downstream. Spend zero reasoning
   on it. The only quantity that is scored is `run_min_per_part`; put all
   of your effort there.
3. **Run time is the only scored quantity — never anchor it from a setup
   number.** Admin / print / mat-pick rows carry zero run time, so they do
   not move the score; do not spend effort tuning their setup (it is the
   flat system constant). Score-moving run lives in MACHINING, DEBUR,
   ASSY, and INSP rows.
4. **Walk all 8 op-families before submitting.** PLANNING / PRINT / MATPICK /
   MACHINING / DEBUR / ASSY / INSP / PACK. A missing family is allowed but
   must be justified — silent omission is the most common failure. The
   run-bearing families (MACHINING, DEBUR, ASSY, INSP) matter most.

## Approaches already tried and REVERTED (do not repeat)

- **Top-3 analogue *median* anchor for run time** — raised variance: great
  when the 3 neighbours agree, bad when one is wrong-class. Prefer a single
  dominant analogue (clear top-1) over a blended median.

## Empirical cut-time priors — PEEK / PP only

From a 10-part shop dataset (none are eval parts). Use to anchor raw NC
minutes for **PEEK and Polypropylene** before calibration. PVC / PET / CPVC
are NOT covered — for those, fall back to an analogue or first principles.

**Calibration k** (`actual run ÷ summed cut-time`), corroborates AGENT.md:

| Machine class            | PEEK k (median, IQR) |
|--------------------------|----------------------|
| vmc_3_axis_well_behaved  | 1.17 (1.06–1.18)     |
| vmc_3_axis               | 1.33 (1.04–1.45)     |
| vmc_4_axis               | 1.27 (1.02–1.53)     |

**Cut rate** (min per 100 mm of cut length) — **line tools only**; do NOT
apply to face / radius / ball mills (area coverage breaks the per-length
normalization):

| Material | end_mill | drill | chamfer |
|----------|----------|-------|---------|
| PEEK     | 3.6      | 0.87  | 5.5     |
| PP       | 5.9      | 1.4   | —       |

## Data-quality cautions

- **Turn-mill / lathe / 5-axis NC is unreliable** — observed implied k of
  0.30, 2.44, 5.27 on these classes. Do not trust a computed cycle time
  here; price the op from a measured analogue — copy its run verbatim when
  near-exact, scale by Ø×L only when the analogue's size differs materially.
- **Some "actual run" figures are lot totals, not per-piece** (one op showed
  k≈8.6). If a calibrated time is wildly above the cut-time estimate,
  suspect a multi-piece program (`-NPC-`) or a lot-vs-piece mixup and
  sanity-check against qty.

## Candidate lessons (holding — not yet validated against ground truth)

1. **Don't double-count final inspection on top of a complete run.** The
   scored per-part run already embeds inspection. If you have emitted an
   `INSP_COMPONENT` run row, do NOT also add a full ~15-min
   (`fixed_hrs_per_lot: 0.25`) final-inspection lot block — that block is
   scored at full per-part value and double-counts (observed: it doubled a
   correct 15-min part to 30; re-adding fixed blocks blew the median from 14%
   back to 29%). Keep TOTAL inspection (component + final) proportional to
   complexity: a few minutes for simple parts, up to ~15 min only for
   genuinely CMM/GD&T-heavy parts. On simple parts set INSP_FINAL_FIXED_LOT
   to ≤0.05 hr or fold it into INSP_COMPONENT.
2. **Simple turn / router / small-mill parts are the most under-quoted —
   anchor machining to the measured analogue, never below it.** Bottom-up
   cut-time on a few-feature turned/routed part lands ~50% low (face+turn+
   drill+partoff summed to 3–6 min when the real run is 15+). Pull the
   closest measured analogue's machining run; copy it VERBATIM when the match
   is near-exact, scale by governing dim only for a materially different size,
   and never submit a machining total below the measured value.
3. **A welded/bonded assembly_top MUST carry weld + assembly run-minutes —
   zero is the failure mode.** The biggest miss observed on weldments is the
   assembly_top emitting only ADMIN + PACK + INSP_FINAL and dropping the join
   work entirely (a WLDMT scored −29% with zero weld/assembly ops). When
   `assembly_hint.welding_required` is true, a weld op is mandatory. Anchor it:
   `kb_adopt_routing` the closest measured weldment/assembly analogue FIRST and
   copy its ASSY/WELD/INSP run-minutes (scaled by piece-count) rather than
   re-deriving. Caveats on the anchor: (a) don't bottom-up sum every sub-item's
   fab plus 3 min × every hardware piece — that over-scopes large weldments
   (~+90%); trust the measured assembly total and cap per-piece hardware
   contribution. (b) Don't over-correct the other way — a multi-piece weldment
   whose sub-items are genuinely machined still needs their machining counted;
   collapsing them to one token op under-scopes ~−50%.
4. **Sanity-check the grand total before submitting.** The number scored is
   your full per-part run = Σ(run rows) + Σ(fixed_hrs_per_lot×60). Compare it
   to your chosen analogue's per-part run scaled by size; if it diverges
   >25%, find the offending row — usually a flat final-inspection block added
   on top (inflation) or bottom-up cut-time on a simple part (deflation).
5. **Emit `MARK_PART` when the part is identified — the engine used to drop
   marking entirely.** If the drawing or the adopted analogue routing shows
   part-marking / serialize / ink-laser-rubber-stamp / silkscreen / vibro-peen,
   emit `MARK_PART` (family MARKING) and copy the analogue's measured mark
   run-minutes (`kb_adopt_routing` now tags these rows correctly), else floor
   ~1–3 min/pc. Most parts have no marking → `MARKING = MISSING` is the common,
   correct call; do not invent it. Keep it distinct from `CNCM_PROFILE_ENGRAVE`
   (a CNC-milled engraved feature, which is MACHINING, not MARKING).
