import { expect, test } from "@playwright/test";
import {
  API,
  CAMERA_LOCATION,
  CAMERA_NAME,
  VIDEO_SOURCE,
  collectPageProblems,
  deleteCameraIfPresent,
  findCamera,
  waitForApi,
} from "./helpers.js";

/**
 * The operator journey: add an exit, draw its region, start the worker, watch
 * it produce a verdict. Every step goes through the UI — the API is only read,
 * to assert that what the console showed matches what the backend stored.
 */
test.describe.configure({ mode: "serial" });

/** The list/detail pages render the name; the em dash makes a brittle
 *  selector, so match on the leading words. */
const NAME_RE = new RegExp(CAMERA_NAME.split("—")[0].trim(), "i");

// The name is unique in the database, so a run that died after the create
// would make every later run fail on a duplicate. Clearing it here rather than
// relying on spec 01 keeps this file runnable on its own.
test.beforeAll(async ({ request }) => {
  await deleteCameraIfPresent(request);
});

test("the form refuses an exit with no name and no source", async ({ page }) => {
  await page.goto("/cameras/new");
  await page.getByRole("button", { name: /create exit/i }).click();

  // Client-side validation, so nothing should have been posted.
  await expect(page.getByText("Required").first()).toBeVisible();
  await expect(page).toHaveURL(/\/cameras\/new$/);
});

test("the form rejects a FULL threshold at or above the CLEAR threshold", async ({ page }) => {
  await page.goto("/cameras/new");
  await page.getByLabel("Name").fill("threshold check");
  await page.getByLabel("Stream source").fill(VIDEO_SOURCE);
  await page.getByLabel("CLEAR threshold").fill("40");
  await page.getByLabel("FULL threshold").fill("60");
  await page.getByRole("button", { name: /create exit/i }).click();

  // Inverted bounds would make PARTIAL unreachable. The backend validates each
  // bound alone and would accept this, so the guard has to be here.
  await expect(page.getByText(/must be below the clear threshold/i)).toBeVisible();
  await expect(page).toHaveURL(/\/cameras\/new$/);
});

test("registering an exit against the test clip lands on the zone editor", async ({ page, request }) => {
  const problems = collectPageProblems(page);

  await page.goto("/cameras");
  await page.getByRole("link", { name: /add exit/i }).click();
  await expect(page).toHaveURL(/\/cameras\/new$/);

  await page.getByLabel("Name").fill(CAMERA_NAME);
  await page.getByLabel("Location").fill(CAMERA_LOCATION);
  await page.getByLabel("Stream source").fill(VIDEO_SOURCE);
  // Faster confirmation than the .env default, so the suite sees a state
  // transition without waiting out a 5s filter on a short clip.
  await page.getByLabel("Confirm seconds").fill("2");
  await page.getByLabel("Clear seconds").fill("2");
  await page.getByLabel("Process FPS").fill("3");

  await page.getByRole("button", { name: /create exit/i }).click();

  // Zone-based is useless without a region, so the app routes there itself.
  await expect(page).toHaveURL(/\/cameras\/\d+\/zone$/, { timeout: 30_000 });

  const camera = await findCamera(request);
  expect(camera, "camera should exist in the API after the form submit").not.toBeNull();
  expect(camera.rtsp_url).toBe(VIDEO_SOURCE);
  expect(camera.location).toBe(CAMERA_LOCATION);
  expect(camera.strategy).toBe("zone_based");
  expect(camera.confirm_seconds).toBe(2);
  expect(problems, problems.join("\n")).toEqual([]);
});

test("the zone editor grabs a real frame from the clip", async ({ page, request }) => {
  const camera = await findCamera(request);
  await page.goto(`/cameras/${camera.id}/zone`);

  // Decoding the first frame goes through OpenCV in the worker process; on a
  // cold container that is slow, but it must succeed — a dead source here is
  // the difference between testing the UI and testing the pipeline.
  const caption = page.getByText(/frame is \d+x\d+px/i);
  await expect(caption).toBeVisible({ timeout: 120_000 });
  await expect(page.locator("canvas")).toBeVisible();

  const [, width, height] = (await caption.textContent()).match(/frame is (\d+)x(\d+)px/i);
  expect(Number(width)).toBeGreaterThan(0);
  expect(Number(height)).toBeGreaterThan(0);
});

