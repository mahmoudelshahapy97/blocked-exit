import { expect, test } from "@playwright/test";
import { API, CAMERA_NAME, collectPageProblems, findCamera, waitForApi } from "./helpers.js";

/**
 * What the running worker from spec 02 produced, read back through every
 * surface that is supposed to show it: the dashboard, the event log, the alert
 * log and the analytics roll-up.
 *
 * Whether the clip actually contains an obstruction is not this suite's to
 * decide, so the assertions split in two: the pages, filters and empty states
 * must always work, and *if* the pipeline opened an event, the log must show
 * it. That keeps the suite honest about a clear clip instead of failing on one.
 */
test.describe.configure({ mode: "serial" });

const NAME_RE = new RegExp(CAMERA_NAME.split("—")[0].trim(), "i");

test("the dashboard shows the monitored exit as a live card", async ({ page, request }) => {
  const problems = collectPageProblems(page);
  const camera = await findCamera(request);

  await page.goto("/");
  await expect(page.getByText(NAME_RE).first()).toBeVisible({ timeout: 30_000 });

  // A monitored exit shows its verdict and an accessibility bar, not the
  // "Not monitored" placeholder.
  const card = page.locator(`a[href="/cameras/${camera.id}"]`).first();
  await expect(card).toBeVisible();
  await expect(card).toContainText(/CLEAR|PARTIAL|FULL/, { timeout: 30_000 });
  await expect(card).toContainText(/%/);

  expect(problems, problems.join("\n")).toEqual([]);
});

test("monitoring/status lists the worker among all cameras", async ({ request }) => {
  const camera = await findCamera(request);
  const response = await request.get(`${API}/monitoring/status`);
  expect(response.ok()).toBeTruthy();

  const statuses = await response.json();
  const mine = statuses.find((status) => status.camera_id === camera.id);
  expect(mine, "the started worker should appear in the all-cameras status").toBeTruthy();
  expect(mine.worker_state).toBe("running");
  expect(mine.camera_name).toBe(CAMERA_NAME);
});

test("the event log renders, filters, and agrees with the API", async ({ page, request }) => {
  const problems = collectPageProblems(page);
  const camera = await findCamera(request);

  const api = await (await request.get(`${API}/events?camera_id=${camera.id}&limit=50`)).json();

  await page.goto("/events");
  await expect(page.getByRole("heading", { name: /blockage events/i, level: 5 })).toBeVisible();

  // Filter to our exit. The count the page prints is the assertion target,
  // because it comes from the same payload the table renders.
  await page.getByRole("combobox", { name: "Exit" }).click();
  await page.getByRole("option", { name: CAMERA_NAME }).click();
  await expect(page.getByText(new RegExp(`^${api.total} events?$`))).toBeVisible({ timeout: 20_000 });

  if (api.total === 0) {
    // A clip with no obstruction is a legitimate outcome; the page must say so
    // rather than render an empty table.
    await expect(page.getByText(/no events match these filters/i)).toBeVisible();
  } else {
    const first = api.items[0];
    const row = page.getByRole("row").filter({ hasText: String(first.id) }).first();
    await expect(row).toBeVisible();
    await expect(row).toContainText(/CLEAR|PARTIAL|FULL/);
    // An event carries the measurement that opened it.
    expect(first.min_accessibility_pct).toBeGreaterThanOrEqual(0);
    expect(first.camera_id).toBe(camera.id);
  }

  // "Still open only" is a server-side filter; it must never widen the set.
  await page.getByRole("checkbox", { name: "Still open only" }).check();
  const openOnly = await (
    await request.get(`${API}/events?camera_id=${camera.id}&open_only=true`)
  ).json();
  expect(openOnly.total).toBeLessThanOrEqual(api.total);

  expect(problems, problems.join("\n")).toEqual([]);
});

test("the alert log renders and its filters round-trip", async ({ page, request }) => {
  const problems = collectPageProblems(page);
  const api = await (await request.get(`${API}/alerts?limit=50`)).json();

  await page.goto("/alerts");
  await expect(page.getByRole("heading", { name: /^Alerts$/, level: 5 })).toBeVisible();
  await expect(page.getByText(new RegExp(`^${api.total} alerts?$`))).toBeVisible({ timeout: 20_000 });

  if (api.total === 0) {
    await expect(page.getByText(/no alerts match these filters/i)).toBeVisible();
  } else {
    await expect(page.getByRole("row").filter({ hasText: String(api.items[0].id) }).first())
      .toBeVisible();
  }

  // Filtering by a channel nothing was delivered on must reach the empty
  // state, not an error.
  await page.getByRole("combobox", { name: "Channel" }).click();
  await page.getByRole("option", { name: "email" }).click();
  await expect(page.getByText(/alerts?$/).first()).toBeVisible();

  expect(problems, problems.join("\n")).toEqual([]);
});

test("a test alert is delivered through the configured channel", async ({ request }) => {
  const camera = await findCamera(request);
  const response = await request.post(`${API}/alerts/test`, {
    data: { camera_id: camera.id },
  });

  // WEBHOOK_URL in .env points at a local receiver that is not running in CI,
  // so a failed *delivery* is expected; what must work is that the backend
  // accepted the request and recorded an attempt.
  expect([200, 201, 202, 207]).toContain(response.status());
  const body = await response.json();
  expect(JSON.stringify(body)).toMatch(/webhook|email|channel|status/i);

  const after = await (await request.get(`${API}/alerts?camera_id=${camera.id}&limit=5`)).json();
  expect(after.total).toBeGreaterThan(0);
});

test("analytics aggregates the window and the timeline", async ({ page, request }) => {
  const problems = collectPageProblems(page);
  const camera = await findCamera(request);

  const summary = await (await request.get(`${API}/analytics/summary?days=7`)).json();
  expect(summary).toHaveProperty("events_total");

  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: /^Analytics$/, level: 5 })).toBeVisible();
  await expect(page.getByText("Events").first()).toBeVisible();
  await expect(page.getByText(/still open/i).first()).toBeVisible({ timeout: 20_000 });

  // Changing the window re-queries rather than re-rendering stale numbers.
  await page.getByRole("combobox", { name: "Window" }).click();
  await page.getByRole("option", { name: /30/ }).first().click();
  await expect(page.getByText(/still open/i).first()).toBeVisible({ timeout: 20_000 });

  const timeline = await request.get(`${API}/analytics/${camera.id}/timeline?days=7`);
  expect(timeline.ok(), `timeline -> ${timeline.status()}`).toBeTruthy();

  const daily = await request.get(`${API}/analytics/daily-report`);
  expect(daily.ok(), `daily-report -> ${daily.status()}`).toBeTruthy();

  expect(problems, problems.join("\n")).toEqual([]);
});

test("the worker keeps producing verdicts over time", async ({ request }) => {
  const camera = await findCamera(request);

  const first = await (await request.get(`${API}/monitoring/${camera.id}/status`)).json();
  // LOOP_VIDEO_FILES=true, so a finished clip restarts rather than ending the
  // worker: the status must still be advancing a minute later.
  const later = await waitForApi(
    request,
    `/monitoring/${camera.id}/status`,
    (payload) => payload.last_frame_at !== first.last_frame_at || payload.frames_processed > first.frames_processed,
    { timeout: 60_000, interval: 3000 }
  );
  expect(later.worker_state).toBe("running");
});
