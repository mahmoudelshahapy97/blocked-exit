# Frontend — Blocked Exit Detection

Operator console for the blocked-exit detection service. **Vite + React 18 +
react-router-dom 6 + MUI 6**, talking to the FastAPI backend through a dev
proxy.

## Quick start

The backend must be running first (see `../backend/README.md`).

```bash
cd "features/blocked&exit/frontend"     # quote the path — it contains '&'
npm install
cp .env.example .env                    # adjust VITE_API_TARGET if needed
npm run dev
```

Open <http://localhost:5173>.

## The proxy, and why there is one

`vite.config.js` forwards `/api`, `/ui`, `/docs`, `/redoc` and `/openapi.json`
to the backend, so **the browser only ever makes same-origin requests**. Two
things fall out of that, and both matter:

- **No CORS.** The backend defaults to `CORS_ORIGINS=*`, which browsers refuse
  to pair with credentials. A same-origin proxy sidesteps the negotiation
  entirely.
- **MJPEG works.** `<img src="/api/v1/monitoring/1/stream">` is same-origin, so
  it is not subject to a preflight that a `multipart/x-mixed-replace` response
  could not answer anyway.

The proxy target defaults to `http://127.0.0.1:8001`, because `backend/.env`
sets `API_PORT=8001` — not the `8000` in the backend README. Override with
`VITE_API_TARGET`.

MJPEG responses never end, so the `/api` proxy sets `timeout: 0` and
`proxyTimeout: 0`. With the defaults, a live view would be severed after a
minute of perfectly healthy streaming.

### In production

There is no Vite dev server, so something else must put the API on the same
origin as the bundle. Serve `dist/` from nginx and proxy `/api` to the backend:

```nginx
location / {
    root /srv/blocked-exit/dist;
    try_files $uri /index.html;    # required: the router owns these paths
}

location /api/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_buffering off;           # required: MJPEG must not be buffered
    proxy_read_timeout 24h;
}
```

`try_files ... /index.html` is not optional — this is a `BrowserRouter`, so a
hard refresh on `/cameras/3/zone` asks the server for a path that does not
exist on disk.

## Routes

| Path | Page |
|---|---|
| `/` | Live dashboard — every exit, worst first |
| `/cameras` | Registered exits, with worker controls |
| `/cameras/new` · `/cameras/:id/edit` | Create / edit a camera |
| `/cameras/:id` | One exit: live view, verdict, blocking objects, recent events |
| `/cameras/:id/zone` | Draw the exit region |
| `/events` | Blockage event history (filters are in the URL) |
| `/alerts` | Alert log, acknowledgement, payload inspection |
| `/analytics` | Most-blocked exits, daily report |

Filters on `/events` and `/alerts` live in the query string, so a filtered view
is a shareable link.

## Layout

```
src/
├── api/
│   ├── client.js      axios instance, X-API-Key, error-shape flattening
│   └── endpoints.js   one function per backend route
├── components/        LiveView, PolygonEditor, chips, dialogs, toasts
├── hooks/
│   ├── usePolling.js  interval fetch with abort + tab-visibility pause
│   ├── useAsync.js    one-shot fetch, same abort discipline
│   └── useMonitoringActions.js   start/stop/restart
├── layouts/AppLayout.jsx    sidebar, backend health chip, theme toggle
├── pages/             one file per route
├── routes/AppRouter.jsx     lazy-loaded routes
└── utils/             constants (mirrors app/core/enums.py), formatters, theme
```

## Things worth knowing before changing this

**The dashboard merges two sources.** `GET /monitoring/status` returns only
cameras that have a *running worker* — a registered-but-stopped exit is simply
absent. The dashboard therefore also fetches `/cameras` and renders the
difference as idle cards with a "start monitoring" action. Drop that merge and
stopped exits vanish from the wall display, which is precisely when you most
want to see them.

**Polygon coordinates have three forms.** The editor works in the frame's
*native pixels*; the canvas renders at whatever width the layout gives it; the
backend stores `[0,1]`. `PolygonEditor` keeps points in native pixels and
scales only for drawing, and the save call sends pixels plus
`frame_width`/`frame_height` (from the `X-Frame-Width`/`X-Frame-Height` headers
on `/calibration-frame`) so the *backend* does the normalization. There is
deliberately only one implementation of that maths, and it is not here.

**Polling pauses on hidden tabs.** Every viewer costs the backend a JPEG encode
per frame, and `MAX_MJPEG_CLIENTS` caps the streaming ones. A forgotten wall
display tab would otherwise take CPU from detection on exactly the hardware
that has none spare.

**`API_KEY` and `<img>` do not mix.** The backend accepts the key only as an
`X-API-Key` header, which an `<img>` tag cannot send. So when `VITE_API_KEY` is
set, `LiveView` switches from the MJPEG stream to polled snapshots fetched as
blobs, which *can* carry the header. Note also that `VITE_API_KEY` is bundled
into the client build — it is not a secret from anyone who loads the page. For
real authentication, put a gateway in front.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_TARGET` | `http://127.0.0.1:8001` | Backend origin the dev proxy forwards to |
| `VITE_PORT` | `5173` | Dev server port |
| `VITE_API_KEY` | *(empty)* | Sent as `X-API-Key`; only needed when the backend sets `API_KEY` |
| `VITE_POLL_INTERVAL_MS` | `3000` | Dashboard / live view refresh cadence |

## Scripts

```bash
npm run dev       # dev server with the proxy
npm run build     # production bundle into dist/
npm run preview   # serve dist/, proxy still applied
```
