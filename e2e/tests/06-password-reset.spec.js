import { API, expect, test } from "./helpers.js";

/**
 * "Forgot your password?" end to end: the login link, the emailed code, the
 * new password, and the old session ending. The code is read back from a
 * Mailpit inbox, so this needs the API's SMTP_HOST pointed at Mailpit and
 * MAILPIT_URL set to its web/API address; without them the file is skipped.
 */

const MAILPIT_URL = process.env.MAILPIT_URL;

test.describe.configure({ mode: "serial" });

const RUN = Date.now().toString(36);
const USERNAME = `e2e.reset.${RUN}`;
const EMAIL = `${USERNAME}@example.com`;
const OLD_PASSWORD = "Old-Password-123";
const NEW_PASSWORD = "New-Password-456";

/** The newest code mailed to `email`, waiting for the background send. */
async function codeMailedTo(email, { after = 0, timeout = 20_000 } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const search = await fetch(
      `${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:"${email}"`)}`
    ).then((r) => r.json());
    const newest = (search.messages || []).find((m) => Date.parse(m.Created) > after);
    if (newest) {
      const message = await fetch(`${MAILPIT_URL}/api/v1/message/${newest.ID}`).then((r) =>
        r.json()
      );
      const match = /code is (\d{6})/.exec(message.Text);
      if (match) return match[1];
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`No reset code reached ${email} within ${timeout}ms`);
}

test.beforeAll(async ({ request }) => {
  const bootstrap = await (await request.get(`${API}/auth/bootstrap`)).json();
  test.skip(
    !MAILPIT_URL || !bootstrap.password_reset,
    "needs SMTP_HOST on the API and MAILPIT_URL for the inbox"
  );
  const response = await request.post(`${API}/auth/users`, {
    data: { username: USERNAME, email: EMAIL, password: OLD_PASSWORD },
  });
  expect(response.status(), await response.text()).toBe(201);
});

test("a user resets a forgotten password with the emailed code", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto("/login");
  await page.getByLabel("Username or email").fill(EMAIL);
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page).toHaveURL(/\/forgot-password$/);
  // The email typed as the login carries over.
  await expect(page.getByLabel("Email")).toHaveValue(EMAIL);

  const asked = Date.now() - 1000;
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByText(/a reset code is on its way/i)).toBeVisible();
  const code = await codeMailedTo(EMAIL, { after: asked });

  await page.getByLabel("Code from the email").fill("000000" === code ? "111111" : "000000");
  await page.getByLabel(/^New password/).fill(NEW_PASSWORD);
  await page.getByLabel("Repeat new password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(page.getByText(/wrong or has expired/i)).toBeVisible();

  await page.getByLabel("Code from the email").fill(code);
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText(/password changed/i)).toBeVisible();

  await page.getByLabel("Username or email").fill(USERNAME);
  await page.getByLabel("Password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await context.close();
});

test("the old password no longer works", async ({
  playwright,
  baseURL,
}) => {
  const api = await playwright.request.newContext({ baseURL });
  const login = await api.post(`${API}/auth/login`, {
    data: { username: USERNAME, password: OLD_PASSWORD },
  });
  expect(login.status()).toBe(401);
  await api.dispose();
});

test("an unknown email gets the same answer and no mail", async ({ playwright, baseURL }) => {
  const api = await playwright.request.newContext({ baseURL });
  const known = await (
    await api.post(`${API}/auth/forgot-password`, { data: { email: EMAIL } })
  ).json();
  const unknown = await (
    await api.post(`${API}/auth/forgot-password`, {
      data: { email: `nobody.${RUN}@example.com` },
    })
  ).json();
  expect(unknown).toEqual(known);
  await api.dispose();

  const search = await fetch(
    `${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:"nobody.${RUN}@example.com"`)}`
  ).then((r) => r.json());
  expect(search.messages_count ?? search.messages.length).toBe(0);
});
