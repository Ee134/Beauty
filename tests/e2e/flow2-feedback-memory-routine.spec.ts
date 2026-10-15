import { expect, test } from "@playwright/test";

import { goTo, openApp } from "./helpers";

test.describe("流程 2：反馈 → 记忆修正 → 计划版本", () => {
  test("负面反馈只生成复核询问，确认暂停后产生 v+1 草稿，历史与记忆都保留", async ({ page }) => {
    await openApp(page, "consumer_a");
    await goTo(page, "nav-routine");
    await expect(page.getByTestId("routine-active-version")).toBeVisible();
    const activeVersionBefore = (await page.getByTestId("routine-active-version").textContent()) ?? "";
    const versionBefore = Number(activeVersionBefore.replace(/[^0-9]/g, "")) || 1;

    // 1. report a negative experience in chat
    await goTo(page, "nav-chat");
    await page.getByTestId("chat-input").fill("昨晚用了澄泉光感精华之后有点刺痛");
    await page.getByTestId("chat-send").click();

    await expect(page.getByTestId("chat-card-review_prompt")).toBeVisible();

    // 2. answer the explicit review question with "pause" (still on the chat screen)
    await expect(page.getByTestId("review-prompt-pause")).toBeVisible();
    await page.getByTestId("review-prompt-pause").click();
    await expect(page.getByTestId("toast-error")).toHaveCount(0);

    // 3. the plan itself is untouched until the produced draft is accepted
    await goTo(page, "nav-routine");
    await expect(page.getByTestId("routine-active-version")).toContainText(String(versionBefore));
    await expect(page.getByTestId("routine-draft-card")).toBeVisible();
    const draftVersionText = (await page.getByTestId("routine-draft-version").textContent()) ?? "";
    expect(Number(draftVersionText.replace(/[^0-9]/g, ""))).toBeGreaterThan(versionBefore);
    await expect(page.getByTestId("routine-active-version")).toContainText(String(versionBefore));

    await page.getByTestId("routine-accept").click();
    await expect(page.getByTestId("routine-active-version")).toContainText(String(versionBefore + 1));
    await expect(page.getByTestId("routine-history")).toBeVisible();

    // 4. the feedback stays in memory and the correction is versioned
    await goTo(page, "nav-memory");
    await expect(page.getByTestId("usage-event-row").first()).toBeVisible();

    const budget = page.locator('[data-testid="memory-record"][data-key="routine.budget_monthly"]');
    await expect(budget.first()).toBeVisible();
    await page.getByTestId("memory-edit-routine.budget_monthly").click();
    await page.getByTestId("memory-edit-value").fill("500");
    await page.getByTestId("memory-edit-save").click();

    const active = page.locator(
      '[data-testid="memory-record"][data-key="routine.budget_monthly"][data-status="active"]',
    );
    await expect(active).toContainText("500");
    const superseded = page.locator(
      '[data-testid="memory-record"][data-key="routine.budget_monthly"][data-status="superseded"]',
    );
    await expect(superseded).toContainText("300");

    // 5. the corrected preference survives a reload (server side state)
    await page.reload();
    await expect(page.getByTestId("app-ready")).toBeVisible();
    await goTo(page, "nav-memory");
    await expect(
      page.locator('[data-testid="memory-record"][data-key="routine.budget_monthly"][data-status="active"]'),
    ).toContainText("500");
  });
});
