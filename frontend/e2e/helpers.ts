import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct horse battery";

export function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const tellButton = (page: Page) => page.getByRole("button", { name: "Tell me what happened…" });

/** The capture sheet (the Home screen behind it can show the same text). */
export const sheet = (page: Page) => page.getByRole("dialog");

/** Create a fresh account through the sign-up screen; every test gets its own. */
export async function signUp(page: Page, name = "Ilyas"): Promise<string> {
  const email = `${unique("e2e")}@example.com`;
  await page.goto("/");
  await page.getByRole("button", { name: "New here? Create an account" }).click();
  await page.getByPlaceholder("Your name").fill(name);
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder(/Password/).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(tellButton(page)).toBeVisible();
  return email;
}

export async function accessToken(page: Page): Promise<string> {
  return page.evaluate(() => JSON.parse(localStorage.getItem("pos.tokens") ?? "{}").access_token);
}

/** Call the API as the signed-in person, for seeding data and checking what was saved. */
export async function api<T>(page: Page, path: string, init: { method?: string; data?: unknown } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const response = await page.request.fetch(path, {
    method,
    data: init.data,
    headers: { Authorization: `Bearer ${await accessToken(page)}` },
  });
  expect(response.ok(), `${method} ${path} -> ${response.status()} ${await response.text()}`).toBeTruthy();
  return (response.status() === 204 ? undefined : await response.json()) as T;
}

/** Open the capture sheet, type a message and save it. */
export async function tell(page: Page, text: string): Promise<void> {
  await tellButton(page).click();
  await page.getByPlaceholder(/I studied AI/).fill(text);
  await page.getByRole("button", { name: "Save", exact: true }).click();
}

export async function closeSheet(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

/** WCAG 2 A and AA checks with axe; every violation fails the test. */
export async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations.map((v) => `${v.impact} ${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}

export type TimelinePage = { items: { id: string; title: string; event_type: string; duration_display: string | null }[] };
