import { expect, type Page, test } from "@playwright/test";

import { api, expectAccessible, signUp } from "./helpers";

type Review = { week: { start: string } };

const shift = (iso: string, days: number) => {
  const day = new Date(`${iso}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
};

/** Two hours of study on the first day of each of the last four weeks, four hours this week. */
async function seedWeeks(page: Page): Promise<string> {
  const { week } = await api<Review>(page, "/v1/review/weekly");
  // The first day of each week is always within the compared days, whatever today is.
  for (const [weeksBack, minutes] of [[0, 240], [1, 120], [2, 120], [3, 120], [4, 120]]) {
    await api(page, "/v1/events", {
      method: "POST",
      data: { event_type: "STUDY", title: "AI study", occurred_on: shift(week.start, -7 * weeksBack), duration_minutes: minutes },
    });
  }
  await api(page, "/v1/events", {
    method: "POST",
    data: { event_type: "EXPENSE", title: "Lunch", occurred_on: week.start, amount: 40, currency: "MAD", category: "food" },
  });
  return week.start;
}

const studyRow = (page: Page) => page.locator(".week-review .row").filter({ hasText: "Study" });

test("the week is compared with last week and the usual week, with what stands out", async ({ page }) => {
  await signUp(page);
  await seedWeeks(page);
  await page.getByRole("button", { name: "Insights", exact: true }).click();

  await expect(page.getByRole("heading", { name: /^This week · / })).toBeVisible();
  await expect(page.getByText(/Study is up 100% on your 4-week average.*: 4h against 2h\./)).toBeVisible();
  await expect(studyRow(page)).toContainText("4h");
  await expect(studyRow(page)).toContainText("+2h");
  await expect(studyRow(page)).toContainText(/Last week.*: 2h · 4-week avg: 2h/);
  await expect(studyRow(page).locator(".sr-only")).toHaveText("2h more than last week");
  await expect(page.locator(".week-review .row").filter({ hasText: "Spending" })).toContainText("40 MAD");
  await expect(page.getByText("Every number comes from your records.", { exact: false })).toBeVisible();
});

test("you can step back through earlier weeks and return", async ({ page }) => {
  await signUp(page);
  await seedWeeks(page);
  await page.getByRole("button", { name: "Insights", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next week" })).toBeDisabled();

  await page.getByRole("button", { name: "Previous week" }).click();
  await expect(page.getByRole("heading", { name: /^Last week · / })).toBeVisible();
  await expect(studyRow(page)).toContainText("2h");
  await page.getByRole("button", { name: "Previous week" }).click();
  await expect(page.getByRole("heading", { name: /^Week of / })).toBeVisible();

  await page.getByRole("button", { name: "Next week" }).click();
  await page.getByRole("button", { name: "Next week" }).click();
  await expect(page.getByRole("heading", { name: /^This week · / })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next week" })).toBeDisabled();
});

test("a new account sees its numbers without invented comparisons", async ({ page }) => {
  await signUp(page);
  await page.getByRole("button", { name: "Insights", exact: true }).click();
  await expect(page.getByRole("heading", { name: /^This week · / })).toBeVisible();
  await expect(page.getByText("Averages start once you have a week of history.", { exact: false })).toBeVisible();
  await expect(page.getByText("What stands out")).toHaveCount(0);
  await expect(studyRow(page)).toContainText("0m");
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme });

    test("the weekly review meets WCAG 2 AA and fits the screen", async ({ page }) => {
      await signUp(page);
      await seedWeeks(page);
      await page.getByRole("button", { name: "Insights", exact: true }).click();
      await expect(page.getByText("What stands out")).toBeVisible();
      await expectAccessible(page);
      const width = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, screen: innerWidth }));
      expect(width.page, "wider than the screen").toBeLessThanOrEqual(width.screen);
    });
  });
}
