import { expect, test } from "@playwright/test";

import { api, closeSheet, sheet, signUp, tell, type TimelinePage, unique } from "./helpers";

const titles = async (page: Parameters<typeof api>[0]) => (await api<TimelinePage>(page, "/v1/timeline")).items.map((e) => e.title);

test("one message becomes several entries, shown on Home and in the Timeline", async ({ page }) => {
  await signUp(page);
  await tell(page, "Studied AI for 2 hours and spent 30 on lunch");
  await expect(page.getByText("I understood:")).toBeVisible();
  await expect(page.getByText("AI study — 2h")).toBeVisible();
  await expect(page.getByText("Lunch — 30 MAD")).toBeVisible();
  await closeSheet(page);

  const today = page.locator(".card").filter({ hasText: "Study" }).first();
  await expect(today).toContainText("2h");
  await expect(today).toContainText("30 MAD");

  await page.getByRole("button", { name: "Timeline", exact: true }).click();
  await page.getByPlaceholder("Search your history").fill("lunch");
  await expect(page.getByRole("button", { name: /Lunch/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /AI study/ })).toHaveCount(0);
});

test("an entry is confirmed at once, even while the AI takes its time", async ({ page }) => {
  await signUp(page);
  await tell(page, "Studied chemistry for 1 hour [slow 6]");
  // The AI needs 6 seconds; the confirmation must not wait for it.
  await expect(sheet(page).getByRole("heading", { name: "Saved" })).toBeVisible({ timeout: 3000 });
  await expect(sheet(page).getByRole("status")).toContainText("Saved. Understanding it…", { timeout: 3000 });
  // The result replaces it in the open sheet when it's ready.
  await expect(sheet(page).getByText("chemistry study — 1h")).toBeVisible({ timeout: 20_000 });
});

test("closing the sheet early loses nothing: Home shows it until it's understood", async ({ page }) => {
  await signUp(page);
  await tell(page, "Studied biology for 1 hour [slow 10]");
  await expect(sheet(page).getByRole("status")).toContainText("Saved. Understanding it…", { timeout: 3000 });
  await closeSheet(page);

  const understanding = page.getByRole("heading", { name: "Understanding" });
  await expect(understanding).toBeVisible();
  await expect(page.getByText("“Studied biology for 1 hour [slow 10]”")).toBeVisible();
  await expect(understanding).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText("biology study")).toBeVisible();
});

test("you can keep going while the last entry is still being understood", async ({ page }) => {
  await signUp(page);
  await tell(page, "Studied history for 1 hour [slow 4]");
  await expect(sheet(page).getByRole("status")).toContainText("Saved. Understanding it…", { timeout: 3000 });
  await sheet(page).getByRole("button", { name: "Tell me something else" }).click();
  await page.getByPlaceholder(/I studied AI/).fill("Spent 12 on coffee");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet(page).getByText("Coffee — 12 MAD")).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => titles(page), { timeout: 20_000 }).toEqual(expect.arrayContaining(["history study", "Coffee"]));
});

test("an entry the AI couldn't process at first is retried by the server by itself", async ({ page }) => {
  await signUp(page);
  await tell(page, `Studied physics for 1 hour [fail once] ${unique("run")}`);
  await expect(sheet(page).getByText("physics study — 1h")).toBeVisible({ timeout: 30_000 });
  expect(await titles(page)).toEqual(["physics study"]);
  // It failed the first time and the server tried again without anyone asking.
  const [capture] = await api<{ attempts: number; status: string }[]>(page, "/v1/captures");
  expect([capture.status, capture.attempts]).toEqual(["PROCESSED", 2]);
});

test("while the AI keeps failing, the entry is shown as saved and waiting for a retry", async ({ page }) => {
  await signUp(page);
  await tell(page, `Studied geology for 1 hour [fail] ${unique("run")}`);
  await expect(sheet(page).getByRole("status")).toContainText("I'll try again shortly", { timeout: 20_000 });
  await closeSheet(page);
  // On Home it waits under Understanding, not under "Not processed yet": nothing to do yet.
  await expect(page.getByRole("heading", { name: "Understanding" })).toBeVisible();
  await expect(page.getByText(/Couldn't understand it yet; I'll try again shortly/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Not processed yet" })).toHaveCount(0);
});

test("a question typed in the capture box is answered from the records", async ({ page }) => {
  await signUp(page);
  await tell(page, "Studied AI for 2 hours");
  await expect(page.getByText("AI study — 2h")).toBeVisible();
  await page.getByRole("button", { name: "Tell me something else" }).click();
  await page.getByPlaceholder(/I studied AI/).fill("How much did I study this week?");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("You studied 2h this week.")).toBeVisible();
});

test("an entry written while the server is unreachable is kept and sent later", async ({ page }) => {
  await signUp(page);
  await page.route("**/v1/captures*", (route) => (route.request().method() === "POST" ? route.abort() : route.fallback()));
  await tell(page, "Studied math for 1 hour");
  await expect(page.getByText("Saved for later")).toBeVisible();
  await closeSheet(page);
  await expect(page.getByText("1 entry is waiting on this phone to be sent.")).toBeVisible();

  await page.unroute("**/v1/captures*");
  await page.reload();
  await expect(page.getByText("Synced 1 saved entry.")).toBeVisible();
  await expect.poll(() => titles(page)).toEqual(["math study"]);
});

test("Send now delivers what's waiting on the phone, and Home shows it understood", async ({ page }) => {
  await signUp(page);
  await page.route("**/v1/captures*", (route) => (route.request().method() === "POST" ? route.abort() : route.fallback()));
  await tell(page, "Studied economics for 1 hour [slow 10]");
  await expect(page.getByText("Saved for later")).toBeVisible();
  await closeSheet(page);

  await page.unroute("**/v1/captures*");
  await page.getByRole("button", { name: "Send now" }).click();
  await expect(page.getByText("Sent 1 entry.")).toBeVisible();
  await expect(page.getByText("waiting on this phone")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Understanding" })).toBeVisible();
  await expect(page.getByText("economics study")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Understanding" })).toHaveCount(0);
});

test("a draft survives closing the sheet by accident", async ({ page }) => {
  await signUp(page);
  await page.getByRole("button", { name: "Tell me what happened…" }).click();
  await page.getByPlaceholder(/I studied AI/).fill("A long thought I don't want to lose");
  await page.locator(".backdrop").click({ position: { x: 10, y: 10 } });
  await page.getByRole("button", { name: "Tell me what happened…" }).click();
  await expect(page.getByPlaceholder(/I studied AI/)).toHaveValue("A long thought I don't want to lose");
});
