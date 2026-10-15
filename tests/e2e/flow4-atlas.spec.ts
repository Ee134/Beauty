import { expect, test } from "@playwright/test";

import { goTo, openApp } from "./helpers";

test.describe("流程 4：反馈积累 → 图鉴查看 → 成分补充陈述 → 来源缺失展示", () => {
  test("图鉴逐卡展示来源、事件计数与不确定性，无来源时显示暂无充分信息", async ({ page }) => {
    await openApp(page, "consumer_a");
    await goTo(page, "nav-atlas");
    await page.getByTestId("atlas-generate").click();

    const cards = page.getByTestId("atlas-card");
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThanOrEqual(4);

    // every card must show its own data status and the association wording
    for (let index = 0; index < (await cards.count()); index += 1) {
      const card = cards.nth(index);
      await expect(card.getByTestId("atlas-card-status")).not.toBeEmpty();
      await expect(card).toContainText("不替代专业建议");
    }

    const clarify = page.locator('[data-testid="atlas-card"][data-common-name="澄泉净澈酸"]');
    await expect(clarify).toBeVisible();
    await expect(clarify).toContainText("出现了");
    await expect(clarify).toContainText("不代表因果关系");
    await expect(clarify).not.toContainText("过敏");

    // life extensions without an approved source are listed as an audit note, never as advice
    await expect(page.getByTestId("atlas-dropped-extensions")).toBeVisible();
    await expect(page.getByTestId("atlas-dropped-extensions")).toContainText("无已审核来源");
    const allCardText = (await cards.allTextContents()).join("\n");
    expect(allCardText).not.toContain("多吃含此成分的食物对皮肤好");

    // an ingredient with no approved sources explains itself
    const insufficient = page.locator('[data-testid="atlas-card"]', { hasText: "暂无充分信息" });
    if ((await insufficient.count()) > 0) {
      await expect(insufficient.first()).not.toContainText("已知功效");
    }

    // the user can attach their own explicit statement to an ingredient
    const ingredientSelect = page.getByTestId("atlas-feedback-ingredient");
    await ingredientSelect.selectOption({ index: 0 });
    const statementInput = page.getByTestId("atlas-feedback-input");
    const submit = page.getByTestId("atlas-feedback-submit");
    await expect(submit).toBeDisabled();
    await statementInput.fill("我确定在使用含水杨酸的产品时会更谨慎");
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(statementInput).toHaveValue("");
  });
});
