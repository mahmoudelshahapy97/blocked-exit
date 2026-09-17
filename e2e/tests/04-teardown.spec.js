import { expect, test } from "@playwright/test";
import { API, CAMERA_NAME, collectPageProblems, findCamera } from "./helpers.js";

/**
 * The rest of the lifecycle: edit an existing exit, acknowledge an alert, stop
 * the worker, delete the camera. Runs last because it dismantles what specs 02
 * and 03 assert against, and leaves the database as it found it.
 */
test.describe.configure({ mode: "serial" });

const NAME_RE = new RegExp(CAMERA_NAME.split("—")[0].trim(), "i");
const NEW_LOCATION = "Building 2, Loading bay";

test("editing an exit persists the change", async ({ page, request }) => {
  const problems = collectPageProblems(page);
  const camera = await findCamera(request);

  await page.goto(`/cameras/${camera.id}`);
  await page.getByRole("link", { name: /^edit$/i }).click();
  await expect(page).toHaveURL(new RegExp(`/cameras/${camera.id}/edit$`));

  // The form must arrive populated, not blank — an edit form that loses the
  // source would silently unregister the stream on save.
  await expect(page.getByLabel("Stream source")).toHaveValue(camera.rtsp_url);
  await expect(page.getByLabel("Name")).toHaveValue(CAMERA_NAME);

  await page.getByLabel("Location").fill(NEW_LOCATION);
  await page.getByRole("button", { name: /save changes/i }).click();

  await expect(page).toHaveURL(new RegExp(`/cameras/${camera.id}$`), { timeout: 30_000 });
  await expect(page.getByText(NEW_LOCATION)).toBeVisible();

  const updated = await findCamera(request);
  expect(updated.location).toBe(NEW_LOCATION);
  // Editing one field must not clear the others.
  expect(updated.door_polygon).toHaveLength(4);
  expect(updated.rtsp_url).toBe(camera.rtsp_url);

  expect(problems, problems.join("\n")).toEqual([]);
});

test("an alert can be acknowledged from the console", async ({ page, request }) => {
  const camera = await findCamera(request);
  // Must be an unacknowledged one: the row's acknowledge button is disabled
  // once an alert already carries a signature.
  const pending = await (
    await request.get(`${API}/alerts?camera_id=${camera.id}&unacknowledged_only=true&limit=5`)
  ).json();
  test.skip(pending.total === 0, "no unacknowledged alert to acknowledge");
  const alertId = pending.items[0].id;

  await page.goto("/alerts");
  // Match on the id *cell*, not on row text: the event column renders an id
  // too, and a substring match there would grab the wrong row.
  const row = page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: String(alertId), exact: true }) })
    .first();
  await expect(row).toBeVisible({ timeout: 20_000 });

  // Actions is the last cell: view-payload, then acknowledge.
  await row.getByRole("button").last().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Your name").fill("e2e-operator");
  await dialog.getByRole("button", { name: "Acknowledge" }).click();

  await expect
    .poll(
      async () => {
        const after = await (
          await request.get(`${API}/alerts?camera_id=${camera.id}&limit=10`)
        ).json();
        return after.items.some(
          (alert) => alert.id === alertId && alert.acknowledged_by === "e2e-operator"
        );
      },
      { timeout: 20_000 }
    )
    .toBe(true);
});

test("stopping the worker removes it from the live status", async ({ page, request }) => {
  const camera = await findCamera(request);
  await page.goto(`/cameras/${camera.id}`);

  await page.getByRole("button", { name: /^stop$/i }).click();

  await expect
    .poll(
      async () => {
        const statuses = await (await request.get(`${API}/monitoring/status`)).json();
        return statuses.some((status) => status.camera_id === camera.id);
      },
      { timeout: 60_000 }
    )
    .toBe(false);

  // The page reflects it without a reload.
  await expect(page.getByRole("button", { name: /start monitoring/i })).toBeVisible({
    timeout: 30_000,
  });
});

test("deleting the exit removes it from the list and the API", async ({ page, request }) => {
  const problems = collectPageProblems(page);
  const camera = await findCamera(request);

  await page.goto("/cameras");
  const row = page.getByRole("row", { name: NAME_RE });
  await expect(row).toBeVisible();

  // The row menu holds the destructive actions.
  await row.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /delete/i }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /delete/i }).click();

  await expect(page.getByRole("row", { name: NAME_RE })).toHaveCount(0, { timeout: 30_000 });

  expect(await findCamera(request)).toBeNull();
  const gone = await request.get(`${API}/cameras/${camera.id}`);
  expect(gone.status()).toBe(404);

  expect(problems, problems.join("\n")).toEqual([]);
});
