"""
decision.py
-----------
Decision engine — intentionally a thin stub for the MVP, designed to
grow without touching detector.py, identifier.py, or app.py.

For now it just logs every event (as a kind="ai" row in event_logs,
scoped to the user whose pipeline produced it) and returns
"allow_feeding" for any recognized pet. Real hunger / schedule / weight
logic plugs in here later.
"""

import db


def _log_event(user_id: str, message: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO event_logs (user_id, kind, message) VALUES (%s, 'ai', %s)",
            (user_id, message),
        )


def decide(pet_name: str, confidence: float, user_id: str) -> dict:
    """
    Called when a pet was successfully identified.

    FUTURE: check feeding schedule, hunger level, last-fed timestamp,
    target weight, etc. before allowing feeding. Right now every
    recognized pet is allowed to feed.
    """
    _log_event(user_id, f"Recognized '{pet_name}' (confidence={confidence:.2f}) -> feeding allowed")
    return {
        "action": "allow_feeding",
        "pet": pet_name,
        "confidence": round(confidence, 2),
    }


def ignore(reason: str, user_id: str, confidence: float = 0.0) -> dict:
    """
    Called when no pet was recognized — either no animal was detected,
    or an animal was detected but didn't match anyone in the database.
    """
    _log_event(user_id, f"Ignored event: {reason} (confidence={confidence:.2f})")
    return {
        "action": "ignore",
        "reason": reason,
        "confidence": round(confidence, 2),
    }