import { expect, type Page, test } from "@playwright/test";

import { api, expectAccessible, signUp, tell } from "./helpers";

/** An account with a little of everything, so every screen shows real content. */
async function seed(page: Page): Promise<{ project: string }> {
  await signUp(page);
  const project = await api<{ id: string }>(page, "/v1/projects", { method: "POST", data: { name: "TenderPilot" } });
  await api(page, "/v1/captures", {
    method: "POST",
    data: { content: "Studied AI for 2 hours and spent 30 on lunch. I need to call the bank tomorrow" },
  });
  return { project: project.id };
}

const SCREENS: [string, (ids: { project: string }) => string, string][] = [
  ["Home", () => "#/home", "Today"],
  ["Timeline", () => "#/timeline", "Timeline"],
  ["Insights", () => "#/insights", "Insights"],
  ["Me", () => "#/me", "Me"],
  ["Tasks", () => "#/tasks", "Tasks"],
  ["Recently deleted", () => "#/deleted", "Recently deleted"],
  ["Project", (ids) => `#/project/${ids.project}`, "TenderPilot"],
];

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme });

    for (const [name, path, heading] of SCREENS) {
      test(`${name} meets WCAG 2 AA and fits the screen`, async ({ page }) => {
        const ids = await seed(page);
        await page.goto(`/${path(ids)}`);
        await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
        await expectAccessible(page);
        const width = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, screen: innerWidth }));
        expect(width.page, "wider than the screen").toBeLessThanOrEqual(width.screen);
      });
    }

    test("the capture sheet and its reply meet WCAG 2 AA", async ({ page }) => {
      await signUp(page);
      await tell(page, "Studied AI for 2 hours and spent 30 on lunch");
      await expect(page.getByText("I understood:")).toBeVisible();
      await expectAccessible(page);
    });
  });
}
