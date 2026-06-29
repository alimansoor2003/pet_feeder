"""
create_admin.py
-----------------
The ONLY way to create an admin account. There is no web form for this —
on purpose. Run from the terminal:

    python create_admin.py

It will prompt for name, email, and password, then create a user with
role="admin" directly via auth.create_user(). Anyone who can run this
script already has shell access to your server, which is the correct
trust boundary for "who can create an admin."
"""

import getpass
import auth


def main():
    print("=== Create PawSense Admin Account ===\n")
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip()
    password = getpass.getpass("Admin password (min 6 chars): ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("\n✗ Passwords don't match. Aborted.")
        return

    user, error = auth.create_user(name, email, password, role="admin")
    if error:
        print(f"\n✗ {error}")
        return

    import devices
    paths = auth.user_paths(user["id"])
    devices.create_default_device(paths["device"])

    print(f"\n✓ Admin account created: {user['email']} (role={user['role']})")
    print("  You can now log in at /login and you'll be sent to /admin/dashboard.")


if __name__ == "__main__":
    main()
