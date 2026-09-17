/**
 * Walk the operator console in a real browser and photograph every step.
 *
 * This is the visual counterpart to the assertions in tests/: same journey,
 * same live stack, but the output is a numbered sequence of screenshots in
 * artifact/ that can be read by someone who will never run the suite. Where a
 * test proves the polygon round-tripped, this shows you the polygon.
 *
 * It owns its own camera from creation to deletion, so it can run before,
 * after or instead of the test suite without colliding with it.
 *
 *   ./e2e/capture.sh                      # against http://localhost:8081
 *   BASE_URL=http://localhost:5173 ./e2e/capture.sh
 */
import { chromium } from "@playwright/test";
import { mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

const BASE_URL = process.env.BASE_URL || "http://localhost:8081";
const OUT_DIR = process.env.ARTIFACT_DIR || "/artifact";
const API = `${BASE_URL}/api/v1`;

const CAMERA_NAME = "Exit A — Concourse";
const CAMERA_LOCATION = "Terminal 1, Concourse";
/** Bind-mounted into the api container; see docker-compose.yml. */
const VIDEO_SOURCE = "/app/data/5.mp4";

const DESKTOP = { width: 1600, height: 1000 };
const MOBILE = { width: 390, height: 844 };

/** Everything written, in order, for the manifest at the end. */
const shots = [];
let step = 0;

async function shot(page, name, { fullPage = false } = {}) {
  step += 1;
  const file = `${String(step).padStart(2, "0")}-${name}.png`;
  await page.screenshot({ path: join(OUT_DIR, file), fullPage });
  shots.push({ file, name });
  console.log(`  [${String(step).padStart(2, "0")}] ${file}`);
  return file;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : null };
}

/** Poll the status endpoint until the worker has an actual verdict to show.
 *  Screenshotting before that photographs a spinner. */
async function waitForVerdict(cameraId, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    const { status, body } = await api(`/monitoring/${cameraId}/status`);
    if (status === 200) {
      last = body;
      if (body.worker_state === "running" && body.state !== "UNKNOWN") return body;
    }
    await sleep(3000);
  }
  throw new Error(`no verdict within ${timeoutMs}ms; last: ${JSON.stringify(last)}`);
}

/** Let MUI's transitions land and the polling components paint once. */
async function settle(page, ms = 1200) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await sleep(ms);
}

