"""
decision.py
-----------
Decision engine — intentionally a thin stub for the MVP, designed to
grow without touching detector.py, identifier.py, or app.py.

For now it just logs every event and returns "allow_feeding" for any
recognized pet. Real hunger / schedule / weight logic plugs in here
later.
"""

import datetime

DEFAULT_LOG_PATH = "events.log"


def _log_event(message: str, log_path: str = DEFAULT_LOG_PATH) -> None:
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def decide(pet_name: str, confidence: float, log_path: str = DEFAULT_LOG_PATH) -> dict:
    """
    Called when a pet was successfully identified.

    FUTURE: check feeding schedule, hunger level, last-fed timestamp,
    target weight, etc. before allowing feeding. Right now every
    recognized pet is allowed to feed.
    """
    _log_event(f"Recognized '{pet_name}' (confidence={confidence:.2f}) -> feeding allowed", log_path)
    return {
        "action": "allow_feeding",
        "pet": pet_name,
        "confidence": round(confidence, 2),
    }


def ignore(reason: str, confidence: float = 0.0, log_path: str = DEFAULT_LOG_PATH) -> dict:
    """
    Called when no pet was recognized — either no animal was detected,
    or an animal was detected but didn't match anyone in the database.
    """
    _log_event(f"Ignored event: {reason} (confidence={confidence:.2f})", log_path)
    return {
        "action": "ignore",
        "reason": reason,
        "confidence": round(confidence, 2),
    }