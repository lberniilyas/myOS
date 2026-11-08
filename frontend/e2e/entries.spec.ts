import { expect, test } from "@playwright/test";

import { api, closeSheet, sheet, signUp, tell, type TimelinePage } from "./helpers";

test("editing an entry, deleting it with a confirmation, and restoring it", async ({ page }) => {
  await signUp(page);
  await tell(page, "Studied AI for 2 hours");
  await expect(page.getByText("AI study — 2h")).toBeVisible();
  await closeSheet(page);

  await page.getByRole("button", { name: /AI study/ }).click();
  await page.getByRole("button", { name: "Edit details" }).click();
  await page.getByPlaceholder("Title").fill("Deep learning study");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { name: "Deep learning study" })).toBeVisible();

  await page.getByRole("button", { name: "Delete entry" }).click();
  await expect(page.getByText("Delete this entry?")).toBeVisible();
  let timeline = await api<TimelinePage>(page, "/v1/timeline");
  expect(timeline.items).toHaveLength(1); // nothing deleted before the second tap

  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText("Deleted. Restore it from Me → Recently deleted.")).toBeVisible();
  timeline = await api<TimelinePage>(page, "/v1/timeline");
  expect(timeline.items).toHaveLength(0);

  await page.getByRole("button", { name: "Me", exact: true }).click();
  await page.getByRole("button", { name: /Recently deleted/ }).click();
  await expect(page.getByText("Deep learning study")).toBeVisible();
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByText("Nothing deleted.")).toBeVisible();
  timeline = await api<TimelinePage>(page, "/v1/timeline");
  expect(timeline.items.map((e) => e.title)).toEqual(["Deep learning study"]);
});

test("a question about a vague entry is answered with one tap", async ({ page }) => {
  await signUp(page);
  await tell(page, "Spent 45 on something");
  await expect(page.getByText("What was the 45 MAD for?")).toBeVisible();
  await sheet(page).getByRole("button", { name: "Shopping" }).click();
  await expect(sheet(page).getByText("What was the 45 MAD for?")).toHaveCount(0);
  await closeSheet(page);
  const timeline = await api<{ items: { category: string | null }[] }>(page, "/v1/timeline");
  expect(timeline.items[0].category).toBe("shopping");
});
