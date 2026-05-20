"""Static material database — port of the existing :mod:`materials` module.

This is the single source of truth the cost engine and the cutting-speed
estimator consult when the user catalog has nothing material-specific.
Anything that talks to a user-overridden material catalog should layer on
top of this — never replace it — so we always have safe fallbacks.

Each entry exposes the fields downstream code reads by name:

  * ``name``            — human-readable
  * ``hardness_bhn``    — Brinell hardness
  * ``sfm_hss``         — recommended surface speed for HSS tooling (ft/min)
  * ``sfm_carbide``     — recommended surface speed for carbide tooling
  * ``feed_factor``     — multiplier on the default chip-load
  * ``density_lb_in3``  — density in lb/in³ (cost engine: volume → mass)
  * ``cost_per_lb``     — raw stock price ($/lb)
  * ``machinability``   — qualitative bucket ("excellent" … "difficult")
"""
from __future__ import annotations

MATERIALS: dict[str, dict] = {
    "6061-T6":   {"name": "6061-T6 Aluminum",        "hardness_bhn": 95,  "sfm_hss": 300, "sfm_carbide": 900,  "feed_factor": 1.00, "density_lb_in3": 0.098, "cost_per_lb": 3.0,   "machinability": "excellent"},
    "7075-T6":   {"name": "7075-T6 Aluminum",        "hardness_bhn": 150, "sfm_hss": 200, "sfm_carbide": 700,  "feed_factor": 0.90, "density_lb_in3": 0.101, "cost_per_lb": 5.0,   "machinability": "good"},
    "2024-T3":   {"name": "2024-T3 Aluminum",        "hardness_bhn": 120, "sfm_hss": 250, "sfm_carbide": 800,  "feed_factor": 0.95, "density_lb_in3": 0.100, "cost_per_lb": 4.5,   "machinability": "good"},
    "1018":      {"name": "1018 Mild Steel",         "hardness_bhn": 126, "sfm_hss": 80,  "sfm_carbide": 450,  "feed_factor": 0.70, "density_lb_in3": 0.284, "cost_per_lb": 1.5,   "machinability": "good"},
    "4140":      {"name": "4140 Alloy Steel",        "hardness_bhn": 197, "sfm_hss": 60,  "sfm_carbide": 350,  "feed_factor": 0.60, "density_lb_in3": 0.284, "cost_per_lb": 2.5,   "machinability": "fair"},
    "304_ss":    {"name": "304 Stainless Steel",     "hardness_bhn": 170, "sfm_hss": 50,  "sfm_carbide": 300,  "feed_factor": 0.50, "density_lb_in3": 0.289, "cost_per_lb": 4.0,   "machinability": "poor"},
    "316_ss":    {"name": "316 Stainless Steel",     "hardness_bhn": 175, "sfm_hss": 45,  "sfm_carbide": 280,  "feed_factor": 0.45, "density_lb_in3": 0.290, "cost_per_lb": 5.0,   "machinability": "poor"},
    "C360":      {"name": "C360 Free-Cutting Brass", "hardness_bhn": 78,  "sfm_hss": 400, "sfm_carbide": 1000, "feed_factor": 1.20, "density_lb_in3": 0.307, "cost_per_lb": 4.0,   "machinability": "excellent"},
    "Ti-6Al-4V": {"name": "Ti-6Al-4V Titanium",      "hardness_bhn": 334, "sfm_hss": 25,  "sfm_carbide": 150,  "feed_factor": 0.30, "density_lb_in3": 0.160, "cost_per_lb": 25.0,  "machinability": "difficult"},
    # Engineering plastics — sfm_carbide for milling; climb-cut, coolant flood
    "PEEK":      {"name": "PEEK",                    "hardness_bhn": 30,  "sfm_hss": 200, "sfm_carbide": 500,  "feed_factor": 1.00, "density_lb_in3": 0.047, "cost_per_lb": 60.0,  "machinability": "good"},
    "Acetal":    {"name": "Acetal / Delrin",         "hardness_bhn": 20,  "sfm_hss": 300, "sfm_carbide": 800,  "feed_factor": 1.10, "density_lb_in3": 0.051, "cost_per_lb": 5.0,   "machinability": "excellent"},
    "Nylon":     {"name": "Nylon / PA6",             "hardness_bhn": 25,  "sfm_hss": 250, "sfm_carbide": 600,  "feed_factor": 1.00, "density_lb_in3": 0.041, "cost_per_lb": 5.0,   "machinability": "good"},
    "PVC":       {"name": "PVC",                     "hardness_bhn": 15,  "sfm_hss": 250, "sfm_carbide": 600,  "feed_factor": 1.00, "density_lb_in3": 0.051, "cost_per_lb": 3.0,   "machinability": "good"},
    "CPVC":      {"name": "CPVC",                    "hardness_bhn": 18,  "sfm_hss": 250, "sfm_carbide": 600,  "feed_factor": 1.00, "density_lb_in3": 0.056, "cost_per_lb": 4.0,   "machinability": "good"},
    "PET":       {"name": "PET / PETG",              "hardness_bhn": 25,  "sfm_hss": 200, "sfm_carbide": 500,  "feed_factor": 0.95, "density_lb_in3": 0.051, "cost_per_lb": 4.0,   "machinability": "good"},
    "UHMW":      {"name": "UHMW-PE",                 "hardness_bhn": 10,  "sfm_hss": 400, "sfm_carbide": 1000, "feed_factor": 1.20, "density_lb_in3": 0.034, "cost_per_lb": 4.0,   "machinability": "excellent"},
    "HDPE":      {"name": "HDPE",                    "hardness_bhn": 12,  "sfm_hss": 400, "sfm_carbide": 1000, "feed_factor": 1.20, "density_lb_in3": 0.035, "cost_per_lb": 3.0,   "machinability": "excellent"},
    "Semitron":  {"name": "Semitron ESD",            "hardness_bhn": 35,  "sfm_hss": 150, "sfm_carbide": 300,  "feed_factor": 0.80, "density_lb_in3": 0.048, "cost_per_lb": 120.0, "machinability": "fair"},
    "Silicone":  {"name": "Silicone Rubber",         "hardness_bhn": 5,   "sfm_hss": 50,  "sfm_carbide": 150,  "feed_factor": 0.50, "density_lb_in3": 0.043, "cost_per_lb": 15.0,  "machinability": "waterjet"},
}

