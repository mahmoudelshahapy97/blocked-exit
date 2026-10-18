-- ---------------------------------------------------------------------------
-- InsightEye — Blocked Exit Detection : schema
--
-- Mirrors backend/alembic/versions/ (0001 through the newest revision named in
-- the stamp note at the foot of this file) exactly. Alembic remains the source of truth for
-- a running deployment; this file exists for the cases Alembic cannot serve —
-- reviewing the shape of the database without a Python environment,
-- provisioning a read-replica or reporting schema, and diffing what is
-- deployed against what is expected.
--
--   psql -h <host> -p 5433 -U insighteye -d blocked_exit -f schema.sql
--
-- Safe to re-run: every object is created IF NOT EXISTS. It does NOT write the
-- alembic_version row — see the note at the foot of this file before pointing
-- Alembic at a database provisioned this way. It also does NOT do the
-- default-workspace backfill 0002 performs on an *existing* database — this
-- file provisions a fresh one, where there is nothing to adopt.
-- ---------------------------------------------------------------------------

BEGIN;

-- ---------------------------------------------------------------------------
-- workspace — one tenant. Every camera, event and alert belongs to exactly one.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workspace (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    -- URL-safe identifier: addressable in a path or a support ticket without
    -- exposing a sequential id.
    slug         VARCHAR(64)  NOT NULL,
    description  VARCHAR(500),
    -- Enforced on camera create, not by a constraint here: the limit is a
    -- business rule that changes per plan, and a tightened default must not
    -- make existing rows unwritable.
    camera_quota INTEGER      NOT NULL DEFAULT 25,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,

    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_workspace_name ON workspace (name);
CREATE UNIQUE INDEX IF NOT EXISTS ix_workspace_slug ON workspace (slug);

-- ---------------------------------------------------------------------------
-- app_user — a person who can log in. Not "user": reserved in Postgres.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_user (
    id                   SERIAL PRIMARY KEY,
    username             VARCHAR(64)  NOT NULL,
    -- Stored lowercased so "Ada@x.com" and "ada@x.com" cannot both register.
    email                VARCHAR(255) NOT NULL,
    full_name            VARCHAR(160),

    password_hash        VARCHAR(255) NOT NULL,   -- argon2
    -- Platform-wide role, independent of any workspace membership, as on the
    -- InsightEye platform: 'superadmin' runs the deployment (users, workspaces,
    -- rosters) and may open any workspace; 'admin' acts as a workspace admin
    -- wherever it is a member; 'user' gets its membership role.
    role                 VARCHAR(16)  NOT NULL DEFAULT 'user'
        CONSTRAINT ck_app_user_role CHECK (role IN ('superadmin', 'admin', 'user')),
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,

    -- The user's ACTIVE workspace: every request acts in it, and it is
    -- switched server-side (POST /workspaces/{id}/activate), so all of a
    -- user's sessions agree. ON DELETE SET NULL: losing a workspace must not
    -- delete the person who was looking at it.
    default_workspace_id INTEGER
        REFERENCES workspace (id) ON DELETE SET NULL,

    last_login_at        TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_app_user_username             ON app_user (username);
CREATE UNIQUE INDEX IF NOT EXISTS ix_app_user_email                ON app_user (email);
CREATE        INDEX IF NOT EXISTS ix_app_user_role                 ON app_user (role);
CREATE        INDEX IF NOT EXISTS ix_app_user_is_active            ON app_user (is_active);
CREATE        INDEX IF NOT EXISTS ix_app_user_default_workspace_id ON app_user (default_workspace_id);

-- ---------------------------------------------------------------------------
-- workspace_member — one user's role in one workspace
--
-- 'admin' | 'member' | 'viewer', ranked in that order — the platform's
-- workspace roles, see app.core.enums.WorkspaceRole. A user may belong to
-- several workspaces with a different role in each, so authorisation is always
-- the pair (user, workspace), never the user alone. Only a superadmin edits
-- this table; every workspace keeps at least one admin.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workspace_member (
    id           SERIAL PRIMARY KEY,
    workspace_id INTEGER     NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    user_id      INTEGER     NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    role         VARCHAR(16) NOT NULL DEFAULT 'member',

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_workspace_member UNIQUE (workspace_id, user_id),
    CONSTRAINT ck_workspace_member_role CHECK (role IN ('admin', 'member', 'viewer'))
);

CREATE INDEX IF NOT EXISTS ix_workspace_member_workspace_id     ON workspace_member (workspace_id);
CREATE INDEX IF NOT EXISTS ix_workspace_member_user_id          ON workspace_member (user_id);
CREATE INDEX IF NOT EXISTS ix_workspace_member_user_workspace   ON workspace_member (user_id, workspace_id);

-- ---------------------------------------------------------------------------
-- revoked_token — tokens invalidated before their natural expiry
--
-- Keyed on jti (a fixed 36-char uuid), not the raw JWT, which is hundreds of
-- bytes and grows with the claims. A row past expires_at is dead weight — the
-- signature check rejects an expired token on its own — and is dropped by the
-- retention sweep. token_type = 'cutoff' rows are the exception: those are a
-- per-user "invalidate everything issued before this moment" marker (used on
-- password change), compared by revoked_at rather than expires_at, and kept
-- until no token of the maximum lifetime could still predate them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS revoked_token (
    id          SERIAL PRIMARY KEY,
    jti         VARCHAR(64)  NOT NULL,
    user_id     INTEGER
        REFERENCES app_user (id) ON DELETE CASCADE,
    token_type  VARCHAR(16)  NOT NULL DEFAULT 'access',  -- access|refresh|cutoff
    reason      VARCHAR(120),

    expires_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_revoked_token_jti        ON revoked_token (jti);
CREATE        INDEX IF NOT EXISTS ix_revoked_token_user_id    ON revoked_token (user_id);
CREATE        INDEX IF NOT EXISTS ix_revoked_token_expires_at ON revoked_token (expires_at);

-- ---------------------------------------------------------------------------
-- camera — one monitored emergency exit, fed by one stream
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camera (
    id                    SERIAL PRIMARY KEY,
    workspace_id          INTEGER      NOT NULL
        REFERENCES workspace (id) ON DELETE CASCADE,
    name                  VARCHAR(120)             NOT NULL,
    -- Where the exit is, coarsest to finest — the platform's camera
    -- hierarchy. Events and analytics filter by any level (exact match, OR
    -- within a level, AND across levels). NULL means "not set", never ''.
    location              VARCHAR(255),
    area                  VARCHAR(100),
    building              VARCHAR(100),
    floor_level           VARCHAR(20),
    zone                  VARCHAR(100),
    -- rtsp:// URL, or a local video file path when exercising the pipeline
    -- without hardware. Long enough for a URL carrying credentials.
    rtsp_url              VARCHAR(512)             NOT NULL,
    enabled               BOOLEAN                  NOT NULL DEFAULT TRUE,

    -- 'zone_based' | 'door_centric'. Deliberately not an enum type: the
    -- registry falls back to the default strategy when the selected one is
    -- unavailable, so an unknown value must degrade rather than fail the write.
    strategy              VARCHAR(32)              NOT NULL DEFAULT 'zone_based',

    -- The exit region, normalized to [0,1]: [[x, y], ...]. Normalized so the
    -- region survives this camera being swapped for one of another resolution.
    door_polygon          JSONB,
    -- Unobstructed door bbox for the door-centric strategy, normalized
    -- [x1, y1, x2, y2].
    reference_bbox        JSONB,
    reference_captured_at TIMESTAMPTZ,

    -- Per-camera overrides. NULL means "inherit the global .env value", which
    -- is why every one of these is nullable rather than defaulted here: a
    -- default would silently pin the camera to today's global value.
    clear_min_pct         DOUBLE PRECISION,
    full_max_pct          DOUBLE PRECISION,
    confirm_seconds       DOUBLE PRECISION,
    clear_seconds         DOUBLE PRECISION,
    process_fps           DOUBLE PRECISION,

    created_at            TIMESTAMPTZ              NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ              NOT NULL DEFAULT now(),

    -- Scoped uniqueness, not global: two tenants must each be able to have an
    -- exit called "Stairwell B" without one of them having to rename it.
    CONSTRAINT uq_camera_workspace_name UNIQUE (workspace_id, name)
);

CREATE        INDEX IF NOT EXISTS ix_camera_workspace_id       ON camera (workspace_id);
CREATE        INDEX IF NOT EXISTS ix_camera_name               ON camera (name);
CREATE        INDEX IF NOT EXISTS ix_camera_enabled            ON camera (enabled);
CREATE        INDEX IF NOT EXISTS ix_camera_workspace_enabled  ON camera (workspace_id, enabled);
CREATE        INDEX IF NOT EXISTS ix_camera_workspace_hierarchy
    ON camera (workspace_id, location, area, building, floor_level, zone);

-- ---------------------------------------------------------------------------
-- blockage_event — one confirmed obstruction episode
--
-- A row appears only once the temporal filter has accepted a non-CLEAR state
-- for CONFIRM_SECONDS, so passers-by never become events. ended_at IS NULL
-- means the blockage is still happening.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS blockage_event (
    id                     SERIAL PRIMARY KEY,
    -- Denormalised from camera.workspace_id: analytics groups this table by
    -- tenant on every dashboard poll, and a mandatory join there buys nothing.
    workspace_id           INTEGER      NOT NULL
        REFERENCES workspace (id) ON DELETE CASCADE,
    camera_id              INTEGER      NOT NULL
        REFERENCES camera (id) ON DELETE CASCADE,

    started_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    ended_at               TIMESTAMPTZ,
    -- Written when the event closes. NULL on an open event — every query that
    -- reports duration must therefore fall back to (now() - started_at).
    duration_s             DOUBLE PRECISION,

    state                  VARCHAR(16)  NOT NULL DEFAULT 'PARTIAL',
    -- The worst state reached during the episode, which is what an incident
    -- review cares about — 'state' alone would understate a blockage that had
    -- already partly cleared by the time it was closed.
    peak_state             VARCHAR(16)  NOT NULL DEFAULT 'PARTIAL',
    strategy               VARCHAR(32)  NOT NULL DEFAULT 'zone_based',

    min_accessibility_pct  DOUBLE PRECISION NOT NULL DEFAULT 100.0,
    last_accessibility_pct DOUBLE PRECISION NOT NULL DEFAULT 100.0,
    peak_risk_score        DOUBLE PRECISION NOT NULL DEFAULT 0.0,

    -- [{label, class_id, confidence, track_id, bbox, area_pct}, ...]
    blocking_objects       JSONB,
    snapshot_path          VARCHAR(512)
);

CREATE INDEX IF NOT EXISTS ix_blockage_event_workspace_id      ON blockage_event (workspace_id);
CREATE INDEX IF NOT EXISTS ix_blockage_event_camera_id         ON blockage_event (camera_id);
CREATE INDEX IF NOT EXISTS ix_blockage_event_started_at        ON blockage_event (started_at);
-- Composite: every analytics query filters by camera/tenant and time window together.
CREATE INDEX IF NOT EXISTS ix_blockage_event_camera_started    ON blockage_event (camera_id, started_at);
CREATE INDEX IF NOT EXISTS ix_blockage_event_workspace_started ON blockage_event (workspace_id, started_at);

-- ---------------------------------------------------------------------------
-- alert — one delivery attempt, on one channel, for one event
--
-- One event produces several rows when multiple channels are configured, and
-- a failed delivery is kept rather than overwritten: "we tried and it failed"
-- is the fact an audit needs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert (
    id              SERIAL PRIMARY KEY,
    -- Denormalised from camera.workspace_id -- see blockage_event.workspace_id.
    workspace_id    INTEGER      NOT NULL
        REFERENCES workspace (id) ON DELETE CASCADE,
    camera_id       INTEGER      NOT NULL
        REFERENCES camera (id) ON DELETE CASCADE,
    -- Nullable: a test alert is dispatched against a camera without opening
    -- an event.
    event_id        INTEGER
        REFERENCES blockage_event (id) ON DELETE CASCADE,

    channel         VARCHAR(16)  NOT NULL,   -- 'webhook' | 'email'
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending',
                                            -- 'pending'|'sent'|'failed'|'skipped'
    error           TEXT,
    -- The exact body that was delivered, kept verbatim so a webhook consumer's
    -- complaint can be checked against what was actually sent.
    payload         JSONB,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(120)
);

CREATE INDEX IF NOT EXISTS ix_alert_workspace_id      ON alert (workspace_id);
CREATE INDEX IF NOT EXISTS ix_alert_camera_id         ON alert (camera_id);
CREATE INDEX IF NOT EXISTS ix_alert_event_id          ON alert (event_id);
CREATE INDEX IF NOT EXISTS ix_alert_status            ON alert (status);
CREATE INDEX IF NOT EXISTS ix_alert_created_at        ON alert (created_at);
CREATE INDEX IF NOT EXISTS ix_alert_camera_created    ON alert (camera_id, created_at);
CREATE INDEX IF NOT EXISTS ix_alert_workspace_created ON alert (workspace_id, created_at);

COMMIT;

-- ---------------------------------------------------------------------------
-- Using this file with Alembic
--
-- Alembic tracks the schema in its own table. A database provisioned from this
-- file has the tables but no version row, so `alembic upgrade head` would try
-- to create them a second time and fail. Stamp it instead:
--
--   alembic stamp 0004
--
-- Equivalent to, from psql:
--
--   CREATE TABLE IF NOT EXISTS alembic_version (
--       version_num VARCHAR(32) NOT NULL CONSTRAINT alembic_version_pkc PRIMARY KEY
--   );
--   INSERT INTO alembic_version (version_num) VALUES ('0004')
--       ON CONFLICT DO NOTHING;
-- ---------------------------------------------------------------------------
