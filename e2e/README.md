# End-to-end tests

Playwright driving the operator console in a real browser, against the real
stack: nginx serving the built bundle, FastAPI behind it, Postgres behind that,
and a YOLO worker decoding an actual video file. Nothing is mocked. When these
pass, the pipeline works — not just the React components.

## Running

```bash
cd features/blocked&exit
docker compose up -d --build     # postgres + api + web
./e2e/run.sh                     # whole suite
./e2e/run.sh tests/02-camera-lifecycle.spec.js   # one file
```

`run.sh` executes the tests inside `mcr.microsoft.com/playwright`, so nothing
has to be installed locally beyond Docker — the image already carries the
browsers and their system libraries. It runs with `--network host`, which is
why `BASE_URL` defaults to `http://localhost:8081` rather than a compose
service name.

Results land in:

| Path | What |
| --- | --- |
| `playwright-report/` | HTML report — `npx playwright show-report` |
| `results.json` | machine-readable summary |
| `test-results/` | screenshots, video and traces for failures |

To run against a different origin (a staging deploy, or the Vite dev server on
5173):

```bash
BASE_URL=http://localhost:5173 ./e2e/run.sh
```

## The test clip

`backend/data/5.mp4` is bind-mounted into the api container at
`/app/data/5.mp4`, and that path is what the suite registers as the camera's
stream source. The backend accepts a local file anywhere it accepts an RTSP
URL, so no camera and no RTSP server are needed. `LOOP_VIDEO_FILES=true` means
the clip restarts rather than ending the worker.

A path only the *host* can see will not work — the worker opens it from inside
the container.

## What the specs cover

They are numbered because they are one story told in order, run by a single
worker. Spec 02 leaves a camera monitoring; 03 reads what that produced; 04
takes it back down.

| File | Covers |
| --- | --- |
| `01-shell.spec.js` | health and readiness, every route, the nav, the 404 page, the legacy `/zones` redirect, the theme toggle |
| `02-camera-lifecycle.spec.js` | form validation, registering an exit against the clip, grabbing a calibration frame, drawing and saving the polygon, starting the worker, the live view, the list joining record with status |
| `03-observability.spec.js` | dashboard cards, `/monitoring/status`, the event log and its filters, the alert log, `/alerts/test`, the analytics roll-up, and that the worker keeps advancing |
| `04-teardown.spec.js` | editing an exit, acknowledging an alert, stopping the worker, deleting the camera |

Assertions cross-check the UI against the API rather than trusting either
alone: the console can render a stale number, and the API can be right about
something the page never shows.

Where a result depends on what is in the clip — whether an obstruction ever
lasted long enough to open an event — the spec asserts both branches: the
page's empty state when there is nothing, the row when there is. A suite that
fails because the footage was uneventful is testing the footage.

## Housekeeping

The camera is named `E2E Exit — clip 5` and the name is unique in the
database, so specs 01 and 02 both delete a leftover from an interrupted run
before creating one. That also means a failed run leaves the camera behind on
purpose — it is there to inspect.

## Timeouts

The per-test timeout is 3 minutes and expectations get 20 seconds. That is not
padding: inference runs on CPU, and the first frame after a container start
pays for torch's cold import — on the order of ten seconds for a single frame
before it settles.

## The visual artifact

`./e2e/capture.sh` runs the same journey but photographs it instead of
asserting on it, writing a numbered sequence to `artifact/` plus a
`manifest.json` recording the run. See `artifact/README.md` for the index.

The two are complementary: the suite tells you whether the console works, the
artifact shows you what it looked like when it did.
