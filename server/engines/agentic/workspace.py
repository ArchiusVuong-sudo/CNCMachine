"""Per-analysis on-disk workspace for the agentic engine.

The single-loop agent (see :mod:`server.engines.agentic.agent`) is the
only consumer. Each analysis gets one root directory; each component
gets a subdirectory under it. The agent writes small JSON checkpoints
into its component directory (``machine.json``, ``operations.json``,
``tools.json``, ``parameters.json``, or whatever else it picks) so that
if the loop gets interrupted — iteration cap hit, server restart,
network blip on the vLLM stream — a later retry can read the checkpoints
back and resume instead of redoing the whole component.

Layout::

    <repo_root>/.agentic_workspace/<analysis_id>/
    ├── component_0/
    │     ├── machine.json
    │     ├── operations.json
    │     └── ...
    ├── component_1/
    │     └── ...
    └── ...

Lifecycle is owned by :class:`server.engines.agentic.coordinator`:

    ws = AnalysisWorkspace.open(analysis_id)
    try:
        ...                 # hand ws.for_component(i) to each agent
    finally:
        ws.cleanup()        # rm -rf the whole analysis dir

If the coordinator never reaches the ``finally`` (process crashed), the
directory survives on disk so the next retry can rehydrate state — and
:func:`AnalysisWorkspace.sweep_stale` can later GC the leftover dirs.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("cncserver.engines.agentic.workspace")

# workspace.py → agentic → engines → server → data
_REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = (_REPO_ROOT / ".agentic_workspace").resolve()

# Hard caps so a runaway agent can't fill the disk.
_MAX_FILE_BYTES = 256 * 1024        # 256 KiB per file
_MAX_FILES_PER_COMPONENT = 32
_VALID_FILENAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$")
_VALID_ANALYSIS_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$")
_STALE_AFTER_SEC = 7 * 24 * 3600    # 7 days


def _safe_analysis_id(analysis_id: str | None) -> str:
    """Return a path-safe analysis id, or synthesize one if missing.

    The orchestrator always supplies a real id; this guard exists so unit
    tests and one-off calls don't crash when the id is omitted.
    """
    if analysis_id and _VALID_ANALYSIS_ID_RE.match(analysis_id):
        return analysis_id
    return f"adhoc_{int(time.time() * 1000)}"


def _safe_filename(name: str) -> str | None:
    """Validate a filename; reject traversal and weird names. Returns None on bad input."""
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not _VALID_FILENAME_RE.match(name):
        return None
    return name


class ComponentWorkspace:
    """Per-component facade. Exposes read/write/list/delete with safe paths.

    Instances are bound to one directory; the agent never sees absolute
    paths. All errors come back as ``{"error": "..."}`` rather than
    raising — the tool loop must never crash because of a workspace
    issue.
    """

    __slots__ = ("_dir", "_analysis_id", "_component_index")

    def __init__(self, root_dir: Path, analysis_id: str, component_index: int) -> None:
        self._dir = root_dir
        self._analysis_id = analysis_id
        self._component_index = component_index
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("workspace: mkdir %s failed (%s)", self._dir, exc)

    # ----- public API consumed by the workspace tools ---------------------

    @property
    def component_index(self) -> int:
        return self._component_index

    @property
    def path(self) -> Path:
        return self._dir

    def list_files(self) -> dict[str, Any]:
        """List filenames currently in the workspace (no contents)."""
        if not self._dir.exists():
            return {"files": [], "count": 0}
        files: list[dict[str, Any]] = []
        try:
            for entry in sorted(self._dir.iterdir()):
                if entry.is_file():
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = 0
                    files.append({"name": entry.name, "size_bytes": size})
        except OSError as exc:
            return {"error": f"list failed: {exc}"}
        return {"files": files, "count": len(files)}

    def read(self, filename: str) -> dict[str, Any]:
        """Read a file back. Auto-decodes JSON when the content parses."""
        safe = _safe_filename(filename)
        if safe is None:
            return {"error": f"invalid filename: {filename!r}"}
        target = self._dir / safe
        if not target.exists() or not target.is_file():
            # An absent file is a VALID answer to a probe (the agent reads
            # before writing to detect resume state) — NOT a failure. Return
            # it without an `error` key so the activity UI doesn't flag a
            # routine "not yet written" read as a red error.
            return {"ok": False, "exists": False, "filename": safe,
                    "message": f"file not found: {safe}"}
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"error": f"read failed: {exc}"}
        out: dict[str, Any] = {
            "filename": safe,
            "size_bytes": len(raw.encode("utf-8", errors="replace")),
            "content": raw,
        }
        # Best-effort JSON decode for the agent's convenience.
        stripped = raw.strip()
        if stripped and stripped[:1] in "{[":
            try:
                out["json"] = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                pass
        return out

    def write(self, filename: str, content: Any) -> dict[str, Any]:
        """Write a file. ``content`` may be a string or a JSON-encodable value."""
        safe = _safe_filename(filename)
        if safe is None:
            return {"error": f"invalid filename: {filename!r}"}
        if isinstance(content, str):
            payload = content
        else:
            try:
                payload = json.dumps(content, indent=2, ensure_ascii=False, default=str)
            except (TypeError, ValueError) as exc:
                return {"error": f"content not JSON-serializable: {exc}"}
        encoded = payload.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_FILE_BYTES:
            return {
                "error": (
                    f"file exceeds {_MAX_FILE_BYTES} bytes "
                    f"({len(encoded)}). Trim or split into smaller checkpoints."
                ),
            }
        existing = self.list_files().get("files") or []
        existing_names = {(f or {}).get("name") for f in existing}
        if safe not in existing_names and len(existing_names) >= _MAX_FILES_PER_COMPONENT:
            return {
                "error": (
                    f"workspace already holds {_MAX_FILES_PER_COMPONENT} files. "
                    "Delete or overwrite an existing one instead."
                ),
            }
        target = self._dir / safe
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.write_bytes(encoded)
            tmp.replace(target)
        except OSError as exc:
            return {"error": f"write failed: {exc}"}
        return {"ok": True, "filename": safe, "size_bytes": len(encoded)}

    def delete(self, filename: str) -> dict[str, Any]:
        """Remove one file from the workspace."""
        safe = _safe_filename(filename)
        if safe is None:
            return {"error": f"invalid filename: {filename!r}"}
        target = self._dir / safe
        if not target.exists():
            return {"ok": True, "filename": safe, "already_absent": True}
        try:
            target.unlink()
        except OSError as exc:
            return {"error": f"delete failed: {exc}"}
        return {"ok": True, "filename": safe}


class AnalysisWorkspace:
    """One temp directory per analysis. Hands out per-component facades.

    Construct via :meth:`open` so the directory is created up front and the
    instance has a real path to hand to the agent.
    """

    __slots__ = ("_root", "_analysis_id")

    def __init__(self, root: Path, analysis_id: str) -> None:
        self._root = root
        self._analysis_id = analysis_id

    @classmethod
    def open(cls, analysis_id: str | None) -> "AnalysisWorkspace":
        safe = _safe_analysis_id(analysis_id)
        root = (WORKSPACE_ROOT / safe).resolve()
        try:
            root.relative_to(WORKSPACE_ROOT)
        except ValueError:
            # Defence-in-depth: should never trigger because the id regex
            # rules out path separators.
            root = WORKSPACE_ROOT / f"adhoc_{int(time.time() * 1000)}"
        root.mkdir(parents=True, exist_ok=True)
        return cls(root, safe)

    @property
    def analysis_id(self) -> str:
        return self._analysis_id

    @property
    def path(self) -> Path:
        return self._root

    def for_component(self, component_index: int) -> ComponentWorkspace:
        idx = int(component_index)
        comp_dir = (self._root / f"component_{idx}").resolve()
        return ComponentWorkspace(comp_dir, self._analysis_id, idx)

    def cleanup(self) -> bool:
        """``rm -rf`` the analysis dir. Idempotent and best-effort."""
        try:
            if self._root.exists():
                shutil.rmtree(self._root, ignore_errors=False)
            return True
        except OSError as exc:
            logger.warning("workspace: cleanup of %s failed (%s)", self._root, exc)
            return False

    # ----- maintenance ----------------------------------------------------

    @classmethod
    def sweep_stale(cls, max_age_sec: float = _STALE_AFTER_SEC) -> int:
        """Delete analysis dirs older than ``max_age_sec``. Returns count removed.

        Called opportunistically from the coordinator at start-of-run so
        the workspace root doesn't grow unbounded across crashes.
        """
        if not WORKSPACE_ROOT.exists():
            return 0
        cutoff = time.time() - max_age_sec
        removed = 0
        try:
            for entry in WORKSPACE_ROOT.iterdir():
                if not entry.is_dir():
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime < cutoff:
                    try:
                        shutil.rmtree(entry, ignore_errors=True)
                        removed += 1
                    except OSError:
                        pass
        except OSError as exc:
            logger.warning("workspace: sweep_stale failed (%s)", exc)
        return removed


__all__ = [
    "AnalysisWorkspace",
    "ComponentWorkspace",
    "WORKSPACE_ROOT",
]
