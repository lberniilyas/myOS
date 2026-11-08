import { expect, test } from "@playwright/test";

import { api, closeSheet, sheet, signUp, tell, type TimelinePage, unique } from "./helpers";

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
  const timeline = await api<TimelinePage>(page, "/v1/timeline");
  expect(timeline.items.map((e) => e.title)).toEqual(["math study"]);
});

test("an entry the AI couldn't process is kept, and sending it again works", async ({ page }) => {
  await signUp(page);
  const text = `Studied physics for 1 hour [fail once] ${unique("run")}`;
  await tell(page, text);
  await expect(sheet(page).getByRole("heading", { name: "Not processed yet" })).toBeVisible();
  await closeSheet(page);

  await page.getByRole("button", { name: "Send now" }).click();
  await expect(page.getByText("Sent 1 entry.")).toBeVisible();
  const timeline = await api<TimelinePage>(page, "/v1/timeline");
  expect(timeline.items.map((e) => [e.title, e.duration_display])).toEqual([["physics study", "1h"]]);
});

test("a draft survives closing the sheet by accident", async ({ page }) => {
  await signUp(page);
  await page.getByRole("button", { name: "Tell me what happened…" }).click();
  await page.getByPlaceholder(/I studied AI/).fill("A long thought I don't want to lose");
  await page.locator(".backdrop").click({ position: { x: 10, y: 10 } });
  await page.getByRole("button", { name: "Tell me what happened…" }).click();
  await expect(page.getByPlaceholder(/I studied AI/)).toHaveValue("A long thought I don't want to lose");
});
