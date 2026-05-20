"""Pairwise component-contact detection via a FreeCAD subprocess.

Approach:
  * Multi-component assemblies: spawn a FreeCAD-aware Python and use
    ``Part.Shape.distToShape`` to measure pairwise distance between every
    pair of solids. Faces within ``TOUCH_TOL=0.5mm`` are treated as a
    contact and classified as face / edge / vertex from FreeCAD's
    nearest-topology metadata.
  * Single-component STEPs: nothing to compare — short-circuit to ``[]``.
  * No FreeCAD available: subprocess exits cleanly with an empty contact
    list; the caller treats it as "no info" rather than an error.

The FreeCAD env path defaults to ``/workspace/miniconda3/envs/freecad``
(the customer's production container layout); locally the parent Python
is used as a fallback so the engine still imports during dev. The
sandboxed parent Python obviously won't have FreeCAD — that's expected,
and the empty-result fallback is the contract.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import textwrap

from ...core.settings import get_settings

logger = logging.getLogger("cncserver.engines.extraction_3d.welding")


_WELD_SCRIPT = textwrap.dedent("""\
    #!/usr/bin/env python3
    '''Pairwise contact detection via FreeCAD's distToShape.'''
    import sys, os, json, traceback

    # Wire up FreeCAD's binary path so `import FreeCAD` resolves.
    if sys.platform == "win32":
        # Windows conda: <env>/python.exe + <env>/Library/bin/FreeCAD.pyd
        _libbin = os.path.join(os.path.dirname(sys.executable), "Library", "bin")
        if os.path.isdir(_libbin):
            sys.path.insert(0, _libbin)
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(_libbin)
    else:
        # Linux pod conda env (matches install_freecad.sh).
        _FC_LIB = "/workspace/miniconda3/envs/freecad/lib"
        if os.path.isdir(_FC_LIB):
            sys.path.insert(0, _FC_LIB)
            os.environ["LD_LIBRARY_PATH"] = (
                _FC_LIB + ":/usr/local/cuda-12.9/compat:/usr/local/cuda-12.9/lib64:"
                + os.environ.get("LD_LIBRARY_PATH", "")
            )

    def _err(msg, **extra):
        payload = {"ok": False, "contacts": [], "error": msg}
        payload.update(extra)
        print(json.dumps(payload))

    if len(sys.argv) < 2:
        _err("no step file")
        sys.exit(1)

    step_file  = sys.argv[1]
    comp_names = json.loads(sys.argv[2]) if len(sys.argv) >= 3 else []
    TOUCH_TOL  = 0.5  # mm — faces closer than this are "in contact"

    try:
        import FreeCAD, Part
    except ImportError as exc:
        _err(f"FreeCAD not available: {exc}", traceback=traceback.format_exc())
        sys.exit(0)

    try:
        # Part.read returns a compound; .Solids walks the compound tree and
        # returns leaf solids with their global XDE placements applied.
        shape = Part.read(step_file)
        solids = list(shape.Solids)

        # Fallback: if Part.read collapsed an XDE assembly, try the Import
        # module which preserves per-component objects in a Document.
        if len(solids) < 2 and len(comp_names) > 1:
            sys.stderr.write(
                f"[weld] Part.read returned {len(solids)} solid(s) but expected "
                f"{len(comp_names)}; trying Import.open fallback\\n"
            )
            try:
                import Import
                import_doc = FreeCAD.newDocument("weld_import")
                Import.open(step_file, import_doc.Name)
                import_solids = []
                for obj in import_doc.Objects:
                    sh = getattr(obj, "Shape", None)
                    if sh and sh.Solids:
                        import_solids.extend(sh.Solids)
                if len(import_solids) > len(solids):
                    solids = import_solids
                    sys.stderr.write(f"[weld] Import.open gave {len(solids)} solids\\n")
            except Exception as exc:
                sys.stderr.write(f"[weld] Import.open fallback failed: {exc}\\n")

        sys.stderr.write(
            f"[weld] measuring {len(solids)} solids (expected {len(comp_names)})\\n"
        )

        if len(solids) < 2:
            print(json.dumps({
                "ok": True, "contacts": [],
                "note": f"only {len(solids)} solid(s) resolved — nothing to compare",
                "solids_found": len(solids),
                "components_expected": len(comp_names),
            }))
            sys.exit(0)

        contacts = []
        pair_errors = []
        for i in range(len(solids)):
            for j in range(i + 1, len(solids)):
                try:
                    dist, _vectors, info = solids[i].distToShape(solids[j])
                    if dist > TOUCH_TOL:
                        continue
                    # Classify contact by nearest topo-type on each side.
                    ctype = "face"
                    if info:
                        t1 = info[0][0][0] if info[0] and info[0][0] else ""
                        t2 = info[0][1][0] if info[0] and info[0][1] else ""
                        if t1 == "Face" and t2 == "Face":
                            ctype = "face"
                        elif "Vertex" in (t1, t2):
                            ctype = "vertex"
                        elif "Edge" in (t1, t2):
                            ctype = "edge"
                    contacts.append({
                        "comp_a":            comp_names[i] if i < len(comp_names) else f"comp_{i}",
                        "comp_b":            comp_names[j] if j < len(comp_names) else f"comp_{j}",
                        "comp_a_index":      i,
                        "comp_b_index":      j,
                        "contact_length_mm": round(float(dist), 4),
                        "contact_type":      ctype,
                    })
                except Exception as exc:
                    pair_errors.append(f"pair ({i},{j}): {exc}")
                    sys.stderr.write(f"[weld] pair ({i},{j}) failed: {exc}\\n")

        sys.stderr.write(f"[weld] found {len(contacts)} contact(s)\\n")
        payload = {
            "ok":                  True,
            "contacts":            contacts,
            "solids_found":        len(solids),
            "components_expected": len(comp_names),
        }
        if pair_errors:
            payload["pair_errors"] = pair_errors[:5]
        print(json.dumps(payload))
        sys.exit(0)

    except Exception as exc:
        print(json.dumps({
            "ok": False, "contacts": [],
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }))
        sys.exit(2)
