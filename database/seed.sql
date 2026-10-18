-- ---------------------------------------------------------------------------
-- InsightEye — Blocked Exit Detection : development seed
--
-- One demo workspace, one account per role inside it, four exits with a spread
-- of states, plus enough event and alert history for the analytics pages to
-- have something to aggregate. Timestamps are relative to now(), so the
-- "last 24 hours" and "last 7 days" windows are populated whenever this is
-- loaded rather than only on the day it was written.
--
--   psql -h <host> -p 5433 -U insighteye -d blocked_exit -f seed.sql
--
-- Re-runnable: the workspace/user/cameras upsert on their unique columns, and
-- the event/alert rows are deleted for the seeded cameras before being
-- reinserted, so loading twice leaves the same data rather than doubling it.
--
-- DEVELOPMENT ONLY. It writes a real (if generic) password hash and
-- fabricated incident history; never load it into a database anyone relies
-- on, and change the password immediately if you ever do.
--
--   Logins (all with password ChangeMe123!):
--     demo.admin   superadmin, admin of the demo workspace
--     demo.member  member  (runs cameras, acknowledges and resolves events)
--     demo.viewer  viewer  (read-only)
-- ---------------------------------------------------------------------------

BEGIN;

-- --- workspace ---------------------------------------------------------------
INSERT INTO workspace (name, slug, description, camera_quota, is_active)
VALUES ('Demo Workspace', 'demo', 'Seeded for local development and screenshots', 25, TRUE)
ON CONFLICT (slug) DO UPDATE SET
    name        = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_at  = now();

-- --- users -----------------------------------------------------------------------
-- Password: ChangeMe123!  (argon2id hash below — regenerate with
-- `python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('...'))"`
-- if you want a different seeded password.)
INSERT INTO app_user (username, email, full_name, password_hash, role, is_active, default_workspace_id)
SELECT
    v.username, v.username || '@example.com', v.full_name,
    '$argon2id$v=19$m=65536,t=3,p=4$OYd43yT0KdsXT4UQSeJZdQ$sB6DzbM34JCPPynCkdykhnSKvenxqMHQiN7NAjL9juI',
    v.role, TRUE, w.id
FROM workspace w,
     (VALUES ('demo.admin',  'Demo Admin',  'superadmin'),
             ('demo.member', 'Demo Member', 'user'),
             ('demo.viewer', 'Demo Viewer', 'user')) AS v (username, full_name, role)
WHERE w.slug = 'demo'
ON CONFLICT (username) DO UPDATE SET
    email      = EXCLUDED.email,
    full_name  = EXCLUDED.full_name,
    role       = EXCLUDED.role,
    updated_at = now();

INSERT INTO workspace_member (workspace_id, user_id, role)
SELECT w.id, u.id, v.ws_role
FROM workspace w,
     (VALUES ('demo.admin', 'admin'), ('demo.member', 'member'), ('demo.viewer', 'viewer'))
         AS v (username, ws_role)
     JOIN app_user u ON u.username = v.username
WHERE w.slug = 'demo'
ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = EXCLUDED.role;

-- --- cameras ---------------------------------------------------------------
-- ON CONFLICT on (workspace_id, name) (not id): the id is a sequence, so
-- re-running would otherwise create duplicates under new ids.
INSERT INTO camera (
    workspace_id, name, location, rtsp_url, enabled, strategy, door_polygon,
    clear_min_pct, full_max_pct, confirm_seconds, clear_seconds, process_fps
)
SELECT w.id, v.name, v.location, v.rtsp_url, v.enabled, v.strategy, v.door_polygon,
       v.clear_min_pct, v.full_max_pct, v.confirm_seconds, v.clear_seconds, v.process_fps
FROM workspace w, (VALUES
    (
        'Exit A - Main Corridor',
        'Building 1, Floor 1',
        'rtsp://demo:demo@10.0.0.11:554/stream1',
        TRUE,
        'zone_based',
        -- Normalized [0,1] — a doorway on the right-hand side of frame.
        '[[0.52,0.18],[0.88,0.18],[0.88,0.94],[0.52,0.94]]'::jsonb,
        NULL::double precision, NULL::double precision, NULL::double precision, NULL::double precision, NULL::double precision
    ),
    (
        'Exit B - Warehouse North',
        'Building 2, Ground Floor',
        'rtsp://demo:demo@10.0.0.12:554/stream1',
        TRUE,
        'zone_based',
        '[[0.10,0.22],[0.44,0.20],[0.46,0.90],[0.12,0.92]]'::jsonb,
        -- A loading bay is busier than a corridor: hold the confirm window
        -- longer so a forklift passing through is not an incident.
        80.0, 35.0, 12.0, 5.0, 4.0
    ),
    (
        'Exit C - Stairwell East',
        'Building 1, Floor 3',
        'rtsp://demo:demo@10.0.0.13:554/stream1',
        TRUE,
        'zone_based',
        '[[0.30,0.10],[0.70,0.10],[0.72,0.95],[0.28,0.95]]'::jsonb,
        90.0, 45.0, NULL, NULL, NULL
    ),
    (
        'Exit D - Server Room',
        'Building 3, Basement',
        -- Disabled and with no polygon: the state a camera is in immediately
        -- after registration, so the UI's "not drawn" path has a subject.
        'rtsp://demo:demo@10.0.0.14:554/stream1',
        FALSE,
        'zone_based',
        NULL,
        NULL, NULL, NULL, NULL, NULL
    )
) AS v(name, location, rtsp_url, enabled, strategy, door_polygon,
       clear_min_pct, full_max_pct, confirm_seconds, clear_seconds, process_fps)
