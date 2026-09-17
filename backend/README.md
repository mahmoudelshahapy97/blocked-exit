# Blocked Exit Detection — FastAPI Backend

Real-time emergency-exit blockage detection for InsightEye. Monitors exits over
RTSP, decides whether each one is obstructed, quantifies **how much of the exit
is still accessible**, and alerts only when a blockage genuinely persists.

Every verdict is a full picture, not a boolean:

```json
{
  "state": "PARTIAL",
  "accessibility_pct": 88.5,
  "blocked": true,
  "blocked_duration_s": 30.2,
  "blocking_objects": [{ "label": "chair", "track_id": 7, "area_pct": 54.2 }],
  "risk_score": 47.7,
  "risk_level": "MEDIUM",
  "recommended_action": "Inspect the exit and remove the obstruction"
}
```

## Two detection strategies, one interface

| Strategy | How it decides | When to use |
|---|---|---|
| **`zone_based`** (default) | YOLO11(-seg) detects obstacles; the union of their masks is intersected with the operator-drawn door polygon. `accessible % = 100 − occupied %` | Works immediately with pretrained COCO weights. Names what is blocking the exit. |
| **`door_centric`** | A door-only detector reports the *visible* door; `accessible % = area(current bbox) / area(reference bbox)` | Generalises to obstacle types never seen in training. Needs door weights + a reference capture. |

`door_centric` implements the ICAART 2026 method (Talebi et al., *Real Time Exit
Blockage Detection via Door-Centric Change Monitoring for Emergency Evacuation*
— `../143129.pdf`, §3 and §4.3.2). Strategy is chosen per camera; if the
selected one is unavailable (no door weights yet), the registry falls back to
`DEFAULT_STRATEGY` and keeps serving instead of erroring.

## Pipeline

```
RTSP ─▶ frame throttle ─▶ YOLO11 + ByteTrack ─▶ occupancy vs door region
        (PROCESS_FPS)                              │
                                                   ▼
                                     temporal filter (debounce + hysteresis)
                                                   │
                                    ┌──────────────┼──────────────┐
                                    ▼              ▼              ▼
                              risk scoring    blockage events   alerts
                                    │          (PostgreSQL)   (webhook/email)
                                    ▼
                          annotated snapshot / MJPEG
```

One thread per camera; workers never touch the database. They publish messages
that a single consumer task drains on the event loop, which owns all writes.

## Layout

```
app/
├── main.py            FastAPI app, lifespan, router mount
├── api/
│   ├── deps.py        DB session, stream manager, API-key guard
│   └── routes/        health, cameras, monitoring, events, alerts, analytics
├── core/              config.py, database.py, enums.py, logging.py, exceptions.py
├── models/            SQLAlchemy: Camera, BlockageEvent, Alert
├── schemas/           Pydantic: camera, detection, event, analytics
├── services/
│   ├── detector/      base.py (contract), zone_based.py, door_centric.py, registry.py
│   ├── model_loader.py    YOLO loading (shared vs per-worker for tracker isolation)
│   ├── stream_worker.py   per-camera capture → infer → track → emit
│   ├── stream_manager.py  worker lifecycle, supervision, thread→loop persistence bridge
│   ├── temporal.py        debounce/hysteresis state machine
│   ├── risk.py            0–100 risk score
│   ├── alerting.py        webhook + SMTP, duration gate, cooldown
│   ├── annotator.py       explainable overlays
│   ├── retention.py       expire old events, alerts and snapshots
│   └── analytics.py       aggregation queries
├── static/            zone-editor.html — draw the exit region in a browser
└── utils/             geometry.py, video.py, image.py, timing.py
```

## Quick start

Requires **Python 3.13** (torch/ultralytics wheels) and Docker for Postgres.

```bash
cd "features/blocked&exit/backend"      # quote the path — it contains '&'
py -3.13 -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
cp .env.example .env

docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload
```

Open <http://localhost:8000/docs>. YOLO11 weights download automatically into
`models/` on first start.

Full stack in Docker instead: `docker compose up` (set `DATABASE_URL` to the
`postgres` service host — the commented line in `.env.example`).

> **Ports.** `POSTGRES_PORT` and `API_PORT` in `.env` set the published host
> ports; change them if 5432/8000 are taken. The compose project is named
> `blocked-exit` so it cannot collide with another stack.
>
> **Windows + Docker in WSL2** (no Docker Desktop): `localhost:5432` from
> Windows may be refused because WSL localhost forwarding is unreliable. Point
> `DATABASE_URL` at the WSL IP instead — `wsl hostname -I` — or run the API in
> compose too, where it reaches Postgres by service name.

