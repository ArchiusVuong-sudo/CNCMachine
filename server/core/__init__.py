"""Cross-cutting kernel.

The `core` package holds infrastructure that every engine needs: settings,
structured logging, the SSE event bus contract, a small HTTP helper, a
per-analysis trace writer, and the Pydantic schemas that form the
inter-engine contracts.

Nothing here knows about CNC domain logic; the engines depend on `core`,
never the other way around.
"""