WHERE w.slug = 'demo'
ON CONFLICT (workspace_id, name) DO UPDATE SET
    location      = EXCLUDED.location,
    rtsp_url      = EXCLUDED.rtsp_url,
    enabled       = EXCLUDED.enabled,
    strategy      = EXCLUDED.strategy,
    door_polygon  = EXCLUDED.door_polygon,
    clear_min_pct = EXCLUDED.clear_min_pct,
    full_max_pct  = EXCLUDED.full_max_pct,
    confirm_seconds = EXCLUDED.confirm_seconds,
    clear_seconds = EXCLUDED.clear_seconds,
    process_fps   = EXCLUDED.process_fps,
    updated_at    = now();

-- Where each exit is: location > area > building > floor_level > zone, so the
-- hierarchy filters on Events and Analytics have something to cascade through.
UPDATE camera c
SET location = v.location, area = v.area, building = v.building,
    floor_level = v.floor_level, zone = v.zone
FROM workspace w, (VALUES
    ('Exit A - Main Corridor',   'Cairo HQ', 'North campus', 'Building 1', '1', 'Main corridor'),
    ('Exit B - Warehouse North', 'Cairo HQ', 'Logistics',    'Building 2', 'G', 'Loading dock'),
    ('Exit C - Stairwell East',  'Cairo HQ', 'North campus', 'Building 1', '3', 'East stairwell'),
    ('Exit D - Server Room',     'Giza DC',  'Data hall',    'Building 3', 'B1', 'Server room')
) AS v(name, location, area, building, floor_level, zone)
WHERE w.slug = 'demo' AND c.workspace_id = w.id AND c.name = v.name;

-- --- clear previous seed history -------------------------------------------
-- Only for the seeded cameras, so a database that also holds real events from
-- a live worker keeps them. The alert rows go with the events via ON DELETE
-- CASCADE; test alerts carry no event_id, so they are removed explicitly.
DELETE FROM alert
WHERE camera_id IN (
    SELECT c.id FROM camera c
    JOIN workspace w ON w.id = c.workspace_id
    WHERE w.slug = 'demo' AND c.name LIKE 'Exit % - %'
);

DELETE FROM blockage_event
WHERE camera_id IN (
    SELECT c.id FROM camera c
    JOIN workspace w ON w.id = c.workspace_id
    WHERE w.slug = 'demo' AND c.name LIKE 'Exit % - %'
);