## Register an exit and start monitoring

`rtsp_url` also accepts a local video file, so the pipeline can be exercised
without a camera.

```bash
curl -X POST localhost:8000/api/v1/cameras -H "Content-Type: application/json" -d '{
  "name": "Exit A - Main Corridor",
  "location": "Building 1, Floor 1",
  "rtsp_url": "rtsp://user:pass@10.0.0.5:554/stream1",
  "enabled": true
}'

curl -X POST localhost:8000/api/v1/monitoring/1/start
curl localhost:8000/api/v1/monitoring/1/status
curl localhost:8000/api/v1/monitoring/1/snapshot -o exit.jpg   # annotated frame
```

Enabled cameras restart automatically when the API restarts.

## Draw the exit region

Open **<http://localhost:8000/api/v1/cameras/1/zone-editor>** and click the
corners of the doorway on a live frame. Drag a point to adjust it, right-click
or <kbd>Ctrl</kbd>+<kbd>Z</kbd> to undo, <kbd>Esc</kbd> to start over, then
Save. The saved region is applied to the running worker immediately and the
panel shows the resulting verdict.

The page is plain HTML served from `app/static/` — no build step, no CDN, so it
works on an air-gapped site network.

Nothing forces you through the UI. The endpoint takes pixel coordinates
together with the frame they were measured on, and normalizes them:

```bash
curl -X PUT localhost:8000/api/v1/cameras/1/door-polygon \
  -H "Content-Type: application/json" -d '{
  "door_polygon": [[576,162],[1344,162],[1344,1026],[576,1026]],
  "frame_width": 1920, "frame_height": 1080
}'

# ...or send normalized [0,1] points directly:
curl -X PUT localhost:8000/api/v1/cameras/1/door-polygon \
  -H "Content-Type: application/json" -d '{
  "door_polygon": [[0.30,0.15],[0.70,0.15],[0.70,0.95],[0.30,0.95]]
}'

curl localhost:8000/api/v1/cameras/1/door-polygon/preview -o zone.jpg  # confirm it
```

Regions are **stored normalized**, so one survives a camera being swapped for
another with a different resolution. With no polygon set, the whole frame is
treated as the exit.

To serve a local clip over real RTSP:

```bash
docker compose --profile rtsp up -d mediamtx
ffmpeg -re -stream_loop -1 -i clip.mp4 -c copy -f rtsp rtsp://localhost:8554/exitA
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/health/ready` | liveness; DB, models, per-worker health |
| POST/GET/PATCH/DELETE | `/cameras`, `/cameras/{id}` | camera CRUD |
| PUT | `/cameras/{id}/door-polygon` | set the exit region (pixels or normalized) |
| GET | `/cameras/{id}/zone-editor` · `/calibration-frame` · `/door-polygon/preview` | draw the region, fetch a clean still, confirm what was stored |
| POST | `/cameras/{id}/reference` | capture the unobstructed door (door-centric calibration) |
| POST | `/monitoring/{id}/start` · `/stop` · `/restart` | worker lifecycle |
| GET | `/monitoring/status` · `/monitoring/{id}/status` | live verdicts |
| GET | `/monitoring/{id}/snapshot` · `/stream` | annotated JPEG / MJPEG |
| GET | `/events`, `/events/{id}` | blockage history |
| GET/POST | `/alerts`, `/alerts/{id}/ack`, `/alerts/test` | alert log, acknowledge, delivery test |
| GET | `/analytics/summary` · `/most-blocked` · `/{id}/timeline` · `/daily-report` | dashboard data |

All under `/api/v1`. Set `API_KEY` in `.env` to require an `X-API-Key` header.

## Tuning

| Setting | Effect |
|---|---|
| `CLEAR_MIN_PCT` / `FULL_MAX_PCT` | CLEAR / PARTIAL / FULL bands (default ≥85% / <40%) |
| `CONFIRM_SECONDS` | how long an obstruction must persist before it is believed — this is what ignores passers-by |
| `CLEAR_SECONDS` | hysteresis before declaring the exit usable again |
| `PROCESS_FPS` | frames analysed per second per camera |
| `ALERT_MIN_DURATION_S` | blockage must last this long before anyone is notified |
| `ALERT_COOLDOWN_S` | silence window per camera; escalation (PARTIAL→FULL) bypasses it |
| `USE_SEGMENTATION` | masks measure partial obstruction accurately; boxes are faster |
| `OBSTACLE_CLASSES` | COCO ids treated as obstacles |

