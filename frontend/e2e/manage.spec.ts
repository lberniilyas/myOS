import { expect, test } from "@playwright/test";

import { api, closeSheet, sheet, signUp, tell } from "./helpers";

test("a spoken intention becomes a task you can tick off", async ({ page }) => {
  await signUp(page);
  await tell(page, "I need to call the bank tomorrow");
  await expect(page.getByText(/Task: Call the bank \(due /)).toBeVisible();
  await closeSheet(page);

  await page.getByRole("button", { name: /Tasks · 1 open/ }).click();
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  await expect(page.getByText("Tomorrow")).toBeVisible();
  await page.getByRole("button", { name: "Mark Call the bank done" }).click();
  await expect(page.getByRole("heading", { name: "Done recently" })).toBeVisible();
  const open = await api<unknown[]>(page, "/v1/tasks?open_only=true");
  expect(open).toHaveLength(0);
});

test("a project's page: nicknames, time invested, and work recognised by nickname", async ({ page }) => {
  await signUp(page);
  await page.getByRole("button", { name: "Me", exact: true }).click();
  await page.getByPlaceholder("New project").fill("TenderPilot");
  await page.locator("form", { has: page.getByPlaceholder("New project") }).getByRole("button", { name: "Add" }).click();
  await page.getByRole("button", { name: /TenderPilot/ }).click();
  await expect(page.getByRole("heading", { name: "TenderPilot" })).toBeVisible();

  await page.getByLabel("New nickname").fill("tender app");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("button", { name: "Remove nickname tender app" })).toBeVisible();

  await page.getByRole("button", { name: "Home", exact: true }).click();
  await tell(page, "Worked on tender app for 90 minutes");
  await expect(page.getByText("tender app work — 1h 30m")).toBeVisible();
  await closeSheet(page);
  // The nickname resolved to the project: the entry is linked to TenderPilot.
  const timeline = await api<{ items: { projects: { name: string }[] }[] }>(page, "/v1/timeline");
  expect(timeline.items[0].projects.map((p) => p.name)).toEqual(["TenderPilot"]);

  await page.getByRole("button", { name: "Me", exact: true }).click();
  await page.getByRole("button", { name: /TenderPilot/ }).click();
  const week = page.locator(".kv").filter({ hasText: "Last 7 days" });
  await expect(week).toContainText("1h 30m");
});

test("a habit's target and its progress this week", async ({ page }) => {
  await signUp(page);
  const habit = await api<{ id: string }>(page, "/v1/habits", { method: "POST", data: { name: "Exercise", target_count: 3 } });
  await tell(page, "Went for a run this morning");
  await expect(sheet(page).getByText("Workout")).toBeVisible();
  await closeSheet(page);
  await page.goto(`/#/habit/${habit.id}`);
  await expect(page.getByText("1 of 3 this week")).toBeVisible();
});
