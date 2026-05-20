"""SSE event bus contract.

Engines never own the SSE transport; they emit events through an
async callback the orchestrator hands them.  Bridge helpers live here so
the pipeline doesn't need to re-invent queue-drain logic.

Event types
-----------
``status``        — coarse progress message (title, message, completed?)
``tool_call``     — engine started a logical "tool" / phase
``tool_result``   — that tool finished, with a small result dict
``thinking``      — chain-of-thought stream chunk (`{"content": str}`)
``final_answer``  — assembled pipeline result (terminal event)
``error``         — fatal error (terminal event)
``done``          — pipeline finished (always last)
``heartbeat``     — keep-alive, no payload
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("cncserver.core.events")

OnEvent = Callable[[str, dict], Awaitable[None]] | None
OnThinking = Callable[[str], Awaitable[None]] | None


async def safe_emit(on_event: OnEvent, ev_type: str, data: dict) -> None:
    """Invoke on_event; never let a callback failure kill the engine."""
    if on_event is None:
        return
    try:
        await on_event(ev_type, data)
    except Exception as exc:  # pragma: no cover - belt and suspenders
        logger.warning("safe_emit(%s) raised %s", ev_type, exc)


async def safe_emit_thinking(on_thinking: OnThinking, chunk: str) -> None:
    if on_thinking is None or not chunk:
        return
    try:
        await on_thinking(chunk)
    except Exception as exc:  # pragma: no cover
        logger.warning("safe_emit_thinking raised %s", exc)


class EventBridge:
    """In-memory queue used by the orchestrator to bridge engine events → SSE.

    Engines push via ``await bridge.emit("status", {...})``.  The orchestrator
    pulls events with ``await bridge.drain_until(tasks)`` which yields events
    while waiting for the supplied tasks to finish, falling back to
    heartbeats during idle gaps so the SSE connection stays open.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    async def emit(self, ev_type: str, data: dict) -> None:
        await self._queue.put((ev_type, data))

    async def emit_thinking(self, chunk: str) -> None:
        await self._queue.put(("thinking", {"content": chunk}))

    def as_callback(self) -> OnEvent:
        """Return the async callback you hand to an engine's ``on_event``."""
        async def _cb(ev_type: str, data: dict) -> None:
            await self.emit(ev_type, data)
        return _cb

    def as_thinking_callback(self) -> OnThinking:
        async def _cb(chunk: str) -> None:
            await self.emit_thinking(chunk)
        return _cb

    async def drain_until(
        self,
        tasks: list[asyncio.Task[Any]],
        *,
        heartbeat_every: float = 1.0,
    ):
        """Yield (event_type, data) until every task is done, then drain rest."""
        while tasks and not all(t.done() for t in tasks):
            try:
                ev = await asyncio.wait_for(self._queue.get(), timeout=heartbeat_every)
                yield ev
            except asyncio.TimeoutError:
                yield ("heartbeat", {})
        while not self._queue.empty():
            try:
                yield self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
