#!/usr/bin/env bash
# Wait for Postgres, apply migrations, then hand over to the CMD.
#
# Migrations run here rather than in the application so that a failed upgrade
# stops the container instead of leaving a running API on a half-known schema.
set -euo pipefail

RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"
ATTEMPTS="${DB_WAIT_ATTEMPTS:-60}"

# Derive host/port from DATABASE_URL when they are not given explicitly, so a
# single setting stays the source of truth.
if [ -z "${POSTGRES_HOST:-}" ] || [ -z "${POSTGRES_WAIT_PORT:-}" ]; then
  eval "$(python - <<'PY'
import os
from urllib.parse import urlsplit

url = os.environ.get("DATABASE_URL", "")
parsed = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1))
print(f'POSTGRES_HOST="{parsed.hostname or "postgres"}"')
print(f'POSTGRES_WAIT_PORT="{parsed.port or 5432}"')
PY
)"
fi

HOST="${POSTGRES_HOST:-postgres}"
PORT="${POSTGRES_WAIT_PORT:-5432}"

echo "[entrypoint] waiting for postgres at ${HOST}:${PORT}"
for i in $(seq 1 "${ATTEMPTS}"); do
  if python -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${HOST}', ${PORT}))
except OSError:
    sys.exit(1)
finally:
    s.close()
" 2>/dev/null; then
    echo "[entrypoint] postgres is up (attempt ${i})"
    break
  fi
  if [ "${i}" -eq "${ATTEMPTS}" ]; then
    echo "[entrypoint] postgres not reachable after ${ATTEMPTS} attempts" >&2
    exit 1
  fi
  sleep 1
done

if [ "${RUN_MIGRATIONS}" = "true" ]; then
  echo "[entrypoint] applying migrations"
  alembic upgrade head
else
  echo "[entrypoint] RUN_MIGRATIONS=${RUN_MIGRATIONS} — skipping migrations"
fi

echo "[entrypoint] starting: $*"
exec "$@"
