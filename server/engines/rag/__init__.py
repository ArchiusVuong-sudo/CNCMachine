"""RAG engine — drop-in alternative to the agentic engine for time/cost
estimation.

Architecture (deletable as a unit — no cross-engine imports):

    pgvector  ──►  retriever  ──►  prompts  ──►  generator
                       │                              │
                       └─────► planner ◄──────────────┘
                                  │
                                  ├──► tool_snap
                                  └──► projection
                                  │
                                  ▼
                            coordinator
                                  │
                                  ▼
                             dispatcher  ──►  ProcessPlan

The dispatcher's public surface matches
``server.engines.agentic.dispatcher.dispatch`` so the pipeline orchestrator
can swap engines via a single ``if/elif`` branch.

Ingestion is offline and lives in :mod:`server.engines.rag.ingestion`. Run
``python -m server.engines.rag.ingestion.build_index --rebuild-all`` after
KB edits.
"""

from .dispatcher import dispatch

__all__ = ["dispatch"]