-- --- blockage events -------------------------------------------------------
WITH ids AS (
    SELECT
        c.workspace_id                                              AS workspace_id,
        MAX(c.id) FILTER (WHERE c.name = 'Exit A - Main Corridor')   AS a,
        MAX(c.id) FILTER (WHERE c.name = 'Exit B - Warehouse North') AS b,
        MAX(c.id) FILTER (WHERE c.name = 'Exit C - Stairwell East')  AS c
    FROM camera c
    JOIN workspace w ON w.id = c.workspace_id
    WHERE w.slug = 'demo'
    GROUP BY c.workspace_id
)
INSERT INTO blockage_event (
    workspace_id, camera_id, started_at, ended_at, duration_s, state, peak_state, strategy,
    min_accessibility_pct, last_accessibility_pct, peak_risk_score,
    blocking_objects, snapshot_path
)
SELECT * FROM (VALUES
    -- Exit B: an open, ongoing full blockage. ended_at and duration_s are
    -- NULL exactly as the pipeline leaves them until the exit clears.
    (
        (SELECT workspace_id FROM ids), (SELECT b FROM ids), now() - INTERVAL '25 minutes', NULL::timestamptz, NULL::double precision,
        'FULL', 'FULL', 'zone_based', 18.4, 18.4, 92.5,
        '[{"label":"couch","class_id":57,"confidence":0.93,"track_id":11,"bbox":[220,140,520,430],"area_pct":61.2},
          {"label":"chair","class_id":56,"confidence":0.88,"track_id":12,"bbox":[500,220,640,430],"area_pct":20.4}]'::jsonb,
        'data/snapshots/camera_2/open_20260806T062640454079.jpg'
    ),
    -- Exit A: a closed partial blockage from earlier today.
    (
        (SELECT workspace_id FROM ids), (SELECT a FROM ids), now() - INTERVAL '4 hours', now() - INTERVAL '3 hours 47 minutes', 780.0,
        'PARTIAL', 'PARTIAL', 'zone_based', 62.1, 88.9, 47.7,
        '[{"label":"chair","class_id":56,"confidence":0.91,"track_id":7,"bbox":[310,180,460,400],"area_pct":37.9}]'::jsonb,
        NULL
    ),
    -- Exit A: escalated from PARTIAL to FULL — peak_state is what makes that
    -- visible after the fact.
    (
        (SELECT workspace_id FROM ids), (SELECT a FROM ids), now() - INTERVAL '2 days', now() - INTERVAL '2 days' + INTERVAL '54 minutes', 3240.0,
        'PARTIAL', 'FULL', 'zone_based', 22.6, 71.3, 88.1,
        '[{"label":"refrigerator","class_id":72,"confidence":0.95,"track_id":3,"bbox":[180,90,540,440],"area_pct":77.4}]'::jsonb,
        NULL
    ),
    -- Exit C: brief, low-risk — a person standing in the doorway.
    (
        (SELECT workspace_id FROM ids), (SELECT c FROM ids), now() - INTERVAL '20 hours', now() - INTERVAL '20 hours' + INTERVAL '42 seconds', 42.0,
        'PARTIAL', 'PARTIAL', 'zone_based', 79.8, 96.2, 21.3,
        '[{"label":"person","class_id":0,"confidence":0.89,"track_id":21,"bbox":[300,150,420,430],"area_pct":20.2}]'::jsonb,
        NULL
    ),
    (
        (SELECT workspace_id FROM ids), (SELECT b FROM ids), now() - INTERVAL '3 days', now() - INTERVAL '3 days' + INTERVAL '19 minutes', 1140.0,
        'FULL', 'FULL', 'zone_based', 12.5, 55.0, 91.0,
        '[{"label":"suitcase","class_id":28,"confidence":0.87,"track_id":31,"bbox":[210,260,470,440],"area_pct":48.8},
          {"label":"backpack","class_id":24,"confidence":0.79,"track_id":32,"bbox":[430,300,560,440],"area_pct":25.1}]'::jsonb,
        NULL
    ),
    (
        (SELECT workspace_id FROM ids), (SELECT b FROM ids), now() - INTERVAL '5 days', now() - INTERVAL '5 days' + INTERVAL '6 minutes', 360.0,
        'PARTIAL', 'PARTIAL', 'zone_based', 58.3, 90.1, 52.4,
        '[{"label":"bicycle","class_id":1,"confidence":0.84,"track_id":41,"bbox":[150,240,430,430],"area_pct":41.7}]'::jsonb,
        NULL
    ),
    (
        (SELECT workspace_id FROM ids), (SELECT c FROM ids), now() - INTERVAL '6 days', now() - INTERVAL '6 days' + INTERVAL '2 minutes', 120.0,
        'PARTIAL', 'PARTIAL', 'zone_based', 74.0, 93.4, 28.9,
        '[{"label":"potted plant","class_id":58,"confidence":0.81,"track_id":51,"bbox":[330,240,450,430],"area_pct":26.0}]'::jsonb,
        NULL
    )
) AS v
-- A database seeded before the demo workspace/cameras exist would otherwise
-- insert rows with a NULL camera_id and fail the FK with a confusing message.
WHERE (SELECT a FROM ids) IS NOT NULL;

-- Risk band and detection confidence, as the pipeline records them: the band
-- of peak_risk_score (app/services/risk.py), and the peak / mean of the top
-- blocking detection (the mean sits a little under the peak, as it does live).
UPDATE blockage_event e
SET risk_level = CASE
        WHEN e.peak_state = 'FULL' AND e.peak_risk_score >= 60 THEN 'CRITICAL'
        WHEN e.peak_risk_score >= 80 THEN 'CRITICAL'
        WHEN e.peak_risk_score >= 55 THEN 'HIGH'
        ELSE 'MEDIUM'
    END,
    confidence     = top.conf,
    avg_confidence = round(top.conf * 0.93, 4)
FROM (
    SELECT e2.id, max((o ->> 'confidence')::numeric) AS conf
    FROM blockage_event e2, jsonb_array_elements(e2.blocking_objects) AS o
    GROUP BY e2.id
) AS top, camera c, workspace w
WHERE top.id = e.id AND c.id = e.camera_id AND w.id = c.workspace_id
  AND w.slug = 'demo' AND c.name LIKE 'Exit % - %';

