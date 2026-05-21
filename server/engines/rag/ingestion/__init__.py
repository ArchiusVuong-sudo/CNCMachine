"""Ingestion CLI + helpers for the RAG engine.

Top-level entry point:

    python -m server.engines.rag.ingestion.build_index --rebuild-all

This module is intentionally not loaded by the request-handling path —
ingestion runs offline whenever the KB changes, not on every analysis.
"""
