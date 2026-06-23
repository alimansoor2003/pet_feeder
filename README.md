# Smart Pet Feeder — MVP

A working implementation of the workflow you specified: web registration →
image/frame input → YOLO detection → embedding-based identification →
decision engine, with strict separation of concerns so video/camera input
can be added later with zero changes to the core pipeline.

## Project layout

```
pet_feeder/
├── app.py             # Web layer ONLY — Flask routes, forms, uploads
├── detector.py         # YOLO ONLY — is there a dog/cat, and where?
├── identifier.py       # Matching ONLY — whose pet is it?
├── decision.py         # Decision engine — what should the feeder do?
├── pipeline.py         # Wires detector → identifier → decision behind
│                       #   one function: pipeline(image)
├── input_adapter.py    # Converts any input source (upload, video frame,
│                       #   camera frame) into a PIL.Image before it
│                       #   reaches the pipeline
├── database.json       # Storage ONLY — { "Bella": {"image": "..."} }
├── uploads/             # Saved pet photos
├── templates/           # index.html, register.html, detect.html
└── requirements.txt
```

This mirrors your design rules directly:

- **Separation of concerns** — `detector.py` never imports `identifier.py`
  or Flask; `identifier.py` never imports YOLO; `app.py` never imports
  `torch` or `ultralytics` directly, only `pipeline.py`.
- **Input abstraction rule** — every caller eventually does
  `image -> pipeline(image)`. `input_adapter.py` already has stubs for
  video frames and camera streams (`from_video_frame`, `from_camera_stream`)
  that return the same `PIL.Image` type an upload does, so when you wire in
  a camera later, `pipeline.py`, `detector.py`, and `identifier.py` don't
  change at all.
- **Device rule** — `DEVICE = "cpu"` is set explicitly in both
  `detector.py` and `identifier.py`, and nothing ever calls `.cuda()`.

## How the pipeline works

1. **Register** (`/register`): name + photo → saved to `uploads/`, path
   stored in `database.json`.
2. **Detect** (`/detect`, or later a camera loop): image → `pipeline(image)`:
   - `detector.py` runs YOLOv8n (COCO classes 15=cat, 16=dog) and returns
     `"dog"`, `"cat"`, or `"none"` plus a crop of the detected animal.
   - If an animal was found, `identifier.py` embeds the crop with a
     ResNet18 (classification head removed) and compares it via cosine
     similarity against every registered pet's embedding. Best match above
     `0.6` similarity → pet name; otherwise → `"Unknown"`.
   - `decision.py` logs the event to `events.log` and returns
     `allow_feeding` for a recognized pet, or `ignore` otherwise. This is
     where hunger/schedule/weight checks will plug in later — nothing else
     needs to change.

## Running it

```bash
cd pet_feeder
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`. The first run will download the
`yolov8n.pt` weights and ResNet18 weights automatically (needs internet
access once).

## Extending to camera/video later

When you're ready to move beyond uploaded images:

1. Write a small loop that grabs a frame (e.g. via `cv2.VideoCapture`) as
   an `np.ndarray`.
2. Call `input_adapter.from_camera_stream(frame)` to get a `PIL.Image`.
3. Call `pipeline(image)` — identical call to what `app.py` already makes.

No changes to `detector.py`, `identifier.py`, `decision.py`, or
`pipeline.py` are required, which is the guarantee the input abstraction
rule was meant to provide.

## Notes / things to harden before real deployment

- `app.secret_key` is a placeholder — set a real one via environment
  variable.
- There's no auth on `/register` — anyone who can reach the server can add
  pets.
- The embedding cache in `identifier.py` is in-memory only; for a large
  pet roster you'd want to persist embeddings to disk instead of
  recomputing on first use after a restart.
- `SIMILARITY_THRESHOLD = 0.6` in `identifier.py` is a starting point —
  tune it against real photos of your pets.
