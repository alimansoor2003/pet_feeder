"""
serve.py - production entry point for PawSense.

Run with:  python serve.py

Serves the app with waitress, a production WSGI server: no auto-reload,
no in-browser debugger, and it handles several requests at once. Use
`python app.py` only for local development.

SECRET_KEY handling: if the environment variable isn't set, a random
key is generated once and stored in data/.secret_key (gitignored), so
login sessions survive restarts without anyone having to manage the
key by hand. Setting SECRET_KEY in the environment overrides the file.
"""
import os
import secrets

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(APP_ROOT, "data", ".secret_key")

if not os.environ.get("SECRET_KEY"):
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    if not os.path.isfile(KEY_FILE):
        with open(KEY_FILE, "w") as f:
            f.write(secrets.token_hex(32))
    with open(KEY_FILE) as f:
        os.environ["SECRET_KEY"] = f.read().strip()

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print("\n" + "=" * 60)
    print("PawSense - Smart Pet Feeder  (production server)")
    print("=" * 60)
    print(f"Serving on http://{host}:{port}")
    print("Stop with Ctrl+C")
    print("=" * 60 + "\n")
    serve(app, host=host, port=port, threads=8)
