required_templates = [
    "base.html", "login.html", "signup.html", "landing.html", "403.html",
    "user/_nav.html", "user/dashboard.html", "user/pets.html", "user/pet_edit.html",
    "user/feed.html", "user/ai.html", "user/history.html", "user/device.html",
    "admin/_nav.html", "admin/dashboard.html", "admin/users.html",
    "admin/devices.html", "admin/analytics.html", "admin/logs.html",
]

import os

missing = []
for t in required_templates:
    path = os.path.join("templates", t)
    if not os.path.exists(path):
        missing.append(t)

if missing:
    print("MISSING TEMPLATES:")
    for m in missing:
        print("  -", m)
else:
    print("All templates present ✓")