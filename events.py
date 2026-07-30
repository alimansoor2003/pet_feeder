"""
events.py
---------
Read-side queries over the event_logs table (written to by decision.py,
kind="ai", and devices.py, kind="device"). Replaces the old per-user
events.log / device_events.log text files that routes used to open and
regex-parse.
"""

import db


def recent_for_user(user_id: str, kind: str = None, limit: int = 100) -> list:
    """Most-recent-first event rows for one user, optionally filtered to
    a single kind ("ai" or "device"). Each row: {timestamp, message, kind}."""
    with db.get_conn() as conn:
        if kind:
            rows = conn.execute(
                """
                SELECT message, kind, created_at FROM event_logs
                WHERE user_id = %s AND kind = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (user_id, kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT message, kind, created_at FROM event_logs
                WHERE user_id = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
    return [
        {"timestamp": row["created_at"].isoformat(timespec="seconds"), "message": row["message"], "kind": row["kind"]}
        for row in rows
    ]


def count_recognized_for_user(user_id: str) -> int:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM event_logs WHERE user_id = %s AND kind = 'ai' AND message LIKE 'Recognized%%'",
            (user_id,),
        ).fetchone()
    return row["n"]


def count_recognized_today_for_user(user_id: str) -> int:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT count(*) AS n FROM event_logs
            WHERE user_id = %s AND kind = 'ai' AND message LIKE 'Recognized%%'
              AND created_at::date = now()::date
            """,
            (user_id,),
        ).fetchone()
    return row["n"]


def recognition_totals() -> tuple:
    """Across every user: (total_recognized, total_ignored) AI events."""
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                count(*) FILTER (WHERE message LIKE 'Recognized%%') AS recognized,
                count(*) FILTER (WHERE message LIKE 'Ignored%%') AS ignored
            FROM event_logs WHERE kind = 'ai'
            """
        ).fetchone()
    return row["recognized"], row["ignored"]


def recent_across_all_users(limit: int = 150) -> list:
    """For the admin Logs page: newest events across every user, with the
    owning user's email attached."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.message, e.kind, e.created_at, u.email AS user_email
            FROM event_logs e
            JOIN users u ON u.id = e.user_id
            ORDER BY e.created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "timestamp": row["created_at"].isoformat(timespec="seconds"),
            "message": row["message"],
            "kind": row["kind"],
            "user": row["user_email"],
        }
        for row in rows
    ]
