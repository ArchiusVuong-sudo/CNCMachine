"""Infrastructure adapters — anything that talks to a real network or DB.

Engines import only from :mod:`server.core` (kernel) and :mod:`server.infra`
(adapters). This keeps the engine code unit-testable: swap an infra module
for a fake and the engine doesn't notice.

Currently provided:
  * :mod:`server.infra.materials` — static material database + matcher.
  * :mod:`server.infra.supabase`  — lazy client factory for the user catalog.
  * :mod:`server.infra.llm`       — Qwen3-VL streaming chat client.
"""
from __future__ import annotations
