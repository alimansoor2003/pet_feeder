# 🐾 PawSense — Smart AI Pet Feeder

PawSense is a full-stack smart pet feeder: an ESP32-powered device that
dispenses food only for registered pets, paired with a Flask web app for
registration, live monitoring, and feeding history.

<img width="500" height="300" alt="giphy" src="https://github.com/user-attachments/assets/7b5e55c8-862b-463a-b5ce-bc485fa604a2" />

Started as a summer training project; now deployed and running on the
public internet rather than just a laptop on the home WiFi.

Please note: It may take some time to start because it is a free tier.
**Live:** https://pawsense-ho4m.onrender.com

---

## What it does

1. A camera (currently a laptop webcam standing in for the onboard ESP32
   camera) captures a frame.
2. **YOLO** (`yolov8n`) detects whether a cat or dog is present in the
   frame, and crops it out.
3. A **ViT** embedding model (`timm`, `vit_small_patch16_224`) compares
   that crop against your registered pets' photos to identify *which*
   pet it is, by cosine similarity.
4. If the best match clears the similarity threshold (0.70), the
   **decision engine** approves feeding and queues a feed command.
5. The **ESP32** polls for commands every 5 seconds, picks up the feed
   command, runs the feed motor for a set portion, then acknowledges it.
6. Every detection and feeding is logged to Postgres and viewable in the
   dashboard.

Feeding can also be triggered manually at any time from the web
dashboard, independent of the AI pipeline.

---

## Features

- **Pet registration** — upload a photo per pet; the original is kept
  untouched and used directly for AI matching
- **AI recognition** — YOLO detection + ViT identification, with a
  configurable similarity threshold in `identifier.py`
- **Manual and automatic feeding** — a "Feed Now" button, and/or the AI
  pipeline triggering feeds on recognized pets
- **Live camera preview** — MJPEG stream from the webcam watcher (port
  5001), embedded in the AI Recognition page, plus a polled live event
  feed of what it's been detecting
- **Per-user accounts** — signup/login, isolated data per user (own
  pets, own device, own history — nothing shared between accounts)
- **Self-service device claiming** — the customer claims a feeder with
  the Device ID + Setup Key printed on the unit's sticker; no admin
  involvement
- **Admin panel** — separate role: manage users (block/unblock/delete),
  provision new devices, view all devices, basic analytics, and logs
- **Feeding history** — filtered to show only meaningful events
  (feedings and unrecognized-animal detections — empty-frame noise is
  excluded)
- **Device online/offline tracking** — via ESP32 heartbeats every 30s,
  with a grace period to avoid false "offline" flapping

---

## Project structure

```
pet_feeder/
├── app.py                    # Flask app factory (development server)
├── serve.py                  # Production entry point (waitress)
├── db.py                     # Postgres connection pool + schema
├── auth.py                   # Accounts, roles (user/admin), sessions
├── pets.py                   # Pet CRUD per user
├── devices.py                # Device CRUD, heartbeat/command state
├── events.py                 # Event log (AI + device) per user
├── create_admin.py           # CLI — the only way to create an admin account
├── migrate_json_to_postgres.py  # One-off import of pre-Postgres JSON data
├── check_templates.py        # Sanity-check that templates render
├── webcam_watcher.py         # Laptop webcam stand-in for the ESP32 camera
├── detector.py               # YOLO — is there an animal, and where?
├── identifier.py             # ViT embeddings — which registered pet is it?
├── decision.py               # Feed / don't feed logic
├── pipeline.py               # Wires detector → identifier → decision
├── input_adapter.py          # Normalizes any input into a PIL.Image
├── render.yaml               # Render Blueprint (deployment)
├── .env.example              # SECRET_KEY + DATABASE_URL template
├── requirements.txt
├── esp32/
│   └── pawsense_feeder.ino   # Firmware: captive-portal WiFi + feed loop
├── routes/
│   ├── auth_routes.py        # /signup, /login, /logout
│   ├── user_routes.py        # dashboard, pets, feeding, AI, history, device
│   ├── admin_routes.py       # admin dashboard, users, devices, analytics, logs
│   └── api_routes.py         # ESP32-facing: heartbeat, data, commands, ack
└── templates/                # Jinja2 templates (landing, user, admin)
```

`app.py` is an app factory only — all route logic lives in `routes/`.
Every module reaches storage through `db.py`, so nothing else needs to
know it's Postgres underneath.

---

## Storage

All structured data — users, pets, devices, and event history — lives in
**Postgres**. The only thing still on local disk is uploaded pet photos
(`data/<user_id>/uploads/`).

Tables are created automatically on startup by `db.init_db()`, so an
empty database is fine — there's no manual schema step.

If you have data from before the Postgres migration (`users.json`,
`data/<user_id>/database.json`, `device.json`,
`data/provisioned_devices.json`, `*.log`), import it once with
`migrate_json_to_postgres.py`. It's safe to re-run — existing rows are
left alone (`ON CONFLICT DO NOTHING`), and event-log import is skipped
for any user who already has history. Note that it iterates users found
in `users.json`, so an orphaned `data/<user_id>/` directory with no
matching user entry is ignored.

---

## Setup

### 1. Requirements

- Python 3.10+
- A Postgres database (local, or a free Neon/Supabase project)
- Arduino IDE set up for **ESP32** boards (for the firmware side)

### 2. Install dependencies

