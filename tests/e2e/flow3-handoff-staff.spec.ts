import { expect, test } from "@playwright/test";

import { goTo, openApp, switchPersona } from "./helpers";

test.describe("流程 3：交接预览 → 本地客服 → 进度查询", () => {
  test("用户预览并确认后才提交，客服更新状态，进度查询不编造结果", async ({ page }) => {
    await openApp(page, "consumer_a");
    await goTo(page, "nav-service");

    await expect(page.getByTestId("handoff-candidates")).toBeVisible();
    await page.getByTestId("handoff-candidate-checkbox").first().check();
    await page.getByTestId("handoff-request-input").fill("防晒乳刺痛问题，希望人工确认下一步安排");
    await page.getByTestId("handoff-preview-button").click();

    await expect(page.getByTestId("handoff-preview")).toBeVisible();
    await expect(page.getByTestId("handoff-preview-status")).toContainText("草稿");
    // still a draft: nothing has been submitted
    await expect(page.getByTestId("ticket-status")).toHaveCount(0);

    await page.getByTestId("handoff-submit").click();
    await expect(page.getByTestId("ticket-status")).toContainText("已提交");
    await expect(page.locator("body")).toContainText("本地演示工作台");

    // the demo staff console is a separate role and is clearly marked as simulated
    await switchPersona(page, "staff");
    await goTo(page, "nav-staff");
    const row = page.getByTestId("staff-ticket-row").first();
    await expect(row).toBeVisible();
    const ticketId = await row.getAttribute("data-ticket-id");
    expect(ticketId, "each staff queue row must expose its ticket id").toBeTruthy();
    await page.goto(`/staff/tickets/${ticketId}`);
    await expect(page.getByTestId("ticket-status")).toBeVisible();
    await page.getByTestId("staff-ticket-status-select").selectOption("resolved");
    await page.getByTestId("staff-ticket-note").fill("已提供一般性建议，未做诊断");
    await page.getByTestId("staff-ticket-save").click();
    await expect(page.getByTestId("ticket-status")).toContainText("演示工作台标记已处理");

    // back to the consumer: asking about progress returns the real stored status
    await openApp(page, "consumer_a");
    await goTo(page, "nav-chat");
    await page.getByTestId("chat-input").fill("我上次那个工单现在处理到哪了？");
    await page.getByTestId("chat-send").click();
    await expect(page.getByTestId("chat-card-service_status")).toBeVisible();

    await goTo(page, "nav-service");
    await expect(page.getByTestId("ticket-status")).toContainText("演示工作台标记已处理");
    // the timeline lives behind "查看时间线" on the consumer service page
    await page.getByRole("button", { name: "查看时间线" }).first().click();
    await expect(page.getByTestId("ticket-timeline")).toContainText("提交");
  });
});
