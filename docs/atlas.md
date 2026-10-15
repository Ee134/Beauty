# 成分图鉴：数据、来源与冲突处理

本文件是规格 §8.1 与 §18「图鉴 API 文档、来源冲突处理说明、生活延伸来源清单」的交付物。
所有条目都能在 `data/sources/demo_ingredients.json` 与 `data/sources/real_sources.json` 中找到原始定义。

## 1. 图鉴 API

| 方法与路径 | 说明 |
|---|---|
| `GET /api/v1/ingredients/atlas?min_events=3` | 主动查看时生成并持久化一个新版本视图；**不会自动推送**。每次调用都重算，因此删除反馈后立即反映 |
| `GET /api/v1/ingredients/atlas/latest` | 只读取最近一次生成的视图（不会隐式生成） |
| `GET /api/v1/ingredients/{ingredient_id}` | 单成分详情：功效 / 致敏性 / 生活延伸 / 来源 / 被丢弃的延伸 |
| `POST /api/v1/ingredients/feedback` | 用户对某成分的明确陈述，写入 `IngredientFeedback`（与统计信号分开显示） |
| `GET /api/v1/ingredient-feedback` / `DELETE .../{id}` | 列出 / 删除自己的补充陈述 |
| `GET /api/v1/combinations` | 当前柜内组合推理结果（逐条附来源） |
| `POST /api/v1/combinations/choice` | 用户对组合提示的选择：`keep` / `space_out` / `remove_one`（后两者只生成草稿） |

响应结构（`GET /ingredients/atlas`）：

```json
{
  "generated_at": "…", "min_events": 3, "mode": "mock", "version": 2,
  "disclaimer": "此信息仅供日常参考，不替代专业建议。",
  "cards": [{
    "ingredient_id": "…", "inci_name": "Demo Clarify Acid", "common_name": "澄泉净澈酸",
    "data_status": "approved | insufficient | pending_review",
    "data_note": null,
    "known_effects": [{"text": "…", "citation": {"citation_id": "…", "source_id": "…", "title": "…"}}],
    "irritancy": {"level": "moderate", "notes": [{"text": "…", "citation": {…}}], "has_source": true},
    "user_signal": {
      "positive_count": 2, "negative_count": 3, "total_count": 5,
      "positive_event_ids": ["…"], "negative_event_ids": ["…"],
      "statement": "你的反馈中，含此成分的产品出现了 3 次负面体验。此成分与你的负面反馈有统计关联，但不代表因果关系。",
      "causality_notice": "统计关联不代表因果关系。"
    },
    "life_extensions": [{"kind": "sun_care", "text": "…", "citation": {…}, "notice": "此延伸基于已审核来源，非个人诊断"}],
    "uncertainty": "…", "disclaimer": "此信息仅供日常参考，不替代专业建议。"
  }],
  "below_threshold": [{"common_name": "…", "positive_count": 1, "negative_count": 1, "min_events": 3, "message": "样本不足（…）"}],
  "pending": [],
  "dropped_life_extensions": [{"inci_name": "…", "text": "…", "reason": "SOURCE_NOT_APPROVED"}],
  "signal_ids": ["…"],
  "stats": {"card_count": 4, "below_threshold_count": 2, "pending_count": 0, "approved_card_count": 4, "insufficient_card_count": 0, "pending_review_card_count": 0}
}
```

## 2. 演示成分档案（全部虚构，`is_demo=true`）

| key | INCI | 通俗名 | approval_status | 致敏等级 | 生活延伸 |
|---|---|---|---|---|---|
| I01 | Demo Hydra-Glucan | 澄泉保湿多糖 | approved | unknown | 无 |
| I02 | Demo Calm-Complex | 澄泉舒缓复合物 | approved | unknown | 无 |
| I03 | Demo Retinoid Ester | 澄泉类视黄醇酯 | approved | moderate | **sun_care（有来源）** |
| I04 | Demo Photo-Shield | 澄泉光护因子 | approved | unknown | 无 |
| I05 | Demo Clarify Acid | 澄泉净澈酸 | approved | moderate | diet（**故意指向未审核来源** → 不展示，负样本） |
| I06 | Demo Mystic Extract | 澄泉神秘提取物 | **insufficient** | unknown | 无 |
| I07 | Demo Amber-Active | 澄泉琥珀活性物 | **pending_review（来源冲突）** | unknown | 无 |
| I08 | Demo Cleansing Betaine | 澄泉洁面甜菜碱 | approved | unknown | 无 |
| I09 | Demo Ceramide-Like | 澄泉类神经酰胺 | approved | unknown | 无 |

## 3. 真实成分与审核来源（3 个）

| INCI | 通俗名 | 来源 | URL | 抓取时间 | 审核 |
|---|---|---|---|---|---|
| Niacinamide | 烟酰胺 | PubChem CID 936（NCBI PUG-View 端点） | https://pubchem.ncbi.nlm.nih.gov/compound/936 | 2026-10-15T12:38:04Z | `demo_seed`（**非品牌/医学审核**） |
| Salicylic Acid | 水杨酸 | PubChem CID 338 | https://pubchem.ncbi.nlm.nih.gov/compound/338 | 2026-10-15T12:38:04Z | `demo_seed` |
| Retinol | 视黄醇（维生素A） | PubChem CID 445354 | https://pubchem.ncbi.nlm.nih.gov/compound/445354 | 2026-10-15T12:38:04Z | `demo_seed` |