```powershell
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### 3. Configure

Copy `.env.example` to `.env` and fill in:

- `SECRET_KEY` — any long random string (session signing)
- `DATABASE_URL` — e.g. `postgresql://user:password@localhost:5432/pawsense`

### 4. Run the app

```powershell
venv\Scripts\python app.py
```

Use `app.py` for development only. `serve.py` is the production entry
point — waitress, no debugger, handles concurrent requests.

### 5. Create an admin account

Signup always creates a normal `user` account — admins can only be
created via this script:

```powershell
venv\Scripts\python create_admin.py
```

There is deliberately no web form for this — see the note in
`create_admin.py` about why shell access is the right trust boundary.

### 6. (Optional) Run the webcam watcher for live AI monitoring

```powershell
venv\Scripts\python webcam_watcher.py your-email@example.com
```

This streams your laptop's webcam on port 5001 and runs frames through
the same AI pipeline the ESP32 would use, as a stand-in while the
onboard camera is being sourced.

### 7. Flash the ESP32

Nothing network-specific gets flashed. The **only** thing you edit per
unit is the identity block (from Admin → Devices → "+ Provision New
Device" — the same pair printed on the unit's sticker) and the server
URL, which is identical for every unit:

```cpp
const char* DEVICE_ID   = "dev_...";
const char* API_KEY     = "XXXX-XXXX-XXXX";
const char* SERVER_BASE = "https://your-domain";
```

Libraries needed (Arduino IDE → Library Manager): **WiFiManager** by
tzapu, **ArduinoJson** by Benoit Blanchon. Board: *ESP32 Dev Module*.

**Onboarding a unit (no re-flashing, any house, any WiFi):**

1. Plug the feeder in. On first boot it broadcasts a hotspot named
   `PawSense-Setup`.
2. Connect a phone to it — a captive-portal setup page pops up. Pick the
   home WiFi, enter the password. The feeder remembers it.
3. Claim the feeder on the website with the Device ID + Setup Key from
   the sticker. Done.

Moving house: hold the BOOT button for 5 seconds and repeat step 2.

**Wiring:**
Will update soon.
## Deploying (Render + Neon, both free)

`render.yaml` is a Render Blueprint for the web service. The database
lives on Neon rather than Render's own Postgres, because Render's free
Postgres tier auto-deletes itself after ~30 days — Neon's free tier
doesn't expire.

1. **Database first — Neon:** create a free project at
   [neon.tech](https://neon.tech) and copy the **pooled** connection
   string (starts with `postgresql://`, host ends in `-pooler...`).
   Supabase works the same way.
2. **Push this repo to GitHub.**
3. **Render:** dashboard → **New +** → **Blueprint** → pick this repo.
   Render reads `render.yaml` and shows one free web service
   (`pawsense`). It prompts for `DATABASE_URL` since the blueprint marks
   it `sync: false` — paste the Neon string. `SECRET_KEY` is generated
   automatically.
4. First boot creates the schema by itself. Then create your admin login
   by running `create_admin.py` locally against the Neon URL — see
   below.

Because `db.init_db()` runs at import time, a missing or wrong
`DATABASE_URL` fails the boot outright — the service returns 502 rather
than starting up broken. A 200 on the landing page means Postgres is
genuinely connected.




### Rotating the database password

If the connection string leaks (pasted into a chat, committed, shared in
a screenshot), treat it as compromised — `neondb_owner` is the owner
role on the database:

1. Neon console → **Roles** → `neondb_owner` → **Reset password**
2. Render → `pawsense` → **Environment** → update `DATABASE_URL` → save
   (this triggers a redeploy)
3. Clear local shell history:
   `Remove-Item (Get-PSReadlineOption).HistorySavePath`

Do these in order — the live site keeps using the old password until
step 2 lands, and starts failing once step 1 is done.

Device API keys are per-unit and issued at provisioning time; rotate one
by re-provisioning the device and re-flashing that unit's identity block.

---

## Known limitations

**Memory on the free tier.** The import chain
`routes/user_routes.py → pipeline.py → detector.py / identifier.py`
loads YOLO (`ultralytics`) and the ViT model (`timm`) **eagerly at
startup**, not lazily. Both are small variants and it does boot within
Render's free 512MB, but there's not much headroom. Intermittent 502s
after idle periods are a cold-start OOM, not a database problem. Two
fixes, cheapest first: make the CV imports lazy (move them inside the
route handlers), or switch `plan: free` to `plan: starter` in
`render.yaml`.

**Cold starts.** The free tier spins down after ~15 minutes idle, so the
first request after a quiet period takes ~30–50s to wake up.

**Uploaded photos are ephemeral.** Pet photos live on local disk under
`data/<user_id>/uploads/`. Render wipes local disk on every
deploy/restart, so photos won't survive those unless you attach a
persistent disk or move to object storage (S3, Cloudinary, etc.) —
worth revisiting before relying on this with real hardware.

**Camera is still off-device.** Recognition runs on a laptop webcam via
`webcam_watcher.py`; the ESP32 only executes feed commands. When the
onboard camera lands, the ESP32 can post frames to
`/api/device/<id>/data` instead, with no other code changes.

**Detection is cats and dogs only.** `detector.py` filters to those two
COCO classes; anything else reads as an empty frame.

**Single camera per household.** Multi-camera setups aren't supported.

**Dispense timing is hand-tuned.** Motor run duration is set in the
firmware per physical build — there's no calibration UI.

---

## Credits

Built during a summer training program.
