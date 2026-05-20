"""Smoke test the local FreeCAD install.

Verifies the FreeCAD-aware Python can import FreeCAD/Part/Path so the
CAM engine + welding subprocess come online.

Run:
    cd E:\\data
    python -m server.infra.migrations.smoke_freecad
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path


def _load_env() -> None:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        print(f"smoke: no .env at {env_file}", file=sys.stderr)
        sys.exit(2)
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _direct_import(python_exe: str) -> int:
    """Run a one-liner under the FreeCAD Python; print module versions.

    Mirrors the platform-specific path setup the embedded subprocess
    scripts (freecad_script.py, welding.py) do before ``import FreeCAD``.
    """
    code = (
        "import os, sys\n"
        "if sys.platform == 'win32':\n"
        "    libbin = os.path.join(os.path.dirname(sys.executable), 'Library', 'bin')\n"
        "    if os.path.isdir(libbin):\n"
        "        sys.path.insert(0, libbin)\n"
        "        if hasattr(os, 'add_dll_directory'):\n"
        "            os.add_dll_directory(libbin)\n"
        "import FreeCAD, Part, Path\n"
        "print('FreeCAD', FreeCAD.Version()[:3])\n"
        "print('Part OK, Path OK')\n"
    )
    print(f"smoke: spawning {python_exe} (with Windows path setup)")
    res = subprocess.run([python_exe, "-c", code], capture_output=True, text=True)
    print("stdout:", res.stdout.strip())
    if res.stderr.strip():
        print("stderr:", res.stderr.strip()[:500])
    return res.returncode


async def _cam_runner_check() -> int:
    """Exercise the CAM short-circuit removal: with FREECAD_PYTHON set,
    run_cam_subprocess should now actually spawn the subprocess (and fail
    on our empty STEP because there's nothing to plan — that's fine)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from server.engines.cam.freecad_runner import _freecad_python, run_cam_subprocess
    py = _freecad_python()
    print(f"smoke: _freecad_python() = {py}")
    if py is None:
        print("smoke: CAM engine still short-circuiting; FREECAD_PYTHON not wired")
        return 1
    res = await run_cam_subprocess(
        b"",
        {"operations": [], "component_name": "smoke", "post_processor": "linuxcnc"},
        out_dir=str(Path(__file__).parent),
    )
    print(f"smoke: cam subprocess result = {res}")
    return 0


def main() -> int:
    _load_env()
    py = os.environ.get("FREECAD_PYTHON")
    print(f"smoke: FREECAD_PYTHON = {py!r}")
    if not py or not Path(py).is_file():
        print("smoke: FREECAD_PYTHON is unset or points nowhere")
        return 2
    rc = _direct_import(py)
    if rc != 0:
        return rc
    return asyncio.run(_cam_runner_check())


if __name__ == "__main__":
    sys.exit(main())
