"""
pets.py
-------
Single responsibility: pet records for one user, stored in the `pets`
table (one row per pet, unique on (user_id, name)):

  image            relative path to the uploaded photo on local disk
  type, age, weight, feeding_amount
  registered       when the pet was added
  last_detected, last_fed

detector.py / identifier.py / pipeline.py only ever read the "image" key,
so none of the AI code needed to change for this extension.
"""

from datetime import datetime

import db


def load_database(user_id: str) -> dict:
    """Returns {pet_name: {...}} — same shape the old database.json had."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM pets WHERE user_id = %s", (user_id,)).fetchall()
    return {
        row["name"]: {
            "image": row["image"],
            "type": row["type"],
            "age": row["age"],
            "weight": row["weight"],
            "feeding_amount": row["feeding_amount"],
            "registered": row["registered"],
            "last_detected": row["last_detected"],
            "last_fed": row["last_fed"],
        }
        for row in rows
    }


def add_pet(user_id: str, name: str, image_rel_path: str, pet_type: str, age, weight, feeding_amount) -> None:
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO pets (user_id, name, image, type, age, weight, feeding_amount,
                               registered, last_detected, last_fed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Never', 'Never')
            """,
            (user_id, name, image_rel_path, pet_type, age, weight, feeding_amount, str(datetime.now())),
        )


def update_pet(user_id: str, name: str, pet_type: str, age, weight, feeding_amount, image_rel_path: str = None) -> bool:
    with db.get_conn() as conn:
        if image_rel_path:
            result = conn.execute(
                """
                UPDATE pets SET type = %s, age = %s, weight = %s, feeding_amount = %s, image = %s
                WHERE user_id = %s AND name = %s
                """,
                (pet_type, age, weight, feeding_amount, image_rel_path, user_id, name),
            )
        else:
            result = conn.execute(
                """
                UPDATE pets SET type = %s, age = %s, weight = %s, feeding_amount = %s
                WHERE user_id = %s AND name = %s
                """,
                (pet_type, age, weight, feeding_amount, user_id, name),
            )
    return result.rowcount > 0


def delete_pet(user_id: str, name: str) -> bool:
    with db.get_conn() as conn:
        result = conn.execute("DELETE FROM pets WHERE user_id = %s AND name = %s", (user_id, name))
    return result.rowcount > 0


def mark_detected(user_id: str, name: str, fed: bool) -> None:
    """Called by the AI pipeline result to update last_detected/last_fed."""
    now_str = datetime.now().strftime("%I:%M %p")
    with db.get_conn() as conn:
        if fed:
            conn.execute(
                "UPDATE pets SET last_detected = %s, last_fed = %s WHERE user_id = %s AND name = %s",
                (now_str, now_str, user_id, name),
            )
        else:
            conn.execute(
                "UPDATE pets SET last_detected = %s WHERE user_id = %s AND name = %s",
                (now_str, user_id, name),
            )
