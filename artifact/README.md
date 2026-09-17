# Blocked-exit console — captured walkthrough

Screenshots of the operator console driven by a real Chromium against the real
stack: nginx serving the built bundle, FastAPI behind it, Postgres behind that,
and a YOLO11 worker decoding `backend/data/5.mp4`. Nothing here is a mockup and
nothing is mocked — the boxes in the live view are what the detector found in
that frame.

Regenerate with:

```bash
cd features/blocked&exit
docker compose up -d --build
./e2e/capture.sh
```

The walkthrough registers its own camera, drives it through the whole
lifecycle and deletes it again, so the folder can be rebuilt at any time
without leaving anything behind. `manifest.json` records the run: when, against
what, the verdict the worker reached, and any uncaught page error (none).

## The sequence

| # | File | What it shows |
| --- | --- | --- |
| 01 | `01-dashboard-empty.png` | Dashboard before anything is monitored |
| 02 | `02-exits-empty.png` | The exits table |
| 03 | `03-camera-form-blank.png` | Add-exit form |
| 04 | `04-camera-form-required.png` | Submitting nothing — required fields refuse |
| 05 | `05-camera-form-threshold-error.png` | FULL ≥ CLEAR rejected: inverted bounds would make PARTIAL unreachable, and the backend validates each bound alone |
| 06 | `06-camera-form-filled.png` | Filled against the local clip |
| 07 | `07-zone-editor-frame.png` | A real 1280×720 frame decoded from the clip |
| 08 | `08-zone-polygon-drawn.png` | Four points clicked on the canvas |
| 09 | `09-camera-detail-idle.png` | Region saved, worker not yet started |
| 10 | `10-camera-detail-monitoring.png` | **The main one.** Live MJPEG with per-person boxes and track ids, the blocking-objects table, config and pipeline counters |
| 11 | `11-exits-monitoring.png` | The list joining each record with its live verdict |
| 12 | `12-dashboard-live.png` | Dashboard card streaming, worst exit first |
| 13 | `13-events.png` | Blockage event log |
| 14 | `14-events-filtered.png` | Filtered to this exit |
| 15 | `15-alerts.png` | Alert delivery log |
| 16 | `16-alert-acknowledge-dialog.png` | Acknowledging, signed by the operator |
| 17 | `17-alerts-acknowledged.png` | The signature recorded against the row |
| 18 | `18-analytics.png` | 7-day roll-up |
| 19 | `19-analytics-30-days.png` | Window switched to 30 days |
| 20 | `20-camera-form-edit.png` | Edit form, arriving populated |
| 21 | `21-dashboard-light-theme.png` | Light theme |
| 22 | `22-not-found.png` | 404 |
| 23 | `23-mobile-dashboard.png` | 390×844 |
| 24 | `24-mobile-camera-detail.png` | 390×844 |
| 25 | `25-delete-confirm.png` | Delete confirmation |
| 26 | `26-exits-after-delete.png` | Gone from the list |
| — | `annotated-frame.jpg` | The annotator's output on its own, straight from `/monitoring/{id}/snapshot` |

## The verdict in these shots

`CLEAR`, 93.7% accessible, 7 people tracked inside the region, risk LOW.

That is the correct reading of this footage, not a weak one. The clip is a
crowded concourse: people crossing the region cover about 6% of it, which is
far above the 85% CLEAR threshold. Exercising the PARTIAL and FULL paths, and
the events and alerts that follow from them, needs footage with something
actually parked in the doorway.

## Note on the two other cameras

`Exit A - Main Corridor` and `Exit B - Test Blockage` appear as *Not monitored*
throughout. They are pre-existing rows whose sources are Windows paths
(`c:/Users/...`) that no container can open; they were disabled so they would
stop burning CPU in a reconnect loop. Re-point them at a path inside the
container to bring them back.
