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
│   ├── auth.py            accounts, workspaces, tokens, password change/reset
│   ├── otp.py             emailed password reset codes (HMAC, expiry, attempts)
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

## Full stack from the repo root

The root `docker-compose.yml` runs Postgres, the API and the web console
together (containers `blocked_exit_postgres`, `blocked_exit_api`,
`blocked_exit_web`):

```bash
cd /home/ubuntu/blocked-exit
docker compose down
docker compose up -d --build
```

| What | URL |
|------|-----|
| Web console | <http://localhost:8081> |
| API (through the console's proxy) | <http://localhost:8081/api/v1> |
| API (direct) | <http://localhost:8001/api/v1> · docs at `/docs` |
| Postgres | `localhost:5433` |

`down` keeps the `pgdata` volume, so accounts, cameras and events survive a
rebuild. `down -v` wipes them.

**First login.** A fresh database has no accounts, and the first signup
becomes the superadmin (see below). The local stack was bootstrapped with the
e2e suite's default account, so `e2e/run.sh` works without extra settings:

| Username | Password | Role |
|----------|----------|------|
| `e2e.admin` | `E2e-Admin-Pass-1` | superadmin, workspace "Default" |

Change that password, or make a separate superadmin, before anyone else can
reach the console. To bootstrap an empty database yourself:

```bash
curl -X POST localhost:8081/api/v1/auth/signup -H "Content-Type: application/json" \
  -d '{"username":"e2e.admin","email":"e2e.admin@example.com","password":"E2e-Admin-Pass-1","workspace_name":"Default"}'
```

**Test videos as cameras.** Compose mounts `backend/videos` read-only at
`/app/videos` in the API container. A camera's source can be any clip there,
and the clip loops forever (`LOOP_VIDEO_FILES=true`). The clips never go into
the image: `.dockerignore` drops `*.mp4`, so a new clip in `backend/videos`
needs no rebuild. On the Cameras page, or through the API:

```bash
curl -X POST localhost:8081/api/v1/cameras -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"name": "Exit A", "location": "Main exit", "rtsp_url": "/app/videos/5.mp4", "enabled": true}'
```

The local stack has these six demo cameras:

| # | Camera | Source | Location |
|---|--------|--------|----------|
| 1 | Exit A | `/app/videos/5.mp4` | Main exit |
| 2 | CCTV 1 | `/app/videos/cctv_video1.mp4` | Corridor |
| 3 | CCTV 3 | `/app/videos/cctv_video3.mp4` | Corridor |
| 4 | CCTV 20 | `/app/videos/cctv_video20.mp4` | Lobby |
| 5 | Left Item 1 | `/app/videos/Left-Behined Item 0001.mp4` | Hall |
| 6 | Normal 1 | `/app/videos/normal-1.mp4` | Side exit |

None of them has an exit region yet, so each one treats the whole frame as the
exit. Draw the door in the [zone editor](#draw-the-exit-region) for meaningful
results. Alerts go nowhere until `ALERT_EMAIL_TO` or `WEBHOOK_URL` is set in
`backend/.env`. Events still show up in the console.

The stack runs YOLO on the GPU (see [Performance](#performance)). Measured on
a Tesla T4 with 4 CPU cores, six cameras each hold the full `PROCESS_FPS=5`.
That uses about 29% of the GPU, 800 MiB of GPU memory, and 1.3 CPU cores. On
`DEVICE=cpu` the same six cameras reach only about 2 fps each and use all 4
cores.

> **API restarting and the console showing 502?** If `backend/data` is missing
> when compose starts, Docker creates it owned by root. The API runs as
> uid 1000 and then fails at startup with
> `PermissionError: '/app/data/snapshots'`. Give the folder back and restart:
>
> ```bash
> docker run --rm -v "$PWD/backend/data:/d" alpine:3 chown -R 1000:1000 /d
> docker restart blocked_exit_api
> ```

## Accounts, roles and workspaces

Same model as the InsightEye platform:

- **No public signup.** The first account to sign up on a fresh database
  (`POST /auth/signup`) becomes the **superadmin** and admin of the
  "Default Workspace". After that, signup is closed (`GET /auth/bootstrap`
  tells the login page) and a superadmin creates accounts
  (`POST /auth/users`). `ALLOW_OPEN_SIGNUP=true` lets anyone sign up into the
  shared Default Workspace as a member.
- **System roles:** `superadmin` creates users and workspaces and manages
  every roster; `admin` acts as a workspace admin wherever it is a member;
  `user` gets its membership role.
- **Workspace roles:** `viewer` reads everything; `member` also runs cameras
  and acknowledges/resolves events; `admin` also draws exit regions, sends
  test alerts and deletes event data. Every workspace keeps at least one admin.
- **Active workspace.** Each user works in one workspace at a time, stored on
  the server (`POST /workspaces/{id}/activate`), so every tab and every
  request agrees. `GET /workspaces/active/permissions` says what the caller may
  do there.

Login takes a username or an email. Access tokens last 60 minutes; refresh
tokens 14 days and rotate on every use. A password change or reset signs the
user out everywhere.

**Forgot your password?** Once `SMTP_HOST` is set, the login page offers a
reset by emailed code (`GET /auth/bootstrap` reports `password_reset`):

1. `POST /auth/forgot-password {"email"}` mails a 6-digit code. The answer is
   the same whether or not the account exists, and the mail is sent after the
   response, so neither tells an outsider who has an account.
2. `POST /auth/reset-password {"email", "code", "new_password"}` checks the
   code and sets the password in one step, then signs the account out
   everywhere. There is no separate "verify" call whose success could be
   spent later.

Codes are stored only as an HMAC keyed with `SECRET_KEY` (table
`password_otp`, one row per account). A code expires after `OTP_TTL_SECONDS`
(10 min) and works once. Asking again within `OTP_RESEND_SECONDS` (60 s) sends
nothing, a new code replaces the old one, and `OTP_MAX_ATTEMPTS` (5) wrong
guesses burn it. Without SMTP both routes answer 503 and an admin resets
passwords from the Users page.

## Register an exit and start monitoring

`rtsp_url` also accepts a local video file, so the pipeline can be exercised
without a camera. In the root compose stack, use a path under `/app/videos`
(see [Full stack from the repo root](#full-stack-from-the-repo-root)). Every route except health and the login/signup/refresh/
bootstrap and password reset endpoints needs a bearer token.

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "..."}' | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
AUTH="Authorization: Bearer $TOKEN"

curl -X POST localhost:8000/api/v1/cameras -H "$AUTH" -H "Content-Type: application/json" -d '{
  "name": "Exit A - Main Corridor",
  "location": "Cairo HQ", "building": "Building 1", "floor_level": "1", "zone": "Main corridor",
  "rtsp_url": "rtsp://user:pass@10.0.0.5:554/stream1",
  "enabled": true
}'

curl -X POST localhost:8000/api/v1/monitoring/1/start -H "$AUTH"
curl localhost:8000/api/v1/monitoring/1/status -H "$AUTH"
curl localhost:8000/api/v1/monitoring/1/snapshot -H "$AUTH" -o exit.jpg   # annotated frame
curl -X POST localhost:8000/api/v1/cameras/1/probe -H "$AUTH"           # test the connection
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
| GET/POST | `/auth/bootstrap` · `/auth/signup` · `/auth/login` · `/auth/refresh` · `/auth/logout` | sessions (signup only while open) |
| GET/PATCH/POST | `/auth/me` · `/auth/me/password` | the caller's profile, memberships and active workspace |
| POST | `/auth/forgot-password` · `/auth/reset-password` | public: password reset by emailed code (needs SMTP) |
| GET/POST/PATCH | `/auth/users`, `/auth/users/{id}` | superadmin: list, create, change role/active/password |
| GET | `/workspaces` · `/workspaces/active` · `/workspaces/active/permissions` | the caller's workspaces, the active one, what they may do |
| POST | `/workspaces/{id}/activate` | switch the active workspace |
| POST/PATCH/DELETE | `/workspaces`, `/workspaces/{id}`, `/workspaces/{id}/deactivate` | superadmin: workspace lifecycle (delete needs deactivate first) |
| GET/POST/PATCH/DELETE | `/workspaces/{id}/members[/{member_id}]` | roster (changes: superadmin) |
| GET | `/workspaces/{id}/cameras` | a workspace's cameras, sources masked |
| POST/GET/PATCH/DELETE | `/cameras`, `/cameras/{id}` | camera CRUD (location, area, building, floor_level, zone) |
| GET | `/cameras/hierarchy` | distinct hierarchy values, cascading |
| POST | `/cameras/{id}/probe` · `/cameras/probe-all` | connection test: reachable, latency, size, fps |
| PUT | `/cameras/{id}/door-polygon` | set the exit region (pixels or normalized) |
| GET | `/cameras/{id}/zone-editor` · `/calibration-frame` · `/door-polygon/preview` | draw the region, fetch a clean still, confirm what was stored |
| POST | `/cameras/{id}/reference` | capture the unobstructed door (door-centric calibration) |
| POST | `/monitoring/{id}/start` · `/stop` · `/restart` | worker lifecycle |
| GET | `/monitoring/status` · `/monitoring/{id}/status` | live verdicts |
| GET | `/monitoring/{id}/snapshot` · `/stream` | annotated JPEG / MJPEG |
| GET | `/events`, `/events/{id}`, `/events/{id}/snapshot`, `/events/overview` | blockage history (status, risk, sort, shared filters), evidence frame, dashboard counters |
| POST | `/events/{id}/acknowledge` · `/events/{id}/resolve` | the detected → acknowledged → resolved workflow |
| DELETE | `/events?<filters>` · `/events/all?confirm=true` | admin data delete (ongoing events are kept) |
| GET/POST | `/alerts`, `/alerts/{id}/ack`, `/alerts/test` | alert log, acknowledge, delivery test |
| GET | `/analytics/summary` · `/most-blocked` · `/{id}/timeline` · `/daily-report` | dashboard data |
| GET | `/analytics/incidents-per-camera` · `/confidence-audit` · `/trend` · `/heatmap` · `/response-times` · `/breakdown` | the platform's charts |

All under `/api/v1`, all scoped to the caller's active workspace.

**Shared filters.** The event list, data delete and every analytics endpoint
take the same query parameters: `start_date`/`end_date` (days in
`REPORT_TIMEZONE`, default Africa/Cairo), `start_time`/`end_time` (with a date
on the same side, an exact bound; alone, a daily window that may wrap
midnight), and comma-separated `camera_id`, `location`, `area`, `building`,
`floor_level`, `zone` (OR within a parameter, AND across them).

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
`yolo26n-seg` at 640px, one camera, `PROCESS_FPS=4`. That is ample — exits are
monitored at a few frames per second, not 30.

For edge deployment, the paper reports large gains from exporting the model
(Raspberry Pi 5: PyTorch 0.75 fps → NCNN 4.84 → OpenVINO 5.78, with
mAP50-95 unchanged):

```bash
yolo export model=models/yolo26n-seg.pt format=openvino
# then set MODEL_PATH / SEG_MODEL_PATH to the exported directory
```

**GPU.** The root `docker-compose.yml` runs on the NVIDIA GPU by default. It
builds the image with CUDA torch (`TORCH_INDEX_URL`, default the cu126 wheel
index), reserves the GPU under `deploy.resources`, and sets `DEVICE=cuda`,
which overrides `backend/.env`. The host needs the NVIDIA driver and the NVIDIA
Container Toolkit (`docker info` lists an `nvidia` runtime). The CUDA image is
about 12GB, against about 3GB for the CPU one, so leave room on disk for the
build. Check that it took:

```bash
docker exec blocked_exit_api python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
curl -s localhost:8081/api/v1/health    # "device": "cuda"
nvidia-smi                              # the api's python process holds GPU memory
```

For a CPU-only host, build with
`TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu`, set `DEVICE=cpu`, and
remove the GPU reservation. Without it, the API container starts with no GPU
and fails at its first inference. A bare `docker build` of `backend/` still
produces the CPU image.

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
| `CORS_ORIGINS=*` | warned at startup, not blocked; set it unless a gateway handles it |
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
pytest                                   # unit tests; tests/db is skipped

# Postgres-backed suite: a database it may drop and recreate
docker compose up -d postgres
# (POSTGRES_PORT from .env; 5433 when using the root docker-compose.yml)
TEST_DATABASE_URL=postgresql+asyncpg://insighteye:insighteye@localhost:5432/blocked_exit_test pytest
```

`tests/db` (marked `db`) migrates a fresh database with Alembic and drives the
real app over HTTP: bootstrap signup and closed signup, superadmin-only
tenancy, workspace activation and the role matrix, the shared filters
(timezone day boundaries, daily windows across midnight, comma lists),
connection probes, data delete safety, password reset by emailed code
(single use, expiry, resend window, attempt limit, no account oracle), the
event lifecycle and the pipeline
writing risk and confidence, and every analytics endpoint against
hand-computed answers.

The unit tests need no weights, database or network: occupancy math
on synthetic masks, the temporal state machine (driven by a fake clock, so no
sleeping), risk bands, alert gating and delivery failure, the zone-based
strategy against a stubbed detector, pixel↔normalized polygon conversion,
credential redaction, the production config guard, retention eviction rules,
queue shedding and supervisor restart policy against stub workers, and the HTTP
surface through an in-process ASGI transport.
