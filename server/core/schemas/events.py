"""Typed SSE event payloads.

Engines emit events through an opaque ``OnEvent`` callback; the
orchestrator turns each one into an SSE frame. Keeping the wire shapes
modelled here lets us validate them in tests without spinning up the
HTTP layer.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
    "status",
    "tool_call",
    "tool_result",
    "thinking",
    "final_answer",
    "error",
    "done",
    "heartbeat",
]


class SSEEvent(BaseModel):
    """One framed event ready for SSE transport."""

    model_config = ConfigDict(extra="allow")

    event: EventType
    data:  dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def status(cls, title: str, message: str, completed: bool = False) -> SSEEvent:
        return cls(event="status", data={
            "title": title, "message": message, "completed": completed,
        })

    @classmethod
    def tool_call(cls, tool: str, *, iteration: int = 1, label: str = "") -> SSEEvent:
        return cls(event="tool_call", data={
            "tool": tool, "iteration": iteration, "label": label or tool,
        })

    @classmethod
    def tool_result(cls, tool: str, result: dict) -> SSEEvent:
        return cls(event="tool_result", data={"tool": tool, "result": result})

    @classmethod
    def thinking(cls, content: str) -> SSEEvent:
        return cls(event="thinking", data={"content": content})

    @classmethod
    def final_answer(cls, payload: dict) -> SSEEvent:
        return cls(event="final_answer", data=payload)

    @classmethod
    def error(cls, message: str) -> SSEEvent:
        return cls(event="error", data={"message": message})

    @classmethod
    def done(cls) -> SSEEvent:
        return cls(event="done", data={})

    @classmethod
    def heartbeat(cls) -> SSEEvent:
        return cls(event="heartbeat", data={})