### 致敏等级映射规则（可复现）

| 来源表述 | 映射等级 |
|---|---|
| 来源明确写 “slightly irritating” | `low`（水杨酸使用此条） |
| GHS 分类含 `H315`（皮肤刺激） | `moderate`（烟酰胺使用此条） |
| GHS 分类含 `H317`（皮肤致敏） | `high`（视黄醇使用此条） |
| 无相关分类 | `unknown` |

这些是**工业化学品危害分类汇总**，不等于化妆品成品的刺激性结论；每条 note 与
`approval_note` 都写明这一点。规则本身不来自模型推断，写在
`data/sources/real_sources.json` 的 `_meta.irritancy_mapping_rule`。

## 4. 生活延伸来源清单

只有同时满足「来源 approved」「与已知功效/致敏性直接相关」「不含医疗或购买建议」的延伸才会展示，
并固定附带「此延伸基于已审核来源，非个人诊断」。

| # | 成分 | kind | 展示文案 | 支撑来源 |
|---|---|---|---|---|
| 1 | Demo Retinoid Ester（I03） | `sun_care` | 含此成分的产品建议晚间使用；白天注意防晒 | `SRC-I03`（虚构演示资料，approved） |
| 2 | Niacinamide（R01） | `diet` | 该物质也被直接添加到人类食品中并被确认为 GRAS，可作为营养强化剂用于膳食补充（不构成饮食建议，也不替代外用产品） | `SRC-REAL-PUBCHEM-NIACINAMIDE`（PubChem CID 936，FDA Requirements 段落，approved） |
| 3 | Retinol（R03） | `storage` | 维生素A对空气和光不稳定，应避光、避免空气暴露保存；制剂宜存放于 40°C 以下，最好在 15–30°C | `SRC-REAL-PUBCHEM-RETINOL`（PubChem CID 445354，Storage Conditions 段落，approved） |

**被拒绝的延伸（负样本，永不出现在建议中）**：

| 成分 | 文案 | 原因 |
|---|---|---|
| Demo Clarify Acid（I05） | 多吃含此成分的食物对皮肤好 | 来源 `SRC-I05-DRAFT` 状态为 `pending` → `dropped_life_extensions` 中标记 `SOURCE_NOT_APPROVED` |

产品来源中也存在可用延伸，会随产品级引用出现（不进入成分图鉴卡片）：

| 产品 | 文案 | 来源 |
|---|---|---|
| 澄泉轻透防晒乳 SPF50+ PA++++ | 紫外线较强时建议配合遮阳帽或遮阳伞使用 | `SRC-D08`（虚构演示资料，approved） |
| 澄泉焕活精华 | 使用本品期间建议白天注意防晒 | `SRC-D05`（虚构演示资料，approved） |

> 注意：Retinol 的 PubChem 记录里**没有**关于化妆品光稳定性或「需配合防晒」的表述，
> 因此**没有**生成该类延伸。这一点在 `real_sources.json` 的 `approval_note` 中明确记录。

## 5. 来源冲突处理

1. 同一成分的两份 `approved` 来源若被标记为同一 `conflict_group`，该成分的
   `approval_status` 置为 `pending_review`、`conflict_flag=true`。
2. 图鉴卡片 `data_status = "pending_review"`，`data_note = "信息存在冲突，待审核"`，
   `known_effects` 与致敏性**都为空**（不选边、不取平均值、不按新旧时间取舍）。
3. 产品级冲突：`load_product_knowledge()` 返回 `SOURCE_CONFLICT`，该产品
   不排入计划（进入待确认列表）、不参与组合推理。
4. 演示负样本：`I07 Demo Amber-Active` + `SRC-I07A` / `SRC-I07B`（同一 `conflict_group=I07-conflict`）。
5. 处理路径：人工审核后在种子/管理数据中修改 `approval_status` 与来源状态，图鉴下次生成即生效。

## 6. 信号提取规则

- 只统计 `UsageEvent`（`provenance=user_report`，`invalidated_at IS NULL`，`event_type ∈ {positive, negative}`）。
- 成分来自**事件所关联产品的 approved 来源**；产品无 approved 成分资料 → 该事件不贡献任何信号。
- 同一成分同一极性的事件数 ≥ `ATLAS_MIN_EVENTS`（默认 3）才会出现在 `cards`；否则进入 `below_threshold`。
- `contributing_event_ids` 记录血缘：删除事件 → `UserIngredientSignal` 立即 `invalidated_at` 非空，
  图鉴下次生成时该信号不再出现。
- 展示措辞只使用：`你的反馈中，含此成分的产品出现了 N 次负面体验`、
  `此成分与你的负面反馈有统计关联，但不代表因果关系`。
  生成时用 `assert_allowed_wording()` 校验，命中禁用模式（`你对…过敏` / `…导致你的…` / `避免…成分` / `确诊`）
  的卡片会被移出 `cards` 并记入 `pending`。

## 7. 演示数据对照

| 用户 | 反馈事件 | 触发图鉴？ |
|---|---|---|
| `consumer_a` | 12 条（正向 6 / 负向 6） | 是：4 张卡片（2 正 2 负），2 个成分样本不足 |
| `consumer_b` | 1 条 | 否：全部显示「样本不足」 |
