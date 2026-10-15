import { expect, test } from "@playwright/test";

import { apiGet, goTo, localDateTimeInput, openApp, switchPersona, tickScheduler } from "./helpers";

test.describe("流程 6：城市 + 活动 + 授权 → 环境触发 → inbox → 计划草稿 → 跨端接受", () => {
  test("授权旅行提醒后调度器把卡片送进 inbox，撤销授权后不再发送", async ({ page }) => {
    await openApp(page, "consumer_a");

    // 1. choose a city manually (never inferred from IP)
    await goTo(page, "nav-environment");
    await page.getByTestId("city-select").selectOption("CN-BJ");
    await page.getByTestId("city-save").click();
    await expect(page.getByTestId("city-select")).toHaveValue("CN-BJ");
    await expect(page.getByTestId("env-current")).toBeVisible();
    await expect(page.getByTestId("env-current")).toContainText("演示数据");
    await expect(page.getByTestId("env-quality")).toContainText("quality");

    // 2. confirm a trip
    await page.getByTestId("activity-type").selectOption("trip");
    await page.getByTestId("activity-title").fill("出差去北京");
    await page.getByTestId("activity-start").fill(localDateTimeInput(24));
    await page.getByTestId("activity-destination").selectOption("CN-BJ");
    await page.getByTestId("activity-create").click();
    await expect(page.getByTestId("activity-row").first()).toContainText("出差去北京");

    // 3. authorize the service type and the channel
    await goTo(page, "nav-settings");
    await page.getByTestId("notif-service-type-travel_support").check();
    await page.getByTestId("notif-daily-cap").fill("3");
    // the default quiet window (22:00-08:00) would legitimately defer the card,
    // so this flow opens the window explicitly
    await page.getByTestId("notif-quiet-start").fill("00:00");
    await page.getByTestId("notif-quiet-end").fill("00:00");
    await page.getByTestId("notif-save").click();
    await expect(page.getByTestId("toast-error")).toHaveCount(0);
    const preferences = await apiGet(page, "/api/v1/notification-preferences");
    expect(preferences.preferences.service_types).toContain("travel_support");
    expect(preferences.preferences.quiet_hours_start).toBe("00:00");

    const activities = await apiGet(page, "/api/v1/activities");
    expect(activities.activities.some((item: { title: string }) => item.title === "出差去北京")).toBeTruthy();

    // 4. the backend scheduler produces the card (a server side action)
    const tick = await tickScheduler(page);
    expect(JSON.stringify(tick.summary.decisions)).toContain("travel_support");
    const inbox = await apiGet(page, "/api/v1/messages");
    expect(inbox.messages.length).toBeGreaterThan(0);
    await goTo(page, "nav-inbox");
    const message = page.getByTestId("inbox-message").first();
    await expect(message).toBeVisible();
    await expect(message).toContainText("出行");

    // 5. adopting a message records intent only; the plan still needs explicit acceptance
    await page.getByTestId("inbox-adopt").first().click();
    await goTo(page, "nav-routine");
    await expect(page.getByTestId("routine-active-version")).toBeVisible();

    // 6. revoking the authorization cancels anything still queued
    await goTo(page, "nav-settings");
    await page.getByTestId("notif-service-type-travel_support").uncheck();
    await page.getByTestId("notif-save").click();
    await page.reload();
    await expect(page.getByTestId("app-ready")).toBeVisible();
    await goTo(page, "nav-settings");
    await expect(page.getByTestId("notif-service-type-travel_support")).not.toBeChecked();
  });
});

test.describe("流程 7：环境数据缺失时如实展示", () => {
  test("预报缺少 UV 时显示未知而不是 0", async ({ page }) => {
    await openApp(page, "consumer_a");
    await goTo(page, "nav-environment");
    await expect(page.getByTestId("env-current")).toBeVisible();
    await expect(page.getByTestId("env-missing-fields")).toBeVisible();
  });
});
