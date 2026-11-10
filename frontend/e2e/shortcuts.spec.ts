import { expect, type Page, test } from "@playwright/test";

import { api, expectAccessible, signUp, type TimelinePage } from "./helpers";

async function openShortcuts(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Me", exact: true }).click();
  await page.getByRole("button", { name: /Siri & Shortcuts/ }).click();
  await expect(page.getByRole("heading", { name: "Siri & Shortcuts", level: 1 })).toBeVisible();
}

async function createKey(page: Page, name: string): Promise<{ header: string; url: string }> {
  await page.getByLabel("Name of the new key").fill(name);
  await page.getByRole("button", { name: "Create key" }).click();
  const header = await page.getByLabel("Authorization header value").inputValue();
  const url = await page.getByLabel("URL", { exact: true }).inputValue();
  return { header, url };
}

/** What the Shortcut in the setup steps sends: Get Contents of URL, POST, JSON body. */
function shortcut(page: Page, url: string, header: string, content: string) {
  return page.request.post(url, { headers: { Authorization: header }, data: { content, input_type: "VOICE" } });
}

test("a key made in the app lets a Shortcut send entries, until it's revoked", async ({ page, baseURL }) => {
  await signUp(page);
  await openShortcuts(page);
  await expect(page.getByText("No keys yet.")).toBeVisible();

  const { header, url } = await createKey(page, "My iPhone");
  expect(header).toMatch(/^Bearer pos_key_[\w-]{40,}$/);
  expect(url).toBe(`${baseURL}/v1/captures?background=true`);

  const sent = await shortcut(page, url, header, "Studied AI for 2 hours");
  expect(sent.status()).toBe(202);
  expect((await sent.json()).message).toBe("Saved. Understanding it…"); // what Siri says
  await expect.poll(async () => (await api<TimelinePage>(page, "/v1/timeline")).items.map((e) => e.title)).toEqual(["AI study"]);

  // The key sends entries and nothing else.
  const reading = await page.request.get("/v1/timeline", { headers: { Authorization: header } });
  expect(reading.status()).toBe(403);

  await page.getByRole("button", { name: "I've copied it" }).click();
  await expect(page.getByLabel("Authorization header value")).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("My iPhone")).toBeVisible();
  await expect(page.getByText(/last used/)).toBeVisible();

  await page.getByRole("button", { name: "Revoke My iPhone" }).click();
  await page.getByRole("button", { name: "Revoke", exact: true }).click();
  await expect(page.getByText("Key revoked.")).toBeVisible();
  await expect(page.getByText("No keys yet.")).toBeVisible();
  const refused = await shortcut(page, url, header, "Studied AI again");
  expect(refused.status()).toBe(401);
  expect((await refused.json()).error.code).toBe("INVALID_KEY");
});

test("the key is shown only once", async ({ page }) => {
  await signUp(page);
  await openShortcuts(page);
  const { header } = await createKey(page, "Siri");
  await page.reload();
  await expect(page.getByRole("button", { name: "Revoke Siri" })).toBeVisible();
  await expect(page.getByLabel("Authorization header value")).toHaveCount(0);
  await expect(page.getByText(header.slice(-4))).toBeVisible(); // only its last characters, to tell keys apart
  await expect(page.getByText(header.replace("Bearer ", ""))).toHaveCount(0);
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme });

    test("Siri & Shortcuts with a new key meets WCAG 2 AA and fits the screen", async ({ page }) => {
      await signUp(page);
      await openShortcuts(page);
      await createKey(page, "iPhone Shortcut");
      await expectAccessible(page);
      const width = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, screen: innerWidth }));
      expect(width.page, "wider than the screen").toBeLessThanOrEqual(width.screen);
    });
  });
}
