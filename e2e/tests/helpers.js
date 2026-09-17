/**
 * Shared vocabulary for the suite.
 *
 * The specs are ordered files run by a single worker (see playwright.config.js),
 * so they form one story: 01 checks the shell, 02 registers an exit and gets a
 * worker detecting on it, 03 reads what that produced, 04 tears it down. State
 * that has to survive between files is re-read from the API rather than kept in
 * a module variable, because each spec file gets a fresh module registry.
 */

/** The camera every spec after 01 operates on. Fixed name: the backend enforces
 *  uniqueness, so a stable name also means a re-run cleans up after itself. */
export const CAMERA_NAME = "E2E Exit — clip 5";
export const CAMERA_LOCATION = "Building 1, Floor 1";

/** Path inside the api container. backend/data is bind-mounted to /app/data,
 *  so the clip committed next to the backend is what the worker decodes. */
export const VIDEO_SOURCE = "/app/data/5.mp4";

export const API = "/api/v1";

/** Find our camera through the API, or null when it is not registered. */
export async function findCamera(request, name = CAMERA_NAME) {
  const response = await request.get(`${API}/cameras`);
  if (!response.ok()) return null;
  const list = await response.json();
  return list.find((camera) => camera.name === name) || null;
}

export async function deleteCameraIfPresent(request, name = CAMERA_NAME) {
  const camera = await findCamera(request, name);
  if (!camera) return false;
  // Stop first: deleting a camera under an open event leaves the worker
  // holding a capture the API can no longer address.
  await request.post(`${API}/monitoring/${camera.id}/stop`).catch(() => {});
  await request.delete(`${API}/cameras/${camera.id}`);
  return true;
}

/**
 * Poll an API predicate until it holds. Used for the things a UI assertion
 * cannot wait on cheaply — a CPU-bound pipeline producing its first verdict.
 */
export async function waitForApi(request, path, predicate, { timeout = 120_000, interval = 2000 } = {}) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    const response = await request.get(`${API}${path}`);
    if (response.ok()) {
      last = await response.json();
      if (predicate(last)) return last;
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error(
    `Timed out after ${timeout}ms waiting on ${path}. Last payload: ${JSON.stringify(last)?.slice(0, 800)}`
  );
}

/**
 * Console and page errors are collected rather than asserted inline: a React
 * page that throws still renders its shell, so a passing visual assertion can
 * hide a broken component.
 */
export function collectPageProblems(page) {
  const problems = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    // MJPEG/snapshot endpoints answer 404 while a worker is not running, and
    // the browser logs the failed <img> load. That is a state the UI handles.
    if (/favicon|ERR_ABORTED|net::ERR_/.test(text)) return;
    problems.push(`console: ${text}`);
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}
