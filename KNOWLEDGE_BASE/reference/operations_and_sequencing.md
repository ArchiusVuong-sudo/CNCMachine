# Operations & Sequencing (Machine Routing Planning)

Supports **Machine Routing Planning**: given features → ordered operation sequence. The
shop encodes order as `N1, N2, …` tokens in the Setup Sheet Operation/Comment cell and
as the order of operation-comment blocks in the NC. Learn the ordering from `Seq +
Feature/Op Type` across `extracted/operations.csv` (Phase 4).

## Job-level routing (macro)
`PLANNING → SAW → [CNC OP10 → OP20 → OP30 …] → DEBUR → INSPECT → ASSY (inserts) →
CLEAN → PACKAGE`. Each CNC OP = one fixturing/orientation; choosing OP split is part of
routing (datum first, then opposite/again for back features & re-grip).

## Within-a-setup operation order (micro) — canonical
1. **Face / fly** the reference surface (establish Z0 datum).
2. **Rough** bulk volume — biggest tool, large stepdown (chip-breaker EM).
3. **Rest / re-rough** — smaller tool clears what rougher couldn't.
4. **Drill** (spot → drill → peck) — before finishing so burrs are removed by finish.
5. **Semi-finish** then **finish** walls/floors/profile (sharp finish tool, light ae).
6. **Corner radius / fillets** (bull/corner-radius tools).
7. **Bores / reams / tight-tol features**.
8. **Threads** (thread-mill / tap) after holes finished.
9. **Chamfers / edge breaks / deburr-in-cycle**.
10. **Engrave** part number + revision.
(Lathe/turn-mill order: STOPPER set → OD rough → ID rough/drill → ID groove/thread →
ID finish → OD finish → **part-off last**. Observed N1-STOPPER…N11-Parting.)

Principles that generalize: datum/face first; rough→finish (never finish before
roughing nearby); drilling before finish (deburr); part-off / release last; minimize
tool changes (group same-tool ops) but never at the expense of rough-before-finish;
heat-sensitive plastics → don't dwell, keep tool moving.

## Feature → operation recipe (each feature expands to these ops)
| Feature | Operation chain |
|---|---|
| Top/datum face | fly/face mill |
| Open pocket | rough → rest-rough → wall finish → floor finish → corner fillet |
| Closed/deep pocket | helical/ramp entry → rough → semi → finish → fillet |
| Profile/outline | rough (leave ~0.2–0.5) → finish |
| Slot | slot mill / EM step rough → finish |
| Dovetail / groove | straight EM relief → form/dovetail tool |
| Simple hole | spot → drill (→ chamfer) |
| Deep hole (d/Ø>3) | spot → peck drill (→ chamfer) |
| Precision bore | spot → drill → bore/ream |
| Tapped hole | spot → tap-drill → tap/thread-mill (→ chamfer) |
| Helicoil hole | spot → tap-drill → STI thread-mill → insert (ASSY) |
| Chamfer/edge | chamfer mill or spot (R0.05–0.30 per note) |
| Engrave | engrave/ball mill (mandatory) |
| OD/ID turn | rough turn → finish turn |
| External/internal thread (turned) | turn → groove (relief) → thread → debur |
| Cut-off | parting tool (last) |

Each chain → tools (`reference/tooling.md`) → params (`reference/cutting_parameters.md`)
→ time (`methodology/03 §2`) → cost (`methodology/03 §1`). Count distinct tools & ops
for setup-time and complexity proxies.
