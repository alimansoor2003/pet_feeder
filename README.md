# PawSense — Smart Pet Feeder

Flask web app for a camera-based smart pet feeder (ESP32 hardware, YOLO
detection, embedding-based pet identification). All structured data —
users, pets, devices, and event history — lives in Postgres. The only
thing still stored on local disk is uploaded pet photos
(`data/<user_id>/uploads/`).

## Local setup

1. Create a virtualenv and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in:
   - `SECRET_KEY` — any long random string (session signing).
   - `DATABASE_URL` — a Postgres connection string, e.g.
     `postgresql://user:password@localhost:5432/pawsense`.
3. Run it:
   ```
   venv\Scripts\python app.py
   ```
   Tables are created automatically on startup (`db.init_db()`), so an
   empty database is fine — no manual schema step needed.
4. Create your first admin account:
   ```
   venv\Scripts\python create_admin.py
   ```

### Migrating existing JSON data

If you have data from before the Postgres migration (`users.json`,
`data/<user_id>/database.json`, `data/<user_id>/device.json`,
`data/provisioned_devices.json`, `*.log` files), import it once with:

```
venv\Scripts\python migrate_json_to_postgres.py
```

It's safe to re-run — existing rows are left alone (`ON CONFLICT DO
NOTHING`), and event-log import is skipped for any user who already has
history in Postgres.

## Deploying (Render + Neon, both free)

`render.yaml` in the repo root is a Render Blueprint for the web
service. The database lives on Neon instead of Render's own Postgres,
because Render's free Postgres tier auto-deletes itself after ~30 days
— Neon's free tier doesn't expire.

1. **Database first — Neon:** create a free project at
   [neon.tech](https://neon.tech), copy the connection string it gives
   you (starts with `postgresql://...`). (Supabase works the same way
   if you'd rather use that.)
2. **Push this repo to GitHub** (if not already).
3. **Render:** dashboard → **New +** → **Blueprint** → pick this repo.
   Render reads `render.yaml` and shows a plan: one free web service
   (`pawsense`). It'll prompt you for `DATABASE_URL` since the
   blueprint marks it `sync: false` — paste in the Neon connection
   string from step 1. `SECRET_KEY` is generated for you automatically.
4. Once it's live, open the web service's **Shell** tab (in the Render
   dashboard) and run:
   ```
   python create_admin.py
   ```
   to create your first admin login. If you have existing data from
   before this migration, also run `python migrate_json_to_postgres.py`
   there first (you'd need to get the old `users.json`/`data/` files
   onto that instance, e.g. via git or the shell's upload — ask if you
   need help with that part).

**About the free web service plan:** this app loads a YOLO model
(`ultralytics`) and a ViT embedding model (`timm`) into memory. Both
are the small/nano variants, so it's worth trying on Render's free
512MB tier first — if it crashes from memory pressure, that shows up
clearly in the Render logs, and the fix is switching `plan: free` to
`plan: starter` (~$7/mo) in `render.yaml`. The free tier also spins
down after 15 minutes idle, so the first request after a quiet period
takes ~30-50s to wake back up.

**Known limitation:** uploaded pet photos still live on local disk
under `data/<user_id>/uploads/`. Render wipes local disk on every
deploy/restart, so photos won't survive those unless you attach a
persistent disk or move to object storage (S3, Cloudinary, etc.) —
something to revisit before relying on this for real hardware in
production.
