# Materials Reference

Plastics only in this corpus. Properties drive cutting speed, finish, fixturing, scrap,
and material cost. Prices/densities below are seeds — **calibrate the RM/unit from each
part's Job Cost "Material" line** (that is the shop's real paid price) in Phase 4.

| Material | Aliases / grades seen | Density g/cm³ | Machinability | Cutting notes |
|---|---|---|---|---|
| **PEEK** | Victrex **PEEK 450G** natural; carbon/glass-filled variants | ~1.30 (450G), ~1.40 filled | Good but abrasive (filled = very abrasive → carbide, faster wear) | High Vc, sharp uncoated carbide, climb mill, watch heat (Tg~143°C, melt~343°C); stress-relieve for tight tol; most expensive stock here (~RM/ft high) |
| **Delrin / POM** (acetal) | Delrin, acetal copolymer | ~1.41 | Excellent (best of the three) | Fast feeds/speeds, great finish, low force; chips clear easily; cheap |
| **Polypropylene (PP)** | PP, copolymer | ~0.905 | Soft/gummy | Sharp tools, high RPM, light finish passes (burr/smearing); low cost; low rigidity → support thin walls |

## Cost basis
- Stock forms: **rod** (Ø×length) for round/lathe parts; **plate/block** (L×W×T) for
  prismatic. Job Cost gives line e.g. `PEEK 450G NAT 90MM ROD … RM23,232 / 13.12 ft`
  (whole job) → `RM/ft` then ÷ pieces. Convert: rod mass = π/4·Ø²·L·ρ.
- Reference anchor: PEEK 450G Ø90 rod ≈ **RM 387/pc** for 713-187739-236 (66.7 mm/pc).
- Add saw kerf + facing + chucking/grip allowance to the part envelope for billet size
  (observed allowances are generous — record actual stock vs part to learn the rule).
- Hardware (helicoils, inserts, dowels) from BOM × per-piece qty (e.g. M5 Nitronic
  helicoil ≈ RM 4.90 ea, 2/pc).

## Per-material price & density table (Phase 4 — fill from Job Cost lines)
| Material | RM per (ft/kg/each) | source part(s) | date |
|---|---|---|---|
| PEEK 450G Ø90 rod | RM ~1,770/ft (RM23,232 / 13.12 ft) | 713-187739-236 (10102R18) | 2026 |
| … | _to populate_ | | |

> Rule of thumb to refine: Material_pc ≈ stock_volume(cm³) × ρ(g/cm³) × RM/kg + hardware.
> Build RM/kg per material from many Job Cost lines; flag price drift over time.
