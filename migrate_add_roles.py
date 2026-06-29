"""
One-time migration: adds role="user" to any account created before
roles existed in the schema. Safe to run multiple times — it only
touches accounts missing the field.
"""
import json

with open("users.json", "r") as f:
    users = json.load(f)

fixed = 0
for email, user in users.items():
    if "role" not in user:
        user["role"] = "user"
        fixed += 1

with open("users.json", "w") as f:
    json.dump(users, f, indent=2)

print(f"✓ Fixed {fixed} account(s) missing a role.")
print(f"  Total accounts: {len(users)}")