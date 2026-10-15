/**
 * /routine 早晚计划：当前版本、草稿与差异、接受、历史版本、组合提示。
 * 计划变更一律需要用户显式接受（accept 携带 expected_version，冲突返回 409）。
 */

import { useState } from "react";
import {
  acceptRoutine,
  createRoutineDraft,
  getCombinations,
  listReviewPrompts,
  listRoutines,
  postCombinationChoice,
  restoreRoutine,
} from "../api/endpoints";
import type {
  AcceptRoutineResponse,
  Citation,
  CombinationNoteRecord,
  CombinationsResponse,
  RoutineDraftResponse,
  RoutineListResponse,
  RoutinePlan,
} from "../api/types";
import { ReviewPromptCardLite } from "../components/ReviewPromptInline";
import { StepView } from "../components/cards/TurnCards";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  EmptyState,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDateTime, truncate } from "../lib/format";
import {
  COMBINATION_OPTION_TEST_IDS,
  combinationOptionLabel,
  periodLabel,
  planStatusLabel,
} from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

export function RoutinePage(): JSX.Element {
  const toast = useToast();
  const { me, refreshContext, refreshMe, lastLoadedAt } = useSession();
  const routines = useAsync<RoutineListResponse>(() => listRoutines(), { deps: [lastLoadedAt] });
  const prompts = useAsync(() => listReviewPrompts(), { deps: [lastLoadedAt] });
  const combinations = useAsync<CombinationsResponse>(() => getCombinations(), { deps: [lastLoadedAt] });
  const [draft, setDraft] = useState<RoutineDraftResponse | null>(null);

  const generate = useAction<[], RoutineDraftResponse>(() => createRoutineDraft({ trigger: "user_request" }));
  const accept = useAction<[string, number | null], AcceptRoutineResponse>((planId, version) =>
    acceptRoutine(planId, version),
  );
  const restore = useAction<[string], RoutineDraftResponse>((planId) => restoreRoutine(planId));

  const refreshAll = () => {
    routines.reload();
    prompts.reload();
    combinations.reload();
    void refreshContext();
    void refreshMe();
  };

  const runGenerate = async () => {
    const result = await generate.run();
    if (result) {
      setDraft(result);
      toast.show(result.notice);
      refreshAll();
    }
  };

  const runAccept = async (planId: string, expectedVersion: number | null) => {
    const result = await accept.run(planId, expectedVersion);
    if (result) {
      toast.show(result.notice);
      setDraft(null);
      refreshAll();
    }
  };

  const runRestore = async (planId: string) => {
    const result = await restore.run(planId);
    if (result) {
      setDraft(result);
      toast.show(result.notice);
      refreshAll();
    }
  };

  // 引用查询表：把计划内所有步骤的 citation 收集起来，供组合提示 chip 复用。
  const citationLookup = new Map<string, Citation>();
  for (const plan of [routines.data?.active, ...(routines.data?.history ?? [])]) {
    for (const step of plan?.steps ?? []) {
      for (const citation of step.citations ?? []) {
        citationLookup.set(citation.citation_id, citation);
      }
    }
  }

  const active = routines.data?.active ?? null;
  // a draft can also be produced elsewhere (chat review decision, combination choice in
  // another tab), so fall back to the newest draft in the history list
  const draftFromHistory = (routines.data?.history ?? []).find((plan) => plan.status === "draft") ?? null;
  const draftPlan = draft?.plan ?? draftFromHistory;

  return (
    <div className="stack">
      <Panel
        title="早晚计划"
        subtitle="每用户最多一份生效版本；草稿在接受前不会生效"
        actions={
          <>
            <button
              type="button"
              className="primary"
              data-testid="routine-generate"
              disabled={generate.running}
              onClick={() => void runGenerate()}
            >
              {generate.running ? "生成中…" : "生成计划草稿"}
            </button>
            <button type="button" onClick={refreshAll}>
              刷新
            </button>
          </>
        }
      >
        <Notice>
          POST /routines/drafts 只创建 draft；POST /routines/&#123;id&#125;/accept 由你显式调用，并携带
          expected_version。同时接受两份草稿时，过时请求返回 409。
        </Notice>
        <ActionFeedback error={generate.error} />
        {draft && (
          <div className="state" style={{ marginTop: 8 }}>
            已生成草稿{draft.plan ? ` v${draft.plan.version}` : ""}。{draft.notice}
            {draft.questions.length > 0 && (
              <ul className="small">
                {draft.questions.map((question) => (
                  <li key={question.key}>
                    {question.question}
                    {question.why ? `（${question.why}）` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Panel>

      <Panel title="当前生效版本" subtitle={active ? `v${active.version}` : "暂无生效版本"} testId="routine-active">
        <AsyncBlock
          loading={routines.loading}
          error={routines.error}
          data={routines.data}
          onRetry={routines.reload}
          loadingLabel="加载计划…"
        >
          {(data) =>
            data.active === null ? (
              <EmptyState hint="点击上方「生成计划草稿」，或先到美妆柜添加产品。">
                当前没有生效中的计划。
              </EmptyState>
            ) : (
              <PlanView
                plan={data.active}
                lookup={citationLookup}
                testIds={{ version: "routine-active-version" }}
              />
            )
          }
        </AsyncBlock>
      </Panel>

      {draftPlan && (
        <Panel
          title={`草稿 v${draftPlan.version}（未生效）`}
          subtitle="接受后成为当前版本；拒绝不会改变现状"
          testId="routine-draft-card"
          actions={
            <button
              type="button"
              className="primary"
              data-testid="routine-accept"
              disabled={accept.running}
              onClick={() => void runAccept(draftPlan.id, draftPlan.version)}
            >
              {accept.running ? "接受中…" : "接受这份草稿"}
            </button>
          }
        >
          <PlanView
            plan={draftPlan}
            lookup={citationLookup}
            testIds={{
              version: "routine-draft-version",
              steps: "routine-draft-steps",
              diff: "routine-diff-summary",
            }}
          />
          <ActionFeedback error={accept.error} />
        </Panel>
      )}

      <Panel title="待复核询问" subtitle="负面反馈只生成复核询问，不自动改计划">
        <AsyncBlock
          loading={prompts.loading}
          error={prompts.error}
          data={prompts.data}
          onRetry={prompts.reload}
          isEmpty={(data) => data.prompts.filter((prompt) => prompt.status === "open").length === 0}
          empty="没有未处理的复核询问。"
        >
          {(data) => (
            <div className="stack">
              {data.prompts
                .filter((prompt) => prompt.status === "open")
                .map((prompt) => (
                  <ReviewPromptCardLite key={prompt.id} prompt={prompt} onDecided={refreshAll} />
                ))}
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="组合适用性提示" subtitle="逐条附来源；系统不替你判定能否叠用">
        <AsyncBlock
          loading={combinations.loading}
          error={combinations.error}
          data={combinations.data}
          onRetry={combinations.reload}
          isEmpty={(data) => data.combination_notes.length === 0}
          empty="当前没有需要提示的组合情况（或产品成分资料不足，未参与组合推理）。"
        >
          {(data) => (
            <div className="stack">
              <div className="small muted">
                计划版本：{data.plan_version === null ? "无生效版本" : `v${data.plan_version}`}
              </div>
              {data.combination_notes.map((note, index) => (
                <CombinationNoteChoice
                  key={index}
                  note={note}
                  index={index}
                  lookup={citationLookup}
                  onChosen={(plan) => {
                    if (plan) {
                      setDraft({
                        plan,
                        questions: [],
                        pending_products: [],
                        combination_notes: [],
                        skipped_combination: [],
                        uncertainties: [],
                        notice: "已生成新草稿；接受前当前版本继续有效。",
                      });
                    }
                    refreshAll();
                  }}
                />
              ))}
              <div>
                <div className="panel-sub">参与组合推理的产品</div>
                <ul className="small">
                  {data.products.map((product) => (
                    <li key={product.owned_product_id}>
                      {product.name} · 成分资料：{product.ingredient_source_status} ·{" "}
                      {product.key_actives.join("、") || "无已提取成分"}
                    </li>
                  ))}
                </ul>
              </div>
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="历史版本" subtitle="历史只读；restore 会创建新草稿而不覆盖历史">
        <AsyncBlock
          loading={routines.loading}
          error={routines.error}
          data={routines.data}
          onRetry={routines.reload}
          isEmpty={(data) => data.history.length === 0}
          empty="还没有历史版本。"
        >
          {(data) => (
            <table className="table" data-testid="routine-history">
              <thead>
                <tr>
                  <th>版本</th>
                  <th>状态</th>
                  <th>步骤</th>
                  <th>接受时间</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.history.map((plan) => (
                  <tr key={plan.id}>
                    <td>v{plan.version}</td>
                    <td>
                      <Badge tone={plan.status === "active" ? "ok" : "default"}>
                        {planStatusLabel(plan.status)}
                      </Badge>
                    </td>
                    <td>{plan.steps.length || "—"}</td>
                    <td>{plan.accepted_at ? formatDateTime(plan.accepted_at, me?.user.timezone) : "—"}</td>
                    <td>{formatDateTime(plan.created_at, me?.user.timezone)}</td>
                    <td>
                      {plan.status !== "active" && (
                        <button type="button" disabled={restore.running} onClick={() => void runRestore(plan.id)}>
                          从此版本创建草稿
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </AsyncBlock>
        <ActionFeedback error={restore.error} />
      </Panel>
    </div>
  );
}

function PlanView({
  plan,
  lookup,
  testIds = {},
}: {
  plan: RoutinePlan;
  lookup: Map<string, Citation>;
  /** 稳定的 E2E 钩子：同一组件在「当前版本」与「草稿」两处渲染。 */
  testIds?: { version?: string; steps?: string; diff?: string };
}): JSX.Element {
  const periods = ["morning", "both", "evening", "as_needed", "weekly", "unknown"];
  const grouped = new Map<string, typeof plan.steps>();
  for (const step of plan.steps) {
    const list = grouped.get(step.period) ?? [];
    list.push(step);
    grouped.set(step.period, list);
  }
  return (
    <div className="stack">
      <div className="row tight">
        <Badge tone={plan.status === "active" ? "ok" : "accent"} data-testid={testIds.version}>
          v{plan.version}
        </Badge>
        <Badge>{planStatusLabel(plan.status)}</Badge>
        <Badge>步骤 {plan.steps.length}</Badge>
        <Badge tone="mock">model_mode：{plan.model_mode}</Badge>
        {plan.needs_review && <Badge tone="warn">需要复核</Badge>}
      </div>
      {plan.needs_review_reason && <Notice>{plan.needs_review_reason}</Notice>}

      {typeof plan.diff === "object" && plan.diff !== null && Object.keys(plan.diff).length > 0 && (
        <div data-testid={testIds.diff}>
          <div className="panel-sub">与上一版本的差异（后端计算）</div>
          <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(plan.diff, null, 1)}
          </pre>
        </div>
      )}

      {plan.reasons.length > 0 && (
        <div>
          <div className="panel-sub">生成原因</div>
          <ul className="small">
            {plan.reasons.map((reason, index) => (
              <li key={index}>{reason.text}</li>
            ))}
          </ul>
        </div>
      )}

      {plan.steps.length === 0 ? (
        <EmptyState>这个版本没有任何步骤（可能所有产品资料都不足）。</EmptyState>
      ) : (
        <div data-testid={testIds.steps}>
          {[...grouped.keys()]
            .sort((a, b) => periods.indexOf(a) - periods.indexOf(b))
            .map((period) => (
            <div className="period-group" key={period}>
              <div className="panel-title">{periodLabel(period)}</div>
              <div className="stack" style={{ marginTop: 6 }}>
                {(grouped.get(period) ?? [])
                  .slice()
                  .sort((a, b) => a.position - b.position)
                  .map((step) => (
                    <StepView key={step.id} step={step} lookup={lookup} />
                  ))}
              </div>
            </div>
            ))}
        </div>
      )}

      {plan.pending_products.length > 0 && (
        <div>
          <div className="panel-sub">待确认产品（资料不足或有冲突，未安排步骤）</div>
          <ul className="small">
            {plan.pending_products.map((item, index) => (
              <li key={index}>
                {String(item.name ?? item.custom_name ?? "未命名产品")}：
                {String(item.reason ?? item.message ?? "缺少已批准来源")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.uncertainties.length > 0 && (
        <div>
          <div className="panel-sub">不确定性说明</div>
          <ul className="small">
            {plan.uncertainties.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="small muted">
        input_snapshot_hash：
        <span className="mono">{truncate(plan.input_snapshot_hash, 32)}</span>
      </div>
    </div>
  );
}

function CombinationNoteChoice({
  note,
  index,
  lookup,
  onChosen,
}: {
  note: CombinationNoteRecord;
  index: number;
  lookup: Map<string, Citation>;
  onChosen: (plan: RoutinePlan | null) => void;
}): JSX.Element {
  const toast = useToast();
  const [target, setTarget] = useState<string>("");
  const action = useAction<[("keep" | "space_out" | "remove_one")], Awaited<ReturnType<typeof postCombinationChoice>>>(
    (choice) =>
      postCombinationChoice({
        note_index: index,
        choice,
        owned_product_id: choice === "remove_one" ? target || null : null,
      }),
  );

  const run = async (choice: "keep" | "space_out" | "remove_one") => {
    const result = await action.run(choice);
    if (result) {
      toast.show(result.notice);
      onChosen(result.plan ?? null);
    }
  };

  return (
    <div className="step" data-testid="combination-note" data-note-index={index}>
      <div className="row tight">
        <Badge tone="warn">组合提示 #{index + 1}</Badge>
        {note.ingredient_inci && <Badge>{note.ingredient_inci}</Badge>}
        <Badge>{note.type}</Badge>
      </div>
      <p style={{ marginTop: 6 }}>{note.text}</p>
      {(note.product_names ?? []).length > 0 && (
        <div className="small muted">涉及产品：{(note.product_names ?? []).join("、")}</div>
      )}
      <div className="chips">
        <span className="small muted" style={{ alignSelf: "center" }}>
          依据来源：
        </span>
        {(note.citation_ids ?? []).map((citationId) => {
          const citation = lookup.get(citationId);
          return (
            <span className="chip" key={citationId} title={citation?.title ?? citationId}>
              {citation ? citation.title.replace(/[《》]/g, "").slice(0, 20) : `引用 #${citationId.slice(0, 8)}`}
            </span>
          );
        })}
        {(note.citation_ids ?? []).length === 0 && <span className="small muted">无引用（不会展示无来源结论）</span>}
      </div>
      <div className="row tight" style={{ marginTop: 8 }}>
        <select value={target} onChange={(event) => setTarget(event.target.value)} aria-label="选择要移除的产品">
          <option value="">（移除时选择产品）</option>
          {(note.owned_product_ids ?? []).map((productId, i) => (
            <option key={productId} value={productId}>
              {(note.product_names ?? [])[i] ?? productId}
            </option>
          ))}
        </select>
        {(["keep", "space_out", "remove_one"] as const).map((choice) => (
          <button
            key={choice}
            type="button"
            data-testid={COMBINATION_OPTION_TEST_IDS[choice]}
            className={choice === "keep" ? "" : "primary"}
            disabled={action.running}
            onClick={() => void run(choice)}
          >
            {combinationOptionLabel(choice)}
          </button>
        ))}
      </div>
      <p className="small muted">
        「保留」只记录你的选择，计划不变；「间隔」或「移除」会生成新草稿，仍需你显式接受。
      </p>
      <ActionFeedback error={action.error} />
      {action.result?.plan && <p className="small muted">已生成草稿 v{action.result.plan.version}。</p>}
    </div>
  );
}
