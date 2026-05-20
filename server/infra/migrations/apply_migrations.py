"""Apply the SQL migrations in this directory to Supabase Postgres.

Connects directly to the Postgres pooler (PostgREST can't run DDL) using
``SUPABASE_DB_URL`` or a derived ``DATABASE_URL``. Runs each
``NNN_*.sql`` file in numeric order. Each file is executed in its own
transaction (handled by the BEGIN/COMMIT inside the file).

Usage::

    # From E:/data/server/ with .env loaded:
    python -m infra.migrations.apply_migrations
    # or
    python infra/migrations/apply_migrations.py

Required env vars (one of):
    SUPABASE_DB_URL              full postgres://… connection string
    SUPABASE_DB_PASSWORD         project DB password
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


HERE = Path(__file__).parent


def _conn_string() -> str:
    direct = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if direct:
        return direct

    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    pwd = os.environ.get("SUPABASE_DB_PASSWORD")
    if not url or not pwd:
        sys.exit(
            "Set SUPABASE_DB_URL (full DSN), or both NEXT_PUBLIC_SUPABASE_URL + "
            "SUPABASE_DB_PASSWORD. The DB password is under "
            "Supabase Dashboard → Project Settings → Database."
        )

    # url is https://<ref>.supabase.co → direct connection at
    # db.<ref>.supabase.co:5432 (no region info needed, IPv6-only on some
    # Supabase plans). If your network doesn't have IPv6 reachability, set
    # SUPABASE_DB_URL to the pooler DSN from the dashboard instead.
    m = re.match(r"https?://([a-z0-9]+)\.supabase\.co", url)
    if not m:
        sys.exit(f"unrecognized SUPABASE_URL shape: {url!r}")
    ref = m.group(1)
    return f"postgresql://postgres:{pwd}@db.{ref}.supabase.co:5432/postgres"


def main() -> None:
    try:
        import psycopg
    except ImportError:
        sys.exit("pip install 'psycopg[binary]>=3' first")

    dsn = _conn_string()
    print(f"Connecting to {dsn.split('@', 1)[1]} ...")

    files = sorted(HERE.glob("[0-9]*.sql"))
    if not files:
        sys.exit("no migration files found")

    with psycopg.connect(dsn, autocommit=True) as conn:
        for f in files:
            print(f"\n-- {f.name} -------------------------------------------")
            sql = f.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
            print(f"   applied {f.name}")

    print("\nAll migrations applied.")


if __name__ == "__main__":
    main()