DEFAULT_MATERIAL: dict = {
    "name":           "Unknown Material (assumed Aluminum)",
    "hardness_bhn":   100,
    "sfm_hss":        250,
    "sfm_carbide":    800,
    "feed_factor":    0.9,
    "density_lb_in3": 0.098,
    "cost_per_lb":    3.0,
    "machinability":  "unknown",
}


_FAMILY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("aluminum", "aluminium"),           "6061-T6"),
    (("stainless",),                       "304_ss"),
    (("steel",),                           "1018"),
    (("brass",),                           "C360"),
    (("titanium",),                        "Ti-6Al-4V"),
    (("peek",),                            "PEEK"),
    (("semitron", "esd"),                  "Semitron"),
    (("acetal", "delrin", "pom"),          "Acetal"),
    (("nylon", "pa6", "pa66"),             "Nylon"),
    (("cpvc",),                            "CPVC"),
    (("pvc",),                             "PVC"),
    (("petg", "pet"),                      "PET"),
    (("uhmw",),                            "UHMW"),
    (("hdpe",),                            "HDPE"),
    (("silicone", "rubber"),               "Silicone"),
)


def match_material(spec: str | None) -> dict:
    """Match a free-text material spec to the closest :data:`MATERIALS` row.

    Strategy:
      1. Direct substring (ignoring case and dashes) on the table keys.
      2. Family-keyword hints (``"aluminum"`` → 6061-T6, ``"stainless"`` → 304_ss, …).
      3. Fall through to :data:`DEFAULT_MATERIAL`.

    Never raises; an empty or ``None`` spec returns the default.
    """
    if not spec:
        return DEFAULT_MATERIAL

    s = spec.lower().replace("-", "")
    for key, mat in MATERIALS.items():
        if key.lower().replace("-", "") in s:
            return mat
    for keywords, target in _FAMILY_HINTS:
        if any(kw in s for kw in keywords):
            return MATERIALS[target]
    return DEFAULT_MATERIAL
