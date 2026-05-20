"""Workspace tools exposed to the agent.

Four tools — read / write / list / delete — backed by a
:class:`server.engines.agentic.workspace.ComponentWorkspace`. The
filesystem details (path, sandboxing) live in the workspace module; this
file is purely the LLM-facing wrapper.

The agent uses these to checkpoint intermediate decisions (machine pick,
op sequence, tool list, parameters) so the loop is resume-safe across
interrupts.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ..workspace import ComponentWorkspace

logger = logging.getLogger("cncserver.engines.agentic.tools.workspace_tool")


def make_workspace_tools(
    workspace: ComponentWorkspace | None,
) -> dict[str, Callable[..., Any]]:
    """Bind a component workspace and return the agent-facing tool callables.

    If ``workspace`` is None (e.g. test harness), every tool returns a
    clean error dict instead of crashing the loop.
    """
    if workspace is None:
        def _disabled(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"error": "workspace not available for this analysis"}
        return {
            "workspace_read":   _disabled,
            "workspace_write":  _disabled,
            "workspace_list":   _disabled,
            "workspace_delete": _disabled,
        }

    def workspace_write(filename: str, content: Any) -> dict[str, Any]:
        return workspace.write(filename, content)

    def workspace_read(filename: str) -> dict[str, Any]:
        return workspace.read(filename)

    def workspace_list() -> dict[str, Any]:
        return workspace.list_files()

    def workspace_delete(filename: str) -> dict[str, Any]:
        return workspace.delete(filename)

    return {
        "workspace_write":  workspace_write,
        "workspace_read":   workspace_read,
        "workspace_list":   workspace_list,
        "workspace_delete": workspace_delete,
    }


WORKSPACE_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "workspace_list",
            "description": (
                "List files currently in this component's workspace. "
                "Call this once at the very start of every component to detect "
                "resume state — if the list is non-empty, an earlier run was "
                "interrupted and you should `workspace_read` each file to "
                "rehydrate your progress before continuing."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_read",
            "description": (
                "Read a previously written workspace file. Returns the raw "
                "content and, when it parses, a decoded `json` field."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Bare filename, e.g. 'machine.json'.",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_write",
            "description": (
                "Checkpoint progress to a workspace file. Use after each major "
                "decision (machine pick, operations list, tool selection, "
                "parameter set) so the loop is resume-safe. Content can be a "
                "string or a JSON-encodable object — it is stored as text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "Bare filename matching [A-Za-z0-9_.\\-]+. "
                            "Conventional names: machine.json, operations.json, "
                            "tools.json, parameters.json, state.json."
                        ),
                    },
                    "content": {
                        "description": "String or JSON-encodable object to persist.",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_delete",
            "description": "Remove one workspace file. Use when discarding a stale checkpoint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                },
                "required": ["filename"],
            },
        },
    },
]


__all__ = [
    "make_workspace_tools",
    "WORKSPACE_TOOL_SPECS",
]
