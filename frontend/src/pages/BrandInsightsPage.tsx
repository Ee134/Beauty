/**
 * /brand/insights 演示品牌需求面板。
 * 只做本地演示汇总：群体不足时抑制明细；不存在任何真实外发通道。
 * 「显式需求」与「模型推测」分开显示（spec 第 24 节 / AC37 / AC38）。
 */

import { useState } from "react";
import {
  brandFeedbackConsent,
  createBrandDraft,
  getBrandInsights,
  listBrandDrafts,
} from "../api/endpoints";
import type { BrandInsightsResponse } from "../api/types";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  EmptyState,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDateTime } from "../lib/format";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

const CATEGORIES = [
  { value: "source_gap", label: "资料缺失（版本说明不完整）" },
  { value: "service_gap", label: "服务缺失（无法查询实际工单）" },
  { value: "explicit_product_request", label: "显式产品需求（用户明确想找某类产品）" },
  { value: "feature_request", label: "功能建议" },
] as const;

export function BrandInsightsPage(): JSX.Element {
  const toast = useToast();
  const { me, lastLoadedAt } = useSession();
  const insights = useAsync<BrandInsightsResponse>(() => getBrandInsights(), { deps: [lastLoadedAt] });
  const drafts = useAsync(() => listBrandDrafts(), { deps: [lastLoadedAt] });
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]["value"]>("source_gap");
  const [summary, setSummary] = useState("");
  const [explicitness, setExplicitness] = useState<"explicit" | "inferred">("explicit");

  const createDraft = useAction(() =>
    createBrandDraft({ category, summary: summary.trim(), explicitness }),
  );
  const consent = useAction<[string, boolean], Awaited<ReturnType<typeof brandFeedbackConsent>>>((id, granted) =>
    brandFeedbackConsent(id, granted),
  );

  const refresh = () => {
    insights.reload();
    drafts.reload();
  };

  const isBrandRole = me?.user.role === "brand";

  return (
    <div className="stack">
      <Panel
        title="品牌需求面板（演示）"
        subtitle="仅展示本租户的合成/汇总数据；不含原始对话、症状、精确定位或订单截图"
        actions={
          <button type="button" onClick={refresh}>
            刷新
          </button>
        }
      >
        <div className="row tight">
          <Badge tone="mock">mode：{insights.data?.mode ?? "mock"}</Badge>
          <Badge tone={isBrandRole ? "ok" : "warn"}>
            当前角色：{me?.user.role ?? "未知"}
            {isBrandRole ? "（品牌角色，可读取聚合）" : "（非品牌角色，接口会返回 403 FORBIDDEN）"}
          </Badge>
        </div>
        <Notice tone="mock">
          本 MVP 不存在真实品牌外发通道：品牌台只做演示汇总，不会向任何品牌发送数据。
        </Notice>
      </Panel>

      <Panel title="聚合汇总" subtitle="GET /brand/insights（群体不足时抑制明细）">
        <AsyncBlock
          loading={insights.loading}
          error={insights.error}
          data={insights.data}
          onRetry={insights.reload}
          loadingLabel="加载品牌汇总…"
        >
          {(data) => (
            <div className="stack">
              <div className="row tight">
                <Badge tone={data.suppressed ? "warn" : "ok"}>
                  群体规模 {data.cohort_size} / 抑制阈值 {data.min_cohort}
                </Badge>
                <Badge>草稿 {data.totals.drafts}</Badge>
                <Badge>已同意分享 {data.totals.consented}</Badge>
                <Badge>显式 {data.totals.explicit}</Badge>
                {data.suppressed && <Badge tone="warn">已抑制明细展示</Badge>}
              </div>
              {data.suppression_notice && <Notice>{data.suppression_notice}</Notice>}
              {data.groups.length === 0 ? (
                <EmptyState>暂无聚合分组（没有需求草稿）。</EmptyState>
              ) : (
                <div className="grid wide">
                  {data.groups.map((group) => (
                    <div className="step" key={group.category}>
                      <div className="row tight">
                        <Badge tone="accent">{group.category_label}</Badge>
                        <Badge>草稿 {group.draft_count}</Badge>
                        <Badge>去重用户 {group.distinct_users}</Badge>
                        <Badge tone="ok">已同意 {group.consented_count}</Badge>
                        <Badge>显式 {group.explicit_count}</Badge>
                        <Badge tone="warn">推测 {group.inferred_count}</Badge>
                      </div>
                      <div className="panel-sub" style={{ marginTop: 6 }}>
                        高频主题
                      </div>
                      <ul className="small">
                        {group.themes.map((theme) => (
                          <li key={theme.theme}>
                            {theme.theme} × {theme.count}
                          </li>
                        ))}
                      </ul>
                      {group.sample_redacted.length > 0 && (
                        <>
                          <div className="panel-sub">去标识示例（最多 3 条）</div>
                          <ul className="small">
                            {group.sample_redacted.map((sample, index) => (
                              <li key={index}>
                                {sample.summary}（出现 {sample.occurrence_count} 次 · 审核状态{" "}
                                {sample.review_status}）
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel
        title="生成内部需求草稿"
        subtitle="POST /brand-feedback/drafts（自动整理，不自动外发；显式与推测分开）"
      >
        <div className="row">
          <div className="field">
            <label htmlFor="draft-category">类别</label>
            <select
              id="draft-category"
              value={category}
              onChange={(event) => setCategory(event.target.value as typeof category)}
            >
              {CATEGORIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="draft-explicitness">来源性质</label>
            <select
              id="draft-explicitness"
              value={explicitness}
              onChange={(event) => setExplicitness(event.target.value as "explicit" | "inferred")}
            >
              <option value="explicit">显式（用户明确表达）</option>
              <option value="inferred">推测（不代表购买意愿）</option>
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 260 }}>
            <label htmlFor="draft-summary">摘要 *</label>
            <input
              id="draft-summary"
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              placeholder="例如：某版本说明缺少成分表"
            />
          </div>
          <button
            type="button"
            className="primary"
            disabled={createDraft.running || summary.trim().length < 2}
            onClick={() => {
              void (async () => {
                const result = await createDraft.run();
                if (result) {
                  toast.show(result.notice);
                  setSummary("");
                  refresh();
                }
              })();
            }}
          >
            {createDraft.running ? "生成中…" : "生成内部草稿"}
          </button>
        </div>
        <Notice>
          用户没有某件产品不会被解释为想购买；真实外发需要用户独立同意与品牌运营审核（本演示未实现外发）。
        </Notice>
        <ActionFeedback error={createDraft.error} />
      </Panel>

      <Panel title="我的需求草稿" subtitle="GET /brand-feedback/drafts（含同意状态）">
        <AsyncBlock
          loading={drafts.loading}
          error={drafts.error}
          data={drafts.data}
          onRetry={drafts.reload}
          isEmpty={(data) => data.drafts.length === 0}
          empty="还没有需求草稿。"
        >
          {(data) => (
            <table className="table">
              <thead>
                <tr>
                  <th>类别</th>
                  <th>摘要</th>
                  <th>来源性质</th>
                  <th>同意分享</th>
                  <th>审核状态</th>
                  <th>出现次数</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.drafts.map((draft) => (
                  <tr key={draft.id}>
                    <td>{draft.category_label}</td>
                    <td>{draft.summary}</td>
                    <td>
                      <Badge tone={draft.explicitness === "explicit" ? "ok" : "warn"}>
                        {draft.explicitness === "explicit" ? "显式" : "推测"}
                      </Badge>
                    </td>
                    <td>{draft.user_consent ? "已同意" : "未同意"}</td>
                    <td>{draft.review_status}</td>
                    <td>{draft.occurrence_count}</td>
                    <td className="small">{formatDateTime(draft.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        disabled={consent.running}
                        onClick={() => {
                          void (async () => {
                            const result = await consent.run(draft.id, !draft.user_consent);
                            if (result) {
                              toast.show(result.notice);
                              refresh();
                            }
                          })();
                        }}
                      >
                        {draft.user_consent ? "撤回同意" : "同意分享范围"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </AsyncBlock>
        <ActionFeedback error={consent.error} />
        <Notice>
          同意仅表示分享范围获得授权；仍需品牌运营审核后才会外发，而本 MVP 不存在外发通道。
        </Notice>
      </Panel>
    </div>
  );
}
