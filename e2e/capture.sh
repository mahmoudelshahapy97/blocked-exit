#!/usr/bin/env bash
# Photograph the operator console end to end into artifact/.
#
# Same container and same contract as run.sh -- see that file for why the tests
# run inside Microsoft's Playwright image on the host network. The one addition
# here is that artifact/ is mounted into the container so the screenshots land
# in the repo rather than inside a container that is about to be removed.
#
#   cd features/blocked&exit
#   docker compose up -d --build
#   ./e2e/capture.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"
IMAGE="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.50.0-noble}"
BASE_URL="${BASE_URL:-http://localhost:8081}"
ARTIFACT="${ARTIFACT_DIR:-${ROOT}/artifact}"

echo "[capture] waiting for ${BASE_URL} to answer"
for attempt in $(seq 1 60); do
  if curl -fsS "${BASE_URL}/api/v1/health" >/dev/null 2>&1; then
    echo "[capture] stack is up (attempt ${attempt})"
    break
  fi
  if [ "${attempt}" -eq 60 ]; then
    echo "[capture] ${BASE_URL} never became ready — is 'docker compose up -d' running?" >&2
    exit 1
  fi
  sleep 2
done

mkdir -p "${ARTIFACT}"
docker volume create blocked-exit-e2e-node-modules >/dev/null

docker run --rm \
  --network host \
  -e BASE_URL="${BASE_URL}" \
  -e ARTIFACT_DIR=/artifact \
  -v "${HERE}:/e2e" \
  -v "${ARTIFACT}:/artifact" \
  -v blocked-exit-e2e-node-modules:/e2e/node_modules \
  -w /e2e \
  --user root \
  "${IMAGE}" \
  bash -lc "npm install --no-audit --no-fund --silent && node capture-artifact.mjs"

echo "[capture] artifact written to ${ARTIFACT}"
