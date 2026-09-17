import { expect, test } from "@playwright/test";
import { API, collectPageProblems, deleteCameraIfPresent } from "./helpers.js";

/**
 * The shell: every route renders, the nav reaches all of them, and the backend
 * the console proxies to is actually alive. Nothing here depends on a camera
 * existing, so it doubles as the environment check that tells a failing suite
 * apart from a broken stack.
 */
test.describe.configure({ mode: "serial" });

test("the backend is live and ready behind the console origin", async ({ request }) => {
  const live = await request.get(`${API}/health`);
  expect(live.ok(), `GET ${API}/health -> ${live.status()}`).toBeTruthy();

  const ready = await request.get(`${API}/health/ready`);
  expect(ready.ok(), `GET ${API}/health/ready -> ${ready.status()}`).toBeTruthy();
  // Readiness covers the database; a console that loads but cannot list
  // cameras is the failure this catches before anything else runs.
  expect(JSON.stringify(await ready.json())).toMatch(/ok|ready|healthy|true/i);
});

test("a camera left behind by an earlier run is removed", async ({ request }) => {
  // Housekeeping, not an assertion about the app: the camera name is unique in
  // the database, so a half-finished previous run would fail spec 02 on create.
  const removed = await deleteCameraIfPresent(request);
  expect(typeof removed).toBe("boolean");
});

test("the dashboard loads with its shell intact", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Live exits", level: 5 })).toBeVisible({
    timeout: 30_000,
  });
  for (const label of ["Dashboard", "Exits", "Events", "Alerts", "Analytics"]) {
    await expect(page.getByRole("link", { name: label, exact: true })).toBeVisible();
  }
  expect(problems, problems.join("\n")).toEqual([]);
});

const ROUTES = [
  { label: "Exits", path: "/cameras", heading: "Exits" },
  { label: "Events", path: "/events", heading: "Blockage events" },
  { label: "Alerts", path: "/alerts", heading: "Alerts" },
  { label: "Analytics", path: "/analytics", heading: "Analytics" },
];

for (const route of ROUTES) {
  test(`the nav reaches ${route.label} and it renders`, async ({ page }) => {
    const problems = collectPageProblems(page);
    await page.goto("/");
    await page.getByRole("link", { name: route.label, exact: true }).click();

    await expect(page).toHaveURL(new RegExp(`${route.path}$`));
    await expect(page.getByRole("heading", { name: route.heading, exact: true, level: 5 })).toBeVisible();
    expect(problems, problems.join("\n")).toEqual([]);
  });
}

test("an unknown route renders the 404 page rather than a blank shell", async ({ page }) => {
  await page.goto("/this-route-does-not-exist");
  await expect(page.getByText(/not found|404/i).first()).toBeVisible();
});

test("the legacy /zones deep link still lands on the camera list", async ({ page }) => {
  await page.goto("/zones?camera_id=1");
  await expect(page).toHaveURL(/\/cameras$/);
  await expect(page.getByRole("heading", { name: "Exits", exact: true, level: 5 })).toBeVisible();
});

test("the dark/light toggle repaints the page", async ({ page }) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /switch to (light|dark)/i });
  await expect(toggle).toBeVisible();

  const before = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await toggle.click();
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor))
    .not.toBe(before);
});