""")


def _freecad_python() -> str | None:
    """Resolve the FreeCAD-aware interpreter, or None when unavailable.

    When neither ``FREECAD_PYTHON`` nor the pod's conda env path resolves,
    return None so the caller can short-circuit to an empty contact list
    rather than spawning a Python that can't import FreeCAD.
    """
    env_var = os.environ.get("FREECAD_PYTHON")
    if env_var and os.path.isfile(env_var):
        return env_var
    pod_default = "/workspace/miniconda3/envs/freecad/bin/python3"
    if os.path.isfile(pod_default):
        return pod_default
    return None


async def detect_welding_contacts(
    step_bytes: bytes,
    components: list[dict],
) -> list[dict]:
    """Pairwise contact detection. Empty list on single-component / failure."""
    if len(components) <= 1:
        return []

    timeout = get_settings().geometry.welding_subprocess_timeout_sec
    comp_names = [c.get("name", f"comp_{i}") for i, c in enumerate(components)]
    logger.info("detect_welding_contacts: %d components, timeout=%ds", len(components), timeout)

    python_exe = _freecad_python()
    if python_exe is None:
        logger.info(
            "detect_welding_contacts: FREECAD_PYTHON not configured; "
            "returning empty contact list",
        )
        return []

    with tempfile.TemporaryDirectory(prefix="extraction_3d_weld_") as tmpdir:
        step_file   = os.path.join(tmpdir, "part.step")
        script_file = os.path.join(tmpdir, "weld_runner.py")

        with open(step_file, "wb") as f:
            f.write(step_bytes)
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(_WELD_SCRIPT)

        env = dict(os.environ)
        env.pop("DISPLAY", None)

        try:
            proc = await asyncio.create_subprocess_exec(
                python_exe, script_file, step_file,
                json.dumps(comp_names),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("detect_welding_contacts: timed out after %ds", timeout)
                return []

            stdout = stdout_b.decode("utf-8", errors="replace").strip()
            stderr = stderr_b.decode("utf-8", errors="replace").strip()
            if stderr:
                for line in stderr.splitlines()[-10:]:
                    logger.info("weld| %s", line[:300])

            if not stdout:
                logger.warning("detect_welding_contacts: empty stdout (rc=%s)", proc.returncode)
                return []

            last_line = next(
                (l.strip() for l in reversed(stdout.splitlines()) if l.strip()), ""
            )
            result = json.loads(last_line)

            if not result.get("ok"):
                logger.warning(
                    "detect_welding_contacts: subprocess error: %s",
                    result.get("error") or "unknown",
                )
            if result.get("note"):
                logger.info("detect_welding_contacts: %s", result["note"])
            if result.get("pair_errors"):
                logger.warning(
                    "detect_welding_contacts: %d pair error(s): %s",
                    len(result["pair_errors"]),
                    result["pair_errors"][:3],
                )

            contacts = result.get("contacts") or []
            logger.info(
                "detect_welding_contacts: found %d contacts (solids=%s, expected=%s)",
                len(contacts),
                result.get("solids_found"),
                result.get("components_expected"),
            )
            return contacts

        except json.JSONDecodeError as exc:
            logger.warning("detect_welding_contacts JSON error: %s", exc)
            return []
        except Exception as exc:
            logger.warning("detect_welding_contacts failed: %s", exc)
            return []
