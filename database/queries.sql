-- ---------------------------------------------------------------------------
-- InsightEye — Blocked Exit Detection : operational queries
--
-- The SQL behind the API's analytics endpoints, written out plainly, plus the
-- ad-hoc queries that answer questions the API does not expose. Nothing here
-- writes; run any block on its own.
--
-- One rule governs almost every query in this file:
--
--     An open event (ended_at IS NULL) has no duration_s yet.
--
-- The pipeline writes duration_s only when it closes an event, so any query
-- that sums or averages duration must fall back to (now() - started_at) or it
-- will silently ignore exactly the blockages that are still happening — the
-- ones that matter most. That fallback is spelled COALESCE(duration_s,
-- EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at))) throughout,
-- matching backend/app/services/analytics.py::_effective_duration.
--
-- TENANCY: since 0002_auth_and_workspaces, camera/blockage_event/alert each
-- carry a workspace_id, and every one of these endpoints filters on it (see
-- app/api/routes/*.py) -- a workspace only ever sees its own rows. The
-- queries below are written single-tenant, as an operator running psql
-- directly usually wants the whole database. Add
-- `AND c.workspace_id = <id>` (or `AND e.workspace_id = <id>` /
-- `AND a.workspace_id = <id>` where those columns are already in scope) to
-- reproduce what one workspace's API calls actually see.
-- ---------------------------------------------------------------------------


-- ===========================================================================
-- 1. Live state
-- ===========================================================================

-- 1.1 Every exit and whether it is blocked right now.
-- The API answers this from worker memory (GET /monitoring/status), which only
-- knows about *started* workers. This version is drawn from the database, so
-- it also covers cameras whose worker is stopped — useful when checking
-- whether an exit was left unmonitored.
SELECT
    c.id,
    c.name,
    c.location,
    c.enabled,
    c.strategy,
    (e.id IS NOT NULL)                                        AS blocked_now,
    e.id                                                      AS open_event_id,
    e.state,
    e.peak_state,
    e.last_accessibility_pct,
    e.peak_risk_score,
    ROUND(EXTRACT(EPOCH FROM (now() - e.started_at))::numeric, 1) AS blocked_for_s,
    jsonb_array_length(COALESCE(c.door_polygon, '[]'::jsonb))  AS polygon_points
FROM camera c
-- LEFT JOIN, not INNER: a clear exit has no open event and must still appear.
LEFT JOIN blockage_event e
       ON e.camera_id = c.id
      AND e.ended_at IS NULL
ORDER BY blocked_now DESC, e.peak_risk_score DESC NULLS LAST, c.name;


-- 1.2 Exits blocked longer than 10 minutes and not yet acknowledged.
-- The escalation list: something is in the way, an alert went out, and nobody
-- has picked it up.
SELECT
    c.name,
    c.location,
    e.id                                                      AS event_id,
    e.peak_state,
    e.min_accessibility_pct,
    e.peak_risk_score,
    ROUND(EXTRACT(EPOCH FROM (now() - e.started_at))::numeric / 60, 1) AS blocked_for_min,
    COUNT(a.id)                                               AS alerts_sent
FROM blockage_event e
JOIN camera c ON c.id = e.camera_id
LEFT JOIN alert a
       ON a.event_id = e.id
      AND a.status = 'sent'
WHERE e.ended_at IS NULL
  AND e.started_at < now() - INTERVAL '10 minutes'
GROUP BY c.name, c.location, e.id, e.peak_state, e.min_accessibility_pct,
         e.peak_risk_score, e.started_at
HAVING COUNT(a.id) FILTER (WHERE a.acknowledged_at IS NOT NULL) = 0
ORDER BY e.started_at;


-- 1.3 Cameras that cannot actually detect anything.
-- Zone-based measures obstruction against the drawn polygon; without one it
-- has nothing to measure, and the camera looks monitored while reporting
-- nothing useful. A silent misconfiguration worth auditing for.
SELECT
    id,
    name,
    location,
    strategy,
    enabled,
    CASE
        WHEN strategy = 'zone_based'
             AND COALESCE(jsonb_array_length(door_polygon), 0) < 3
            THEN 'zone_based with no exit region drawn'
        WHEN strategy = 'door_centric' AND reference_bbox IS NULL
            THEN 'door_centric with no reference captured'
    END AS problem
FROM camera
WHERE (strategy = 'zone_based'   AND COALESCE(jsonb_array_length(door_polygon), 0) < 3)
   OR (strategy = 'door_centric' AND reference_bbox IS NULL)
ORDER BY enabled DESC, name;


-- ===========================================================================
-- 2. Analytics — the queries behind /api/v1/analytics
-- ===========================================================================

-- 2.1 Summary over a window (GET /analytics/summary?days=7).
WITH windowed AS (
    SELECT
        e.*,
        COALESCE(
            e.duration_s,
            EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at))
        ) AS effective_duration_s
    FROM blockage_event e
    WHERE e.started_at >= now() - INTERVAL '7 days'
)
SELECT
    (SELECT COUNT(*) FROM camera)                                AS cameras_total,
    COUNT(*)                                                     AS events_total,
    COUNT(*) FILTER (WHERE ended_at IS NULL)                     AS events_open,
    ROUND(COALESCE(AVG(effective_duration_s), 0)::numeric, 1)    AS avg_duration_s,
    ROUND(COALESCE(MAX(effective_duration_s), 0)::numeric, 1)    AS max_duration_s,
    ROUND(COALESCE(AVG(min_accessibility_pct), 100)::numeric, 1) AS avg_min_accessibility_pct,
    (
        SELECT COUNT(*)
        FROM alert
        WHERE created_at >= now() - INTERVAL '7 days'
          AND status = 'sent'
    )                                                            AS alerts_sent
FROM windowed;


-- 2.2 Most blocked exits (GET /analytics/most-blocked?days=7&limit=10).
-- The heatmap data: which exits keep being obstructed.
SELECT
    c.id                                                        AS camera_id,
    c.name                                                      AS camera_name,
    c.location,
    COUNT(e.id)                                                 AS event_count,
    ROUND(COALESCE(SUM(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    ), 0)::numeric, 1)                                          AS total_blocked_s,
    ROUND(COALESCE(AVG(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    ), 0)::numeric, 1)                                          AS avg_duration_s,
    ROUND(COALESCE(MAX(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    ), 0)::numeric, 1)                                          AS max_duration_s,
    ROUND(COALESCE(MIN(e.min_accessibility_pct), 100)::numeric, 1) AS min_accessibility_pct,
    ROUND(COALESCE(MAX(e.peak_risk_score), 0)::numeric, 1)         AS peak_risk_score
FROM camera c
JOIN blockage_event e ON e.camera_id = c.id
WHERE e.started_at >= now() - INTERVAL '7 days'
GROUP BY c.id, c.name, c.location
ORDER BY event_count DESC, total_blocked_s DESC
LIMIT 10;


-- 2.3 Timeline for one exit (GET /analytics/{camera_id}/timeline).
-- Set the camera id before running.
SELECT
    e.id                                                        AS event_id,
    e.started_at,
    e.ended_at,
    ROUND(COALESCE(
        e.duration_s,
        EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at))
    )::numeric, 1)                                              AS duration_s,
    e.state,
    e.peak_state,
    e.min_accessibility_pct,
    e.peak_risk_score,
    -- The distinct labels that obstructed the exit, flattened out of the JSONB
    -- array so the timeline can say "chair, suitcase" without post-processing.
    COALESCE(
        (
            SELECT array_agg(DISTINCT obj ->> 'label')
            FROM jsonb_array_elements(COALESCE(e.blocking_objects, '[]'::jsonb)) AS obj
        ),
        ARRAY[]::text[]
    )                                                           AS blocking_labels
FROM blockage_event e
WHERE e.camera_id = 1                       -- <<< set the camera id
  AND e.started_at >= now() - INTERVAL '7 days'
ORDER BY e.started_at DESC
LIMIT 200;


-- 2.4 Daily report (GET /analytics/daily-report), for the current UTC day.
SELECT
    c.id                                                        AS camera_id,
    c.name                                                      AS camera_name,
    c.location,
    COUNT(e.id)                                                 AS event_count,
    ROUND(COALESCE(SUM(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    ), 0)::numeric, 1)                                          AS total_blocked_s,
    ROUND(COALESCE(AVG(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    ), 0)::numeric, 1)                                          AS avg_duration_s,
    ROUND(COALESCE(MAX(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    ), 0)::numeric, 1)                                          AS longest_blockage_s,
    ROUND(COALESCE(MIN(e.min_accessibility_pct), 100)::numeric, 1) AS worst_accessibility_pct,
    (
        SELECT COUNT(*)
        FROM alert a
        WHERE a.camera_id = c.id
          AND a.status = 'sent'
          AND a.created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
    )                                                           AS alerts_sent
FROM camera c
LEFT JOIN blockage_event e
       ON e.camera_id = c.id
      AND e.started_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
GROUP BY c.id, c.name, c.location
ORDER BY total_blocked_s DESC;


-- ===========================================================================
-- 3. Questions the API does not answer
-- ===========================================================================

-- 3.1 What actually blocks these exits, ranked.
-- Drives the decision the analytics pages cannot: if 'chair' dominates, the
-- fix is furniture policy, not more cameras.
SELECT
    obj ->> 'label'                                             AS object_label,
    COUNT(*)                                                    AS times_seen,
    COUNT(DISTINCT e.camera_id)                                 AS exits_affected,
    ROUND(AVG((obj ->> 'area_pct')::numeric), 1)                AS avg_area_pct,
    ROUND(MAX((obj ->> 'area_pct')::numeric), 1)                AS worst_area_pct,
    ROUND(AVG((obj ->> 'confidence')::numeric), 3)              AS avg_confidence
FROM blockage_event e
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(e.blocking_objects, '[]'::jsonb)) AS obj
WHERE e.started_at >= now() - INTERVAL '30 days'
GROUP BY obj ->> 'label'
ORDER BY times_seen DESC;


-- 3.2 When do blockages happen?
-- Hour-of-day histogram. A spike at shift change is an operations problem; one
-- spread evenly through the night is a storage problem.
SELECT
    EXTRACT(HOUR FROM started_at)::int                          AS hour_of_day,
    COUNT(*)                                                    AS events,
    ROUND(AVG(
        COALESCE(duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at)))
    )::numeric, 1)                                              AS avg_duration_s
FROM blockage_event
WHERE started_at >= now() - INTERVAL '30 days'
GROUP BY hour_of_day
ORDER BY hour_of_day;


-- 3.3 Daily trend per exit — is a given exit getting better or worse?
SELECT
    date_trunc('day', e.started_at)::date                       AS day,
    c.name                                                      AS camera_name,
    COUNT(*)                                                    AS events,
    ROUND(SUM(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    )::numeric / 60, 1)                                         AS blocked_minutes
FROM blockage_event e
JOIN camera c ON c.id = e.camera_id
WHERE e.started_at >= now() - INTERVAL '30 days'
GROUP BY day, c.name
ORDER BY day DESC, blocked_minutes DESC;


-- 3.4 Alert delivery health.
-- A channel sitting at a high failure rate means alerts are being raised and
-- silently going nowhere.
SELECT
    channel,
    status,
    COUNT(*)                                                    AS deliveries,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY channel), 1) AS pct_of_channel,
    -- Only 'sent' rows have sent_at, so this latency is over successes alone.
    ROUND(AVG(EXTRACT(EPOCH FROM (sent_at - created_at)))::numeric, 2)     AS avg_latency_s,
    MAX(created_at)                                             AS most_recent
FROM alert
WHERE created_at >= now() - INTERVAL '30 days'
GROUP BY channel, status
ORDER BY channel, deliveries DESC;


-- 3.5 How quickly does anyone respond?
-- Time from alert raised to acknowledged, per exit.
SELECT
    c.name                                                      AS camera_name,
    COUNT(*)                                                    AS acknowledged_alerts,
    ROUND(AVG(EXTRACT(EPOCH FROM (a.acknowledged_at - a.created_at)))::numeric / 60, 1) AS avg_response_min,
    ROUND(MAX(EXTRACT(EPOCH FROM (a.acknowledged_at - a.created_at)))::numeric / 60, 1) AS worst_response_min,
    COUNT(DISTINCT a.acknowledged_by)                           AS responders
FROM alert a
JOIN camera c ON c.id = a.camera_id
WHERE a.acknowledged_at IS NOT NULL
  AND a.created_at >= now() - INTERVAL '30 days'
GROUP BY c.name
ORDER BY avg_response_min DESC;


-- 3.6 Repeat offenders — exits blocked on the most separate days.
-- Distinct days, not event count: one exit blocked 40 times in a single
-- afternoon is one bad day, while one blocked once on 20 different days is a
-- standing habit. The second is the harder problem.
SELECT
    c.name                                                      AS camera_name,
    c.location,
    COUNT(DISTINCT date_trunc('day', e.started_at))             AS days_blocked,
    COUNT(*)                                                    AS total_events,
    ROUND(SUM(
        COALESCE(e.duration_s,
                 EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)))
    )::numeric / 3600, 2)                                       AS total_blocked_hours
FROM blockage_event e
JOIN camera c ON c.id = e.camera_id
WHERE e.started_at >= now() - INTERVAL '90 days'
GROUP BY c.name, c.location
ORDER BY days_blocked DESC, total_blocked_hours DESC;


-- ===========================================================================
-- 4. Maintenance
-- ===========================================================================

-- 4.1 What the retention job would delete.
-- The service prunes on its own schedule (RETENTION_* in .env); this is the
-- dry run, so the effect can be seen before trusting it.
SELECT 'blockage_event' AS table_name,
       COUNT(*)         AS rows_beyond_retention,
       MIN(started_at)  AS oldest
FROM blockage_event
WHERE started_at < now() - INTERVAL '90 days'      -- EVENT_RETENTION_DAYS
UNION ALL
SELECT 'alert',
       COUNT(*),
       MIN(created_at)
FROM alert
WHERE created_at < now() - INTERVAL '90 days';     -- ALERT_RETENTION_DAYS


-- 4.2 Events that never closed.
-- A worker killed mid-blockage leaves ended_at NULL forever, and such a row
-- inflates every duration average through the now() fallback. Anything open
-- for days is almost certainly this rather than a genuine multi-day blockage.
SELECT
    e.id,
    c.name                                                      AS camera_name,
    e.started_at,
    ROUND(EXTRACT(EPOCH FROM (now() - e.started_at))::numeric / 3600, 1) AS open_for_hours,
    e.state,
    e.peak_state
FROM blockage_event e
JOIN camera c ON c.id = e.camera_id
WHERE e.ended_at IS NULL
  AND e.started_at < now() - INTERVAL '1 day'
ORDER BY e.started_at;


-- 4.3 Table sizes and row counts.
SELECT
    relname                                                     AS table_name,
    n_live_tup                                                  AS approx_rows,
    pg_size_pretty(pg_total_relation_size(relid))               AS total_size,
    pg_size_pretty(pg_indexes_size(relid))                      AS index_size
FROM pg_stat_user_tables
WHERE relname IN ('camera', 'blockage_event', 'alert')
ORDER BY pg_total_relation_size(relid) DESC;


-- 4.4 Snapshot files referenced by surviving events.
-- Retention prunes rows and files on separate criteria, so the two can drift.
-- Anything on disk that this query does not list is an orphan.
SELECT snapshot_path
FROM blockage_event
WHERE snapshot_path IS NOT NULL
ORDER BY started_at DESC;
