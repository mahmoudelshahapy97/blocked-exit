import { E2E_USER, expect, loginPair, signInPage, test } from "./helpers.js";

/**
 * Tenancy, the platform's way: a superadmin creates workspaces and accounts,
 * every user works in one active workspace stored on the server, and what a
 * page offers depends on the role held there. Independent of specs 01-04.
 */

test.describe.configure({ mode: "serial" });

const RUN = Date.now().toString(36);
const WORKSPACE = `E2E tenancy ${RUN}`;
const VIEWER = `e2e.viewer.${RUN}`;
const VIEWER_PASSWORD = "Viewer-Pass-123";

test("a superadmin creates a workspace from the console", async ({ page }) => {
  await page.goto("/admin/workspaces");
  await page.getByRole("button", { name: "Add workspace" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(WORKSPACE);
  await dialog.getByRole("button", { name: "Create" }).click();

  await expect(page.getByRole("heading", { name: WORKSPACE })).toBeVisible();
  await expect(page.getByRole("cell", { name: E2E_USER, exact: true })).toBeVisible(); // creator joins as admin
});

test("a superadmin creates a viewer straight into it", async ({ page }) => {
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Create user" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Username").fill(VIEWER);
  await dialog.getByLabel("Email").fill(`${VIEWER}@example.com`);
  await dialog.getByLabel("Password").fill(VIEWER_PASSWORD);
  await dialog.getByLabel("Workspace", { exact: true }).click();
  await page.getByRole("option", { name: WORKSPACE, exact: true }).click();
  await dialog.getByLabel("Workspace role").click();
  await page.getByRole("option", { name: "viewer" }).click();
  await dialog.getByRole("button", { name: "Create" }).click();

  await expect(page.getByRole("cell", { name: VIEWER, exact: true })).toBeVisible();
});

test("signup is closed and the login page says who to ask", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/login");
  await expect(page.getByText(/contact your administrator/i)).toBeVisible();
  await page.goto("/signup");
  await expect(page).toHaveURL(/\/login$/);
  await context.close();
});

test("a viewer lands in that workspace with a read-only console", async ({ browser, baseURL }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInPage(page, await loginPair(baseURL, VIEWER, VIEWER_PASSWORD));

  await page.goto("/settings/workspace");
  await expect(page.getByRole("heading", { name: WORKSPACE })).toBeVisible();
  await expect(page.getByText("viewer").first()).toBeVisible();

  await page.goto("/cameras");
  await expect(page.getByRole("heading", { name: "Exits", level: 5 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add exit" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Add exit" })).toHaveCount(0);

  await page.goto("/admin/users");
  // Not a superadmin: the page explains instead of rendering the user list.
  await expect(page.getByText(/does not have permission/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Create user" })).toHaveCount(0);
  await context.close();
});

test("switching workspace re-scopes every page", async ({ page }) => {
  await page.goto("/cameras");
  const switcher = page.getByRole("combobox", { name: /^Workspace:/ });
  const original = (await switcher.textContent()).trim();
  // An option reads "<name>" over "<n> cameras"; match the name line exactly.
  const option = (name) =>
    page.getByRole("option").filter({ has: page.getByText(name, { exact: true }) });

  await switcher.click();
  await option(WORKSPACE).click();
  await expect(switcher).toHaveText(WORKSPACE);
  await expect(page.getByText(/no exits registered yet/i)).toBeVisible();

  await switcher.click();
  await option(original).click();
  await expect(switcher).toHaveText(original);
});

test("the workspace is deactivated, then deleted", async ({ page }) => {
  await page.goto("/admin/workspaces");
  await page.getByRole("cell", { name: new RegExp(WORKSPACE) }).click();
  await page.getByRole("button", { name: "Deactivate" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Deactivate" }).click();
  await expect(page.getByText(/^Deactivated:/)).toBeVisible();

  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/workspaces$/);
  await expect(page.getByRole("cell", { name: new RegExp(WORKSPACE) })).toHaveCount(0);
});
