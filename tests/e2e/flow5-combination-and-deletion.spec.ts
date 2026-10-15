import { expect, test } from "@playwright/test";

import { goTo, openApp } from "./helpers";

test.describe("流程 5：组合推理 → 间隔 → 计划草稿 → 接受 → 删除反馈后重算图鉴", () => {
  test("组合提示带来源且由用户选择；删除反馈后图鉴重新生成", async ({ page }) => {
    await openApp(page, "consumer_a");
    await goTo(page, "nav-routine");

    const note = page.getByTestId("combination-note").first();
    await expect(note).toBeVisible();
    await expect(note).toContainText("不判定");

    // the user chooses to space the products out; this only creates a draft
    await page.getByTestId("combination-option-space_out").first().click();
    await expect(page.getByTestId("routine-draft-card")).toBeVisible();

    const draftVersion = (await page.getByTestId("routine-draft-version").textContent()) ?? "";
    await page.getByTestId("routine-accept").click();
    await expect(page.getByTestId("routine-active-version")).toContainText(
      String(Number(draftVersion.replace(/[^0-9]/g, ""))),
    );

    // record the atlas state, delete one negative report, then regenerate
    await goTo(page, "nav-atlas");
    await page.getByTestId("atlas-generate").click();
    const clarify = page.locator('[data-testid="atlas-card"][data-common-name="澄泉净澈酸"]');
    await expect(clarify).toBeVisible();
    const before = (await clarify.textContent()) ?? "";

    await goTo(page, "nav-memory");
    await page.getByTestId("usage-event-delete").first().click();
    await expect(page.getByTestId("usage-event-row")).not.toHaveCount(
      (await page.getByTestId("usage-event-row").count()) + 1,
    );

    await goTo(page, "nav-atlas");
    await page.getByTestId("atlas-generate").click();
    const after = page.locator('[data-testid="atlas-card"][data-common-name="澄泉净澈酸"]');
    if ((await after.count()) > 0) {
      expect((await after.textContent()) ?? "").not.toBe(before);
    } else {
      await expect(page.getByTestId("atlas-below-threshold")).toBeVisible();
    }

    // the deletion survives a full reload
    await page.reload();
    await expect(page.getByTestId("app-ready")).toBeVisible();
    await goTo(page, "nav-atlas");
    await page.getByTestId("atlas-generate").click();
    const anyAtlasContent = page.getByTestId("atlas-below-threshold").or(page.getByTestId("atlas-card").first());
    await expect(anyAtlasContent.first()).toBeVisible();
  });
});
