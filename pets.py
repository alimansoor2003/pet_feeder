"""
pets.py
-------
Single responsibility: pet records for one user.

Each pet entry in database.json now carries the full profile the user
dashboard needs to display:
{
  "Max": {
      "image": "data/u_xxx/uploads/max_photo.jpg",
      "type": "Dog",
      "age": 3,
      "weight": 12.5,
      "feeding_amount": 80,
      "registered": "2026-06-23 ...",
      "last_detected": "Never",
      "last_fed": "Never"
  }
}

detector.py / identifier.py / pipeline.py only ever read the "image" key,
so none of the AI code needed to change for this extension.
"""

import json
import os
from datetime import datetime


def load_database(path: str) -> dict:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_database(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def add_pet(path: str, name: str, image_rel_path: str, pet_type: str, age, weight, feeding_amount) -> None:
    database = load_database(path)
    database[name] = {
        "image": image_rel_path,
        "type": pet_type,
        "age": age,
        "weight": weight,
        "feeding_amount": feeding_amount,
        "registered": str(datetime.now()),
        "last_detected": "Never",
        "last_fed": "Never",
    }
    save_database(path, database)


def update_pet(path: str, name: str, pet_type: str, age, weight, feeding_amount, image_rel_path: str = None) -> bool:
    database = load_database(path)
    if name not in database:
        return False
    database[name]["type"] = pet_type
    database[name]["age"] = age
    database[name]["weight"] = weight
    database[name]["feeding_amount"] = feeding_amount
    if image_rel_path:
        database[name]["image"] = image_rel_path
    save_database(path, database)
    return True


def delete_pet(path: str, name: str) -> bool:
    database = load_database(path)
    if name not in database:
        return False
    del database[name]
    save_database(path, database)
    return True


def mark_detected(path: str, name: str, fed: bool) -> None:
    """Called by the AI pipeline result to update last_detected/last_fed."""
    database = load_database(path)
    if name not in database:
        return
    now_str = datetime.now().strftime("%I:%M %p")
    database[name]["last_detected"] = now_str
    if fed:
        database[name]["last_fed"] = now_str
    save_database(path, database)