test("drawing and saving a region stores a normalized polygon", async ({ page, request }) => {
  const camera = await findCamera(request);
  await page.goto(`/cameras/${camera.id}/zone`);
  await expect(page.getByText(/frame is \d+x\d+px/i)).toBeVisible({ timeout: 120_000 });

  const canvas = page.locator("canvas");
  const box = await canvas.boundingBox();

  // A quadrilateral over the middle of the frame. The exact coordinates do not
  // matter to the assertion — that they round-trip as four normalized points
  // does.
  const corners = [
    [0.30, 0.25],
    [0.72, 0.25],
    [0.72, 0.88],
    [0.30, 0.88],
  ];
  for (const [fx, fy] of corners) {
    await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
  }
  await expect(page.getByText("4 points", { exact: true })).toBeVisible();

  // Undo is part of the drawing contract, so exercise it before the save
  // rather than leaving it untested.
  await page.getByRole("button", { name: /^undo$/i }).click();
  await expect(page.getByText("3 points", { exact: true })).toBeVisible();
  await page.mouse.click(box.x + box.width * 0.30, box.y + box.height * 0.88);
  await expect(page.getByText("4 points", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /save region/i }).click();
  await expect(page).toHaveURL(new RegExp(`/cameras/${camera.id}$`), { timeout: 30_000 });

  const updated = await findCamera(request);
  expect(updated.door_polygon).toHaveLength(4);
  for (const [x, y] of updated.door_polygon) {
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x).toBeLessThanOrEqual(1);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(y).toBeLessThanOrEqual(1);
  }
  // The stored polygon must reflect where we clicked, not a default box.
  const xs = updated.door_polygon.map(([x]) => x);
  expect(Math.min(...xs)).toBeLessThan(0.45);
  expect(Math.max(...xs)).toBeGreaterThan(0.55);
});

test("starting the worker produces a live verdict", async ({ page, request }) => {
  const camera = await findCamera(request);
  await page.goto(`/cameras/${camera.id}`);

  // The "draw a region" warning must be gone now that one is stored.
  await expect(page.getByText(/no exit region is defined/i)).toHaveCount(0);

  const start = page.getByRole("button", { name: /start monitoring/i });
  if (await start.isVisible().catch(() => false)) {
    await start.click();
  }

  // The worker decodes, runs YOLO on CPU and publishes a status. The first
  // verdict on a cold torch import is the slowest thing in the suite.
  const status = await waitForApi(
    request,
    `/monitoring/${camera.id}/status`,
    (payload) => payload && payload.worker_state === "running" && payload.state !== "UNKNOWN",
    { timeout: 150_000 }
  );

  expect(["CLEAR", "PARTIAL", "FULL"]).toContain(status.state);
  expect(status.accessibility_pct).toBeGreaterThanOrEqual(0);
  expect(status.accessibility_pct).toBeLessThanOrEqual(100);
  expect(status.strategy).toBe("zone_based");

  // And the console shows the same thing without a manual reload — the detail
  // page polls.
  await expect(page.getByText(/running/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(new RegExp(status.state)).first()).toBeVisible({ timeout: 30_000 });
});

test("the live view renders annotated frames", async ({ page, request }) => {
  const camera = await findCamera(request);

  // Assert on the endpoint the <img> points at: a decoded JPEG of non-trivial
  // size is proof the annotator ran, which "the element is visible" is not.
  const snapshot = await request.get(`${API}/monitoring/${camera.id}/snapshot?annotated=true`);
  expect(snapshot.ok(), `snapshot -> ${snapshot.status()}`).toBeTruthy();
  expect(snapshot.headers()["content-type"]).toMatch(/image\/jpeg/);
  expect((await snapshot.body()).length).toBeGreaterThan(5_000);

  await page.goto(`/cameras/${camera.id}`);
  const image = page.locator("img").first();
  await expect(image).toBeVisible({ timeout: 60_000 });
  await expect
    .poll(() => image.evaluate((node) => node.naturalWidth), { timeout: 60_000 })
    .toBeGreaterThan(0);
});

test("the camera list joins the record with its live status", async ({ page }) => {
  await page.goto("/cameras");

  const row = page.getByRole("row", { name: NAME_RE });
  await expect(row).toBeVisible();
  await expect(row).toContainText("4 points");
  await expect(row).toContainText(/running/i, { timeout: 30_000 });
  // Accessibility renders as a percentage once a verdict exists.
  await expect(row).toContainText(/%/, { timeout: 30_000 });

  // Search filters on name, location and source.
  const search = page.getByPlaceholder(/search name, location, url/i);
  await search.fill("no-such-exit-xyz");
  await expect(page.getByText(/no exit matches that search/i)).toBeVisible();
  await search.fill(CAMERA_LOCATION);
  await expect(page.getByRole("row", { name: NAME_RE })).toBeVisible();
});
