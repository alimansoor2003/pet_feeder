"""
db.py
-----
Single Postgres connection pool + schema for the whole app, replacing
the old users.json / data/<user_id>/*.json / *.log file storage.

Every other module (auth.py, devices.py, pets.py, decision.py,
identifier.py) goes through the helpers here instead of touching
files directly, so none of them need to know this is Postgres.

Configuration: set DATABASE_URL (e.g. postgres://user:pass@host:5432/dbname).
Render/Railway/Heroku-style hosts inject this automatically once you
attach a Postgres addon; for local dev, set it in .env.
"""

import atexit
import os
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. PawSense now stores all data in Postgres — "
        "set DATABASE_URL to a postgres:// connection string (see .env.example)."
    )

# Some hosts (Render, Heroku) hand out "postgres://" URLs; psycopg wants
# either scheme, so no rewrite is actually required, but a few older
# libraries insisted on "postgresql://" — normalize just in case.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

_pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=False)
atexit.register(_pool.close)


@contextmanager
def get_conn():
    """Borrow a pooled connection. Commits on success, rolls back on error."""
    if _pool.closed:
        _pool.open()
    with _pool.connection() as conn:
        yield conn


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call on every startup."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                user_id TEXT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                api_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'offline',
                food_level INTEGER NOT NULL DEFAULT 100,
                last_connection TIMESTAMPTZ,
                pending_feed BOOLEAN NOT NULL DEFAULT FALSE,
                provisioned BOOLEAN NOT NULL DEFAULT FALSE,
                feeding_schedule TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provisioned_devices (
                device_id TEXT PRIMARY KEY,
                setup_key TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                claimed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                claimed_at TIMESTAMPTZ
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                image TEXT,
                type TEXT,
                age TEXT,
                weight TEXT,
                feeding_amount TEXT,
                registered TEXT,
                last_detected TEXT,
                last_fed TEXT,
                UNIQUE (user_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_logs (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS event_logs_user_idx ON event_logs (user_id, created_at DESC)")
