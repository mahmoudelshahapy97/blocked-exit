import { expect, request as playwrightRequest, test as base } from "@playwright/test";

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

/**
 * The account the suite acts as. On an empty database it is created by the
 * bootstrap signup and becomes the superadmin; on a populated one it must
 * already exist (create it under Users, or point these at an existing
 * superadmin).
 */
export const E2E_USER = process.env.E2E_USERNAME || "e2e.admin";
export const E2E_PASSWORD = process.env.E2E_PASSWORD || "E2e-Admin-Pass-1";

/** Where the console keeps the refresh token (frontend/src/api/tokenStore.js). */
const REFRESH_KEY = "blocked-exit:refresh-token";

/**
 * A fresh token pair for `username`. Refresh tokens rotate on every use, so
 * each test gets its own pair instead of sharing a saved browser session.
 */
export async function loginPair(baseURL, username = E2E_USER, password = E2E_PASSWORD) {
  const api = await playwrightRequest.newContext({ baseURL });
  try {
    const bootstrap = await (await api.get(`${API}/auth/bootstrap`)).json();
    if (bootstrap.needs_bootstrap && username === E2E_USER) {
      const signup = await api.post(`${API}/auth/signup`, {
        data: { username, email: `${username}@example.com`, password, workspace_name: "E2E" },
      });
      if (signup.ok()) return signup.json();
    }
    const response = await api.post(`${API}/auth/login`, { data: { username, password } });
    if (!response.ok()) {
      throw new Error(
        `Could not log in as ${username} (${response.status()}). On a database that ` +
          "already has accounts, set E2E_USERNAME/E2E_PASSWORD to a superadmin."
      );
    }
    return response.json();
  } finally {
    await api.dispose();
  }
}

/**
 * Open the console already signed in, the way a reload resumes a session.
 * The init script runs on every navigation, so it only seeds an empty slot:
 * the console rotates the token on first use, and putting the original back
 * would hand it a refresh token the server has already burned.
 */
export async function signInPage(page, pair) {
  await page.addInitScript(
    ([key, token]) => {
      if (!window.localStorage.getItem(key)) window.localStorage.setItem(key, token);
    },
    [REFRESH_KEY, pair.refresh_token]
  );
}

/**
 * `test` with a signed-in `page` and an authenticated `request`, both acting
 * as E2E_USER in its active workspace.
 */
export const test = base.extend({
  session: async ({ baseURL }, use) => {
    await use(await loginPair(baseURL));
  },
  request: async ({ baseURL, session }, use) => {
    const context = await playwrightRequest.newContext({
      baseURL,
      extraHTTPHeaders: { Authorization: `Bearer ${session.access_token}` },
    });
    await use(context);
    await context.dispose();
  },
  page: async ({ page, session }, use) => {
    await signInPage(page, session);
    await use(page);
  },
});

export { expect };

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
