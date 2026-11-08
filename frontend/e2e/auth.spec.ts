import { expect, test } from "@playwright/test";

import { api, signUp, tellButton } from "./helpers";

test("signing up lands on Home, and reopening the app keeps you signed in", async ({ page }) => {
  await signUp(page, "Ilyas");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Ilyas");
  await page.reload();
  await expect(tellButton(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);
});

test("an expired session renews quietly, and a failed renewal never signs you out", async ({ page }) => {
  await signUp(page);
  await page.evaluate(() => {
    const tokens = JSON.parse(localStorage.getItem("pos.tokens")!);
    localStorage.setItem("pos.tokens", JSON.stringify({ ...tokens, access_token: "expired" }));
  });

  // No network for the renewal: still signed in, with an honest message.
  await page.route("**/v1/auth/refresh", (route) => route.abort());
  await page.reload();
  await expect(tellButton(page)).toBeVisible();
  await expect(page.getByText("Can't reach your system right now.")).toBeVisible();

  // A busy server during renewal: still signed in.
  await page.unroute("**/v1/auth/refresh");
  await page.route("**/v1/auth/refresh", (route) => route.fulfill({ status: 503, body: "busy" }));
  await page.reload();
  await expect(tellButton(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);

  // Once reachable, the session renews by itself and everything loads.
  await page.unroute("**/v1/auth/refresh");
  await page.reload();
  await expect(page.getByText("Nothing recorded yet today.")).toBeVisible();
  const me = await api<{ email: string }>(page, "/v1/me");
  expect(me.email).toContain("@example.com");
});

test("signing out returns to the sign-in screen and stays signed out", async ({ page }) => {
  await signUp(page);
  await page.getByRole("button", { name: "Me", exact: true }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});