Every threshold can be overridden per camera (`clear_min_pct`, `confirm_seconds`,
`process_fps`, …); `NULL` inherits the global value.

## Enabling door-centric detection

1. Train YOLO11s on a door dataset (the paper used 648 door images × 9
   synthetic blockage variants, annotating only the *visible* door region).
2. Put the weights in `models/` and set `DOOR_MODEL_PATH=door_yolo11s.pt`.
3. `POST /cameras/{id}/reference` while the exit is clear.
4. `PATCH /cameras/{id}` with `{"strategy": "door_centric"}`.

With `DOOR_CENTRIC_EXPLAIN=true` the zone-based detector runs alongside it purely
to name the obstacles — the verdict still comes from the door geometry.

## Performance

Measured here on CPU (no usable GPU): **~3.2 fps, 256 ms/frame** with
`yolo11n-seg` at 640px, one camera, `PROCESS_FPS=4`. That is ample — exits are
monitored at a few frames per second, not 30.

For edge deployment, the paper reports large gains from exporting the model
(Raspberry Pi 5: PyTorch 0.75 fps → NCNN 4.84 → OpenVINO 5.78, with
mAP50-95 unchanged):

```bash
yolo export model=models/yolo11n-seg.pt format=openvino
# then set MODEL_PATH / SEG_MODEL_PATH to the exported directory
```

CUDA is only worth it with a modern GPU — set `DEVICE=cuda`.

## Running in production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The overlay stops publishing the Postgres port to the host, switches the app to
production settings, and hands the schema to Alembic. The entrypoint waits for
the database and runs `alembic upgrade head` before uvicorn starts, so a failed
migration stops the container instead of leaving an API serving against a schema
it does not understand.

**One process, always.** Stream workers are in-process threads holding
per-camera ByteTrack state. A second uvicorn worker or a second replica would
open every camera twice and write duplicate events. Scale by adding cameras and
hardware, not processes.

What changes when `ENV=production`:

| | Behaviour |
|---|---|
| `AUTO_CREATE_TABLES=true` or `DEBUG=true` | **startup fails** — both let the app quietly diverge from what Alembic and your logs say is running |
| `CORS_ORIGINS=*`, no `API_KEY` | warned at startup, not blocked; set both unless a gateway handles them |
| `/docs`, `/redoc`, `/openapi.json` | off (`ENABLE_DOCS=true` re-enables) |

Other operational behaviour, all configurable in `.env`:

- **Workers are supervised.** One that dies, errors, or stops producing frames
  is restarted with exponential backoff. `/health/ready` reports
  `supervisor_restarts` and `seconds_since_frame` per camera, and returns
  `degraded` while any worker is unhealthy.
- **Events are reconciled at startup.** A crash mid-blockage would otherwise
  leave `ended_at NULL` forever, and the analytics duration maths measures open
  events up to *now* — one unclean shutdown would skew every aggregate
  permanently.
- **Storage is bounded.** Events, alerts and snapshots are expired on a timer,
  with a hard ceiling on the snapshot directory (`SNAPSHOT_MAX_TOTAL_MB`).
- **Credentials are redacted.** `rtsp://user:pass@host` appears as
  `rtsp://***:***@host` in every log line and error body. Stored and
  API-returned URLs keep their credentials — the config UI needs them.
- **Backups.** All state is the `pgdata` volume plus `./data/snapshots`.
  `docker compose exec postgres pg_dump -U insighteye blocked_exit` covers the
  first; the snapshots are reproducible evidence, not source of truth.

Dependencies are pinned exactly in `requirements.txt`; test and lint tooling
lives in `requirements-dev.txt` and is not installed into the image.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

127 tests, none of which need weights, a database or a network: occupancy math
on synthetic masks, the temporal state machine (driven by a fake clock, so no
sleeping), risk bands, alert gating and delivery failure, the zone-based
strategy against a stubbed detector, pixel↔normalized polygon conversion,
credential redaction, the production config guard, retention eviction rules,
queue shedding and supervisor restart policy against stub workers, and the HTTP
surface through an in-process ASGI transport.
