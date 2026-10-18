# Database — Blocked Exit Detection

PostgreSQL 16. **Alembic owns the schema of a running deployment** — the files
here are for the jobs Alembic does not do.

| File | What it is | When you want it |
|---|---|---|
| `schema.sql` | Full DDL, mirroring `backend/alembic/versions/` up to the newest revision (see its stamp note) | Reading the shape of the database without a Python environment; provisioning a reporting replica; diffing deployed vs. expected |
| `seed.sql` | A demo workspace with one account per role, four exits across a location hierarchy, and event and alert history in every lifecycle status | A populated UI to develop against, with no cameras and no ML stack |
| `queries.sql` | The SQL behind `/api/v1/analytics`, plus operational queries the API does not expose | Answering "what actually blocks these exits" and "is anyone acknowledging alerts" |

## Connecting

The stack runs Postgres in Docker. From `backend/`:

```bash
docker compose up -d postgres
```

`.env` publishes it on **5433** (`POSTGRES_PORT`), not the default 5432, so it
can coexist with another Postgres already on this machine.

```bash
psql -h 127.0.0.1 -p 5433 -U insighteye -d blocked_exit   # password: insighteye
```

> **Windows + Docker inside WSL2** (no Docker Desktop). Two things bite here:
>
> 1. `localhost:5433` forwarding from Windows into WSL is unreliable — it works,
>    then stops. Use the WSL IP instead: `wsl hostname -I`. That is why
>    `backend/.env` points `DATABASE_URL` at an IP rather than localhost.
> 2. WSL terminates when idle and takes the Docker daemon — and every running
>    container — with it. The `pgdata` volume survives; the daemon needs
>    starting again (`sudo service docker start` inside WSL) before the
>    container comes back.

## Loading the files

```bash
# Schema — only for a database Alembic is not managing (see the note at the
# foot of schema.sql before pointing Alembic at one provisioned this way).
psql -h 127.0.0.1 -p 5433 -U insighteye -d blocked_exit -f schema.sql

# Demo data. Development only — it writes fabricated incident history.
psql -h 127.0.0.1 -p 5433 -U insighteye -d blocked_exit -f seed.sql
```

Both are re-runnable: `schema.sql` creates everything `IF NOT EXISTS`, and
`seed.sql` upserts its cameras on their unique name and replaces only its own
event rows, so a second load leaves the same data rather than doubling it.

`queries.sql` is a reference, not a script — run the block you want.

## The tables

```
workspace ──┬──< workspace_member >── app_user ──< revoked_token
            ├──< camera ──┬──< blockage_event ──< alert
            │             └──< alert
            └── (workspace_id on camera, blockage_event and alert)
```

- **`app_user`** — `role` is the platform role: `superadmin` (users,
  workspaces, rosters, any workspace), `admin` (workspace admin wherever it is
  a member) or `user`. `default_workspace_id` is the user's **active**
  workspace, switched server-side.
- **`workspace_member`** — `admin` > `member` > `viewer` inside one workspace.
- **`revoked_token`** — burned refresh tokens and per-user "sign out
  everywhere" cutoffs.

- **`camera`** — one monitored exit, placed by `location` > `area` >
  `building` > `floor_level` > `zone` (the hierarchy every filter uses). Holds the exit region as a JSONB polygon
  normalized to `[0,1]`, so it survives the camera being replaced with one of a
  different resolution. Its threshold columns are nullable on purpose: `NULL`
  means "inherit the global `.env` value", which is a different thing from `0`.
- **`blockage_event`** — one confirmed obstruction episode. A row appears only
  after the obstruction has outlasted `CONFIRM_SECONDS`, so passers-by never
  become events. `peak_state` records the worst it got, which `state` alone
  would understate; `risk_level` the worst risk band; `confidence` /
  `avg_confidence` the peak and mean detection confidence of what blocked it.
  `status` is the operator workflow, `detected` → `acknowledged` →
  `resolved`, with who and when for each step — independent of `ended_at`,
  because a blockage can clear long before anyone looks at it.
- **`alert`** — one delivery attempt on one channel. Failures are kept rather
  than overwritten; "we tried and it failed" is the fact an audit needs.

Deleting a camera cascades to its events and alerts; deleting a workspace
(only once deactivated) cascades to everything in it.

## The one trap in every query

**An open event has no `duration_s`.** The pipeline writes it only when it
closes the event, so any query that sums or averages duration must fall back to
`now() - started_at`:

```sql
COALESCE(
    duration_s,
    EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at))
)
```

Without it, a `SUM(duration_s)` silently ignores exactly the blockages that are
still happening — the ones that matter most. Everything in `queries.sql` uses
this form, matching `_effective_duration()` in
`backend/app/services/analytics.py`.
