import { expect, test } from "@playwright/test";
import path from "node:path";

import { goTo, openApp } from "./helpers";

// Playwright runs with cwd = the config directory (the repository root).
const DEMO_SCREENSHOT = path.resolve(
  process.cwd(),
  "data",
  "fixtures",
  "imports",
  "demo_order_screenshot_1.png",
);

test.describe("流程 1：导入截图 → 修正候选 → 确认入柜 → 计划草稿 → 接受", () => {
  test("用户修正候选后确认导入，并接受生成的计划", async ({ page }) => {
    await openApp(page, "consumer_a");
    await goTo(page, "nav-cabinet");

    await page.getByTestId("import-file-input").setInputFiles(DEMO_SCREENSHOT);
    await page.getByTestId("import-submit").click();

    await expect(page.getByTestId("import-candidates")).toBeVisible();
    const rows = page.getByTestId("import-candidate-row");
    await expect(rows).toHaveCount(2);
    await expect(page.getByTestId("import-status")).toContainText("mock");

    // correct the first candidate's name before confirming
    const corrected = "澄泉轻透防晒乳（已修正）";
    await page.getByTestId("import-candidate-name-0").fill(corrected);
    await page.getByTestId("import-candidate-qty-0").fill("1");
    await page.getByTestId("import-confirm").click();

    // the confirmation happens on the import screen; the cabinet reflects it afterwards
    await goTo(page, "nav-cabinet");
    await expect(page.getByTestId("cabinet-list")).toContainText(corrected);

    // ask for a plan in chat, then accept the draft through the confirmation button
    await goTo(page, "nav-chat");
    await page.getByTestId("chat-input").fill("帮我把这些产品安排成早晚流程");
    await page.getByTestId("chat-send").click();

    await expect(page.getByTestId("chat-card-routine_draft")).toBeVisible();
    const accept = page.getByTestId("chat-pending-action-accept_routine");
    await expect(accept).toBeVisible();
    await accept.click();

    await goTo(page, "nav-routine");
    await expect(page.getByTestId("routine-active")).toBeVisible();
    await expect(page.getByTestId("routine-active-version")).not.toBeEmpty();
    await expect(page.getByTestId("routine-step").first()).toBeVisible();
  });
});
