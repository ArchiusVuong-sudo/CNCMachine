"""Lazy Supabase client factory.

The pipeline only needs Supabase to read per-user shop catalog rows
(machines, tooling, labor, material stock). We keep the import lazy so the
server still starts in a bare dev environment without the ``supabase``
package installed — engines fall back to vendored defaults.

Usage::

    client = get_supabase_client()
    if client is not None:
        rows = client.table("a4_machines").select("*").execute()
        # NOTE: ``a4_machines.user_id`` was dropped in migration 002 — catalog
        # tables are now globally readable; do NOT filter by user_id here.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger("cncserver.infra.supabase")

_CLIENT: Any = None
_LOCK = threading.Lock()
_MISSING_CREDS_WARNED = False


def _read_credentials() -> tuple[str | None, str | None]:
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
    )
    return url, key


def is_configured() -> bool:
    url, key = _read_credentials()
    return bool(url and key)


def get_supabase_client() -> Any | None:
    """Return a cached Supabase client, or ``None`` if env / package missing.

    Service-role key bypasses RLS so the pipeline can read every user's
    catalog rows. Returns the same client on repeated calls; callers should
    treat ``None`` as "no DB available" and use built-in defaults.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    url, key = _read_credentials()
    if not url or not key:
        global _MISSING_CREDS_WARNED
        if not _MISSING_CREDS_WARNED:
            logger.info("supabase: NEXT_PUBLIC_SUPABASE_URL / SERVICE_ROLE_KEY missing — using defaults")
            _MISSING_CREDS_WARNED = True
        return None

    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT
        try:
            from supabase import create_client
        except ImportError:
            logger.warning("supabase: 'supabase' package not installed — install with pip install supabase")
            return None
        try:
            _CLIENT = create_client(url, key)
            logger.info("supabase: connected to %s", url)
        except Exception as exc:
            logger.warning("supabase: create_client failed (%s) — using defaults", exc)
            _CLIENT = None
    return _CLIENT


def reset_client() -> None:
    """Drop the cached client. Used in tests to force re-resolution."""
    global _CLIENT
    with _LOCK:
        _CLIENT = None