-- Operator workflow, newest event first: the ongoing blockage and one old
-- event nobody looked at are still 'detected'; one is acknowledged; the rest
-- were resolved, with realistic delays for the response-time analytics.
WITH ranked AS (
    SELECT e.id, e.started_at,
           row_number() OVER (ORDER BY e.started_at DESC) AS rn
    FROM blockage_event e
    JOIN camera c ON c.id = e.camera_id
    JOIN workspace w ON w.id = c.workspace_id
    WHERE w.slug = 'demo' AND c.name LIKE 'Exit % - %'
)
UPDATE blockage_event e
SET status             = v.status,
    acknowledged_at    = r.started_at + v.ack_after,
    acknowledged_by_id = (SELECT id FROM app_user WHERE username = v.ack_by),
    resolved_at        = r.started_at + v.resolve_after,
    resolved_by_id     = (SELECT id FROM app_user WHERE username = v.resolve_by),
    resolution_note    = v.note
FROM ranked r, (VALUES
    (2, 'resolved',     INTERVAL '3 minutes', 'demo.member', INTERVAL '14 minutes', 'demo.member', 'Chair returned to the meeting room'),
    (3, 'acknowledged', INTERVAL '2 minutes', 'demo.member', NULL,                  NULL,          NULL),
    (4, 'resolved',     INTERVAL '6 minutes', 'demo.member', INTERVAL '58 minutes', 'demo.admin',  'Refrigerator delivery rerouted to the loading dock'),
    (5, 'resolved',     INTERVAL '4 minutes', 'demo.member', INTERVAL '22 minutes', 'demo.member', 'Luggage collected by its owner'),
    (6, 'resolved',     INTERVAL '9 minutes', 'demo.admin',  INTERVAL '12 minutes', 'demo.admin',  'Bicycle moved to the rack')
) AS v (rn, status, ack_after, ack_by, resolve_after, resolve_by, note)
WHERE r.rn = v.rn AND e.id = r.id;

-- --- alerts ----------------------------------------------------------------
-- Attached to the events above rather than invented independently, so the
-- alert log and the event log tell the same story.
INSERT INTO alert (workspace_id, camera_id, event_id, channel, status, error, payload, created_at, sent_at, acknowledged_at, acknowledged_by)
SELECT
    e.workspace_id,
    e.camera_id,
    e.id,
    'webhook',
    'sent',
    NULL,
    jsonb_build_object(
        'event', 'blockage_alert',
        'camera_id', e.camera_id,
        'state', e.peak_state,
        'accessibility_pct', e.min_accessibility_pct,
        'risk_score', e.peak_risk_score,
        'blocking_objects', COALESCE(e.blocking_objects, '[]'::jsonb)
    ),
    e.started_at + INTERVAL '15 seconds',
    e.started_at + INTERVAL '16 seconds',
    -- Only the closed events were acknowledged; the ongoing one is still
    -- waiting for somebody, which is what the "unacknowledged only" filter is
    -- there to surface.
    CASE WHEN e.ended_at IS NOT NULL THEN e.started_at + INTERVAL '4 minutes' END,
    CASE WHEN e.ended_at IS NOT NULL THEN 'facilities.duty' END
FROM blockage_event e
JOIN camera c ON c.id = e.camera_id
JOIN workspace w ON w.id = c.workspace_id
WHERE w.slug = 'demo' AND c.name LIKE 'Exit % - %'
  AND e.peak_risk_score >= 45.0;

-- One failed email delivery, so the alert log has a failure path to show.
INSERT INTO alert (workspace_id, camera_id, event_id, channel, status, error, payload, created_at, sent_at)
SELECT
    e.workspace_id,
    e.camera_id,
    e.id,
    'email',
    'failed',
    'SMTP connect failed: [Errno 111] Connection refused',
    jsonb_build_object('event', 'blockage_alert', 'camera_id', e.camera_id, 'state', e.peak_state),
    e.started_at + INTERVAL '15 seconds',
    NULL
FROM blockage_event e
JOIN camera c ON c.id = e.camera_id
JOIN workspace w ON w.id = c.workspace_id
WHERE w.slug = 'demo' AND c.name = 'Exit B - Warehouse North'
  AND e.ended_at IS NULL;

COMMIT;

-- --- what was loaded -------------------------------------------------------
SELECT
    w.slug        AS workspace,
    c.name,
    COUNT(e.id)                                        AS events,
    COUNT(e.id) FILTER (WHERE e.ended_at IS NULL)      AS open_events,
    COUNT(a.id)                                        AS alerts
FROM camera c
JOIN workspace w ON w.id = c.workspace_id
LEFT JOIN blockage_event e ON e.camera_id = c.id
LEFT JOIN alert a          ON a.camera_id = c.id
WHERE w.slug = 'demo'
GROUP BY w.slug, c.id, c.name
ORDER BY c.id;
