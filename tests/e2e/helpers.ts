import { expect, type Page } from "@playwright/test";

export type Persona = "consumer_a" | "consumer_b" | "staff" | "brand";

/** Open the app and authenticate as one of the fixed demo personas. */
export async function openApp(page: Page, persona: Persona = "consumer_a"): Promise<void> {
  await page.goto("/");
  const button = page.getByTestId(`persona-${persona}`);
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.getByTestId("app-ready")).toBeVisible();
}

/** Switch the server-side demo identity and wait until the app has reloaded state. */
export async function switchPersona(page: Page, persona: Persona): Promise<void> {
  const button = page.getByTestId(`persona-${persona}`);
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.getByTestId("app-ready")).toBeVisible();
}

export async function goTo(page: Page, navTestId: string): Promise<void> {
  await page.getByTestId(navTestId).click();
}

/** Read the bearer token the SPA stores, without hard-coding the storage key. */
export async function sessionToken(page: Page): Promise<string> {
  const token = await page.evaluate(() => {
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (!key) continue;
      const value = window.localStorage.getItem(key);
      if (value && value.startsWith("bc_")) return value;
      if (value && /token/i.test(key) && value.length > 10) return value.replace(/^"|"$/g, "");
    }
    return null;
  });
  expect(token, "the app must keep the demo session token in localStorage").toBeTruthy();
  return token as string;
}

/** Trigger one scheduler tick through the API (a backend action, not a UI action). */
export async function tickScheduler(page: Page): Promise<{ summary: any }> {
  const token = await sessionToken(page);
  const response = await page.request.post("/api/v1/admin/scheduler/tick", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

export async function apiGet(page: Page, path: string): Promise<any> {
  const token = await sessionToken(page);
  const response = await page.request.get(path, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

export function isoIn(hours: number): string {
  return new Date(Date.now() + hours * 3600 * 1000).toISOString();
}

/** Value for an <input type="datetime-local"> (local time, no seconds, no zone). */
export function localDateTimeInput(hours: number): string {
  const target = new Date(Date.now() + hours * 3600 * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(target.getDate())}T${pad(
    target.getHours(),
  )}:${pad(target.getMinutes())}`;
}
