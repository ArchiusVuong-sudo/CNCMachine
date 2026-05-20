# Cutting Parameters Reference

Supports **Machine Parameter Setting** (Feedrate, Spindle Speed, Stepover, Stepdown →
FreeCAD) and feeds the cycle-time model. Seed bands below; **the authoritative anchor is
the feeds/speeds observed in the corpus NC programs & Setup Sheets** — Phase 4 fills the
empirical table in `patterns/cutting_parameters.md` from `extracted/tools.csv`.

## Equations
```
n (RPM)      = 1000·Vc / (π·D)            cap at machine max (~10–12k)
F (mm/min)   = fz · z · n                 (milling, G94)
F (mm/rev)   = f_rev                       (turning, G95)
ae stepover  = k_ae · D                    rough ~0.4–0.6·D, finish ~0.05–0.15·D
ap stepdown  = k_ap · D                    rough ~0.5–2·D (plastics tolerate deep), finish ≤0.5
MRR          = ae · ap · F                 mm³/min
```

## Seed material bands (plastics) — start values, validate vs NC
| Material | Vc m/min | fz mm/tooth (Ø6–12) | turn f mm/rev | notes |
|---|---|---|---|---|
| PEEK 450G | 200–400 | 0.05–0.12 | 0.05–0.25 | filled grades: lower Vc, carbide |
| Delrin/POM | 250–500 | 0.06–0.15 | 0.05–0.25 | most forgiving; highest feeds |
| Polypropylene | 300–600 | 0.06–0.15 | 0.05–0.20 | gummy → sharp tool, light finish |

Observed NC anchors (reference part, PEEK, DNM 5700): S 5,000–10,000 RPM;
F 300–3,000 mm/min milling; rougher (Ø20 3FL chip-breaker) F≈2,500 @ S≈10,000;
finish EM Ø10 F≈900–1,500 @ S≈8,000; drills S 1,000–3,500 F 150–200; face mill Ø80
F≈800 @ S≈5,000. Turn-mill (713-A05592-003): turn f 0.05–0.25 mm/rev, S 1,000–2,000.

## Adjustment rules (generalize to unseen)
- Scale F with Ø & flutes: keep fz constant per material, recompute n from Vc and Ø.
- Long/thin tool (`depth/Ø`>4) or thin wall → ×0.3–0.6 on ap and fz (deflection/chatter).
- Roughing maximize ap (plastics allow ≥1·Ø) & MRR; finishing minimize ae for finish.
- Deep drilling depth/Ø>3 → peck (×~1.3 time); plastics → high helix, polished flute.
- Cap n at machine max; if Vc would exceed it, n is the limit and effective Vc drops.
- Climb milling default; coolant/air mist (heat control) — does not change time, affects
  achievable fz/Vc (allows the higher end of bands).

> Use these to *predict* params for a new feature, then **sanity-check against the
> nearest NC example** in `extracted/tools.csv`. Prefer interpolation within observed
> ranges; flag extrapolation.