async function main() {
  // Empty the directory rather than replacing it: OUT_DIR is a bind mount when
  // this runs in the Playwright container, and rmdir on a mount point is EBUSY.
  await mkdir(OUT_DIR, { recursive: true });
  for (const entry of await readdir(OUT_DIR)) {
    await rm(join(OUT_DIR, entry), { recursive: true, force: true });
  }

  // Start from a known state: a leftover camera from an interrupted run would
  // put a stranger in every screenshot.
  const existing = await api("/cameras");
  for (const camera of existing.body || []) {
    if (camera.name === CAMERA_NAME) {
      await api(`/monitoring/${camera.id}/stop`, { method: "POST" }).catch(() => {});
      await api(`/cameras/${camera.id}`, { method: "DELETE" });
    }
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: DESKTOP,
    deviceScaleFactor: 1,
    colorScheme: "dark",
  });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  console.log(`Capturing ${BASE_URL} -> ${OUT_DIR}`);

  // --- the console before anything is registered -------------------------
  await page.goto(BASE_URL);
  await settle(page);
  await shot(page, "dashboard-empty");

  await page.getByRole("link", { name: "Exits", exact: true }).click();
  await settle(page);
  await shot(page, "exits-empty");

  // --- registering an exit ------------------------------------------------
  await page.getByRole("link", { name: /add exit/i }).click();
  await settle(page);
  await shot(page, "camera-form-blank");

  // Submitting nothing: the required fields must say so rather than posting.
  await page.getByRole("button", { name: /create exit/i }).click();
  await settle(page, 600);
  await shot(page, "camera-form-required");

  // Inverted thresholds would make PARTIAL unreachable. The backend validates
  // each bound alone, so this guard only exists in the form.
  await page.getByLabel("Name").fill(CAMERA_NAME);
  await page.getByLabel("Stream source").fill(VIDEO_SOURCE);
  await page.getByLabel("CLEAR threshold").fill("40");
  await page.getByLabel("FULL threshold").fill("60");
  await page.getByRole("button", { name: /create exit/i }).click();
  await settle(page, 600);
  await shot(page, "camera-form-threshold-error");

  await page.getByLabel("Location").fill(CAMERA_LOCATION);
  await page.getByLabel("CLEAR threshold").fill("85");
  await page.getByLabel("FULL threshold").fill("40");
  await page.getByLabel("Confirm seconds").fill("2");
  await page.getByLabel("Clear seconds").fill("2");
  await page.getByLabel("Process FPS").fill("3");
  await settle(page, 600);
  await shot(page, "camera-form-filled");

  await page.getByRole("button", { name: /create exit/i }).click();
  // Zone-based is useless without a region, so the app routes there itself.
  await page.waitForURL(/\/cameras\/\d+\/zone$/, { timeout: 60_000 });

  const cameraId = Number(page.url().match(/\/cameras\/(\d+)\/zone$/)[1]);
  console.log(`  camera id = ${cameraId}`);

  // --- drawing the exit region -------------------------------------------
  // The frame is decoded from the clip by the backend; on a cold container
  // that first read is slow.
  await page.getByText(/frame is \d+x\d+px/i).waitFor({ timeout: 120_000 });
  await settle(page);
  await shot(page, "zone-editor-frame");

  const canvas = page.locator("canvas");
  const box = await canvas.boundingBox();
  const corners = [
    [0.30, 0.25],
    [0.72, 0.25],
    [0.72, 0.88],
    [0.30, 0.88],
  ];
  for (const [fx, fy] of corners) {
    await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
    await sleep(350);
  }
  await settle(page, 600);
  await shot(page, "zone-polygon-drawn");

  await page.getByRole("button", { name: /save region/i }).click();
  await page.waitForURL(new RegExp(`/cameras/${cameraId}$`), { timeout: 60_000 });
  await settle(page);
  await shot(page, "camera-detail-idle");

  // --- monitoring ---------------------------------------------------------
  const start = page.getByRole("button", { name: /start monitoring/i });
  if (await start.isVisible().catch(() => false)) await start.click();

  const verdict = await waitForVerdict(cameraId);
  console.log(
    `  verdict: ${verdict.state} ${verdict.accessibility_pct}% accessible, ` +
      `${verdict.people_count} people, ${verdict.blocking_objects.length} objects`
  );
  // Give the annotator a few more frames so the live view is not the first,
  // emptiest one.
  await sleep(20_000);

  await page.reload();
  await settle(page, 4000);
  await shot(page, "camera-detail-monitoring", { fullPage: true });

  // The annotated frame on its own, straight from the endpoint the live view
  // points at — the clearest single picture of what the detector is doing.
  const snapshot = await fetch(`${API}/monitoring/${cameraId}/snapshot?annotated=true`);
  const buffer = Buffer.from(await snapshot.arrayBuffer());
  await writeFile(join(OUT_DIR, "annotated-frame.jpg"), buffer);
  shots.push({ file: "annotated-frame.jpg", name: "annotated detector output" });
  console.log(`  [--] annotated-frame.jpg (${buffer.length} bytes)`);

  await page.goto(`${BASE_URL}/cameras`);
  await settle(page, 3000);
  await shot(page, "exits-monitoring");

  await page.goto(BASE_URL);
  await settle(page, 4000);
  await shot(page, "dashboard-live");

  // --- what monitoring produced -------------------------------------------
  await page.getByRole("link", { name: "Events", exact: true }).click();
  await settle(page, 2000);
  await shot(page, "events");

  await page.getByRole("combobox", { name: "Exit" }).click();
  await page.getByRole("option", { name: CAMERA_NAME }).click();
  await settle(page, 2000);
  await shot(page, "events-filtered");

  // An alert with no blockage to report: /alerts/test exercises delivery
  // without waiting for the clip to obstruct itself.
  await api("/alerts/test", {
    method: "POST",
    body: JSON.stringify({ camera_id: cameraId }),
  });

  await page.getByRole("link", { name: "Alerts", exact: true }).click();
  await settle(page, 2000);
  await shot(page, "alerts");

  const pending = await api(`/alerts?camera_id=${cameraId}&unacknowledged_only=true&limit=5`);
  if (pending.body?.total) {
    const alertId = pending.body.items[0].id;
    const row = page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: String(alertId), exact: true }) })
      .first();
    await row.getByRole("button").last().click();
    await settle(page, 800);
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Your name").fill("duty-officer");
    await shot(page, "alert-acknowledge-dialog");
    await dialog.getByRole("button", { name: "Acknowledge" }).click();
    await settle(page, 2500);
    await shot(page, "alerts-acknowledged");
  }

  await page.getByRole("link", { name: "Analytics", exact: true }).click();
  await settle(page, 3000);
  await shot(page, "analytics", { fullPage: true });

  await page.getByRole("combobox", { name: "Window" }).click();
  await page.getByRole("option", { name: /30/ }).first().click();
  await settle(page, 3000);
  await shot(page, "analytics-30-days", { fullPage: true });

  // --- editing ------------------------------------------------------------
  await page.goto(`${BASE_URL}/cameras/${cameraId}/edit`);
  await settle(page, 1500);
  await shot(page, "camera-form-edit");

  // --- the light theme, the 404, and a phone ------------------------------
  await page.goto(BASE_URL);
  await settle(page, 2500);
  await page.getByRole("button", { name: /switch to light/i }).click();
  await settle(page, 1500);
  await shot(page, "dashboard-light-theme");
  await page.getByRole("button", { name: /switch to dark/i }).click();
  await settle(page, 800);

  await page.goto(`${BASE_URL}/no-such-page`);
  await settle(page, 1000);
  await shot(page, "not-found");

  await page.setViewportSize(MOBILE);
  await page.goto(BASE_URL);
  await settle(page, 3000);
  await shot(page, "mobile-dashboard");

  await page.goto(`${BASE_URL}/cameras/${cameraId}`);
  await settle(page, 3000);
  await shot(page, "mobile-camera-detail");
  await page.setViewportSize(DESKTOP);

  // --- teardown, photographed ---------------------------------------------
  await page.goto(`${BASE_URL}/cameras`);
  await settle(page, 2500);
  const row = page.getByRole("row", { name: new RegExp(CAMERA_NAME.split("—")[0].trim(), "i") });
  await row.getByRole("button").last().click();
  await settle(page, 600);
  await page.getByRole("menuitem", { name: /delete/i }).click();
  await settle(page, 800);
  await shot(page, "delete-confirm");

  await page.getByRole("dialog").getByRole("button", { name: /delete/i }).click();
  await settle(page, 2500);
  await shot(page, "exits-after-delete");

  // --- manifest -----------------------------------------------------------
  const manifest = {
    captured_at: new Date().toISOString(),
    base_url: BASE_URL,
    camera: { id: cameraId, name: CAMERA_NAME, source: VIDEO_SOURCE },
    verdict: {
      state: verdict.state,
      accessibility_pct: verdict.accessibility_pct,
      occupied_pct: verdict.occupied_pct,
      people_count: verdict.people_count,
      blocking_objects: verdict.blocking_objects.length,
      risk_level: verdict.risk_level,
      strategy: verdict.strategy,
    },
    page_errors: consoleErrors,
    screenshots: shots,
  };
  await writeFile(join(OUT_DIR, "manifest.json"), JSON.stringify(manifest, null, 2));

  await context.close();
  await browser.close();

  console.log(`\n${shots.length} files written to ${OUT_DIR}`);
  if (consoleErrors.length) {
    console.log(`page errors during the walkthrough:\n  ${consoleErrors.join("\n  ")}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
