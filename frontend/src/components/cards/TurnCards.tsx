/**
 * 对话标准输出（TurnOutput）的结构化卡片渲染。
 *
 * cards / pending_actions 是后端定义的 discriminated union（backend/app/schemas/turn.py），
 * 这里为每种 type 提供真实的结构化渲染，而不是把 answer 当一堵文字墙。
 * 所有涉及成分/服务的措辞都逐字复用后端返回的 statement / text / notice，
 * 前端不新增任何因果或功效断言。
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { acceptRoutine, reviewDecision, submitHandoff } from "../../api/endpoints";
import { describeError } from "../../api/client";
import type {
  AtlasCard,
  AuditSummaryCard,
  Citation,
  CombinationNoteCard,
  EnvironmentCard,
  ErrorCard,
  ImportCandidatesCard,
  IngredientCard,
  MemoryRecordCard,
  OwnedProductCard,
  PendingAction,
  ProactiveMessageCard,
  ReviewDecisionResponse,
  ReviewPromptCard,
  RoutineDraftCard,
  RoutinePlanCard,
  ServiceStatusCard,
  StepOut,
  TicketCard,
  TravelChecklistCard,
  TurnCard,
} from "../../api/types";
import { formatDate, formatDateTime, formatValue } from "../../lib/format";
import {
  PENDING_ACTION_LABELS,
  REVIEW_OPTION_TEST_IDS,
  combinationOptionLabel,
  lifecycleLabel,
  periodLabel,
  planStatusLabel,
  reviewOptionLabel,
  ticketStatusLabel,
  usageLabel,
} from "../../lib/labels";
import { useAction } from "../../state/useAsync";
import { CitationChips } from "../Citations";
import { ActionFeedback, Badge, Notice, useToast } from "../ui";

export interface TurnRendererProps {
  cards: TurnCard[];
  pendingActions: PendingAction[];
  citations: Citation[];
  /** 确认动作成功后刷新相关数据。 */
  onChanged?: () => void;
  /** 是否展示 memory_changes（对话里由 ChatPage 渲染）。 */
  compact?: boolean;
}

export function citationLookup(citations: Citation[]): Map<string, Citation> {
  const map = new Map<string, Citation>();
  for (const citation of citations) {
    map.set(citation.citation_id, citation);
  }
  return map;
}

export function TurnCards({
  cards,
  pendingActions,
  citations,
  onChanged,
  compact = false,
}: TurnRendererProps): JSX.Element {
  const lookup = citationLookup(citations);
  return (
    <div className="turn-cards">
      {cards.map((card, index) => (
        <div key={`${card.type}-${index}`} data-testid={`chat-card-${card.type}`}>
          <TurnCardView card={card} lookup={lookup} onChanged={onChanged} compact={compact} />
        </div>
      ))}
      {pendingActions.length > 0 && (
        <PendingActions actions={pendingActions} onChanged={onChanged} />
      )}
    </div>
  );
}

function TurnCardView({
  card,
  lookup,
  onChanged,
  compact,
}: {
  card: TurnCard;
  lookup: Map<string, Citation>;
  onChanged?: () => void;
  compact: boolean;
}): JSX.Element {
  switch (card.type) {
    case "routine_draft":
      return <RoutineDraftCardView card={card} compact={compact} />;
    case "routine_plan":
      return <RoutinePlanCardView card={card} lookup={lookup} />;
    case "combination_note":
      return <CombinationNoteCardView card={card} lookup={lookup} onChanged={onChanged} />;
    case "import_candidates":
      return <ImportCandidatesCardView card={card} />;
    case "owned_product":
      return <OwnedProductCardView card={card} />;
    case "memory_record":
      return <MemoryRecordCardView card={card} onChanged={onChanged} />;
    case "review_prompt":
      return <ReviewPromptCardView card={card} onChanged={onChanged} />;
    case "service_ticket":
      return <TicketCardView card={card} />;
    case "service_status":
      return <ServiceStatusCardView card={card} />;
    case "environment":
      return <EnvironmentCardView card={card} />;
    case "ingredient":
      return <IngredientCardView card={card} />;
    case "ingredient_atlas":
      return <AtlasCardView card={card} />;
    case "audit_summary":
      return <AuditSummaryCardView card={card} />;
    case "proactive_message":
      return <ProactiveMessageCardView card={card} />;
    case "travel_checklist":
      return <TravelChecklistCardView card={card} />;
    case "error":
      return <ErrorCardView card={card} />;
    default: {
      const unknown = card as { type: string };
      return (
        <div className="turn-card">
          <Badge tone="warn">未识别的卡片类型</Badge>
          <p className="small muted">
            后端返回了前端未实现的卡片类型「{unknown.type}」。原始内容：
            {JSON.stringify(card)}
          </p>
        </div>
      );
    }
  }
}

// --- 各卡片 ----------------------------------------------------------------

function RoutineDraftCardView({
  card,
  compact,
}: {
  card: RoutineDraftCard;
  compact: boolean;
}): JSX.Element {
  const navigate = useNavigate();
  return (
    <div className="turn-card accent">
      <div className="row tight">
        <Badge tone="accent">计划草稿 v{card.version}</Badge>
        <Badge>{planStatusLabel(card.status)}</Badge>
        <Badge>步骤 {card.step_count}</Badge>
        {card.pending_count > 0 && <Badge tone="warn">待确认产品 {card.pending_count}</Badge>}
        {card.combination_note_count > 0 && (
          <Badge tone="warn">组合提示 {card.combination_note_count}</Badge>
        )}
        {card.question_count > 0 && <Badge>待回答 {card.question_count}</Badge>}
      </div>
      {card.diff_summary && <p style={{ marginTop: 6 }}>{card.diff_summary}</p>}
      <p className="small muted">
        草稿不会自动生效；接受后才成为当前版本（接受动作由服务端校验 expected_version）。
      </p>
      {!compact && (
        <div className="row tight">
          <button type="button" onClick={() => navigate("/routine")}>
            查看早晚计划与差异
          </button>
        </div>
      )}
    </div>
  );
}

const PERIOD_ORDER = ["morning", "both", "evening", "as_needed", "weekly", "unknown"];

export function RoutinePlanCardView({
  card,
  lookup,
}: {
  card: RoutinePlanCard;
  lookup: Map<string, Citation>;
}): JSX.Element {
  const grouped = new Map<string, StepOut[]>();
  for (const step of card.steps) {
    const list = grouped.get(step.period) ?? [];
    list.push(step);
    grouped.set(step.period, list);
  }
  const periods = [...grouped.keys()].sort(
    (a, b) => PERIOD_ORDER.indexOf(a) - PERIOD_ORDER.indexOf(b),
  );
  return (
    <div className="turn-card accent">
      <div className="row tight">
        <Badge tone="accent">计划 v{card.version}</Badge>
        <Badge>{planStatusLabel(card.status)}</Badge>
        <Badge>步骤 {card.steps.length}</Badge>
      </div>
      <div className="stack" style={{ marginTop: 8 }}>
        {periods.map((period) => (
          <div className="period-group" key={period}>
            <div className="panel-title">{periodLabel(period)}</div>
            <div className="stack" style={{ marginTop: 6 }}>
              {(grouped.get(period) ?? [])
                .slice()
                .sort((a, b) => a.position - b.position)
                .map((step, index) => (
                  <StepView
                    key={`${period}-${index}-${step.label}`}
                    step={step}
                    lookup={lookup}
                  />
                ))}
            </div>
          </div>
        ))}
      </div>
      {card.pending_products.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="panel-sub">
            待确认产品（资料不足或有冲突，未安排步骤，也未参与组合推理）
          </div>
          <ul className="small">
            {card.pending_products.map((item, index) => (
              <li key={index}>{describePendingProduct(item)}</li>
            ))}
          </ul>
        </div>
      )}
      {card.uncertainties.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="panel-sub">不确定性说明</div>
          <ul className="small">
            {card.uncertainties.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function StepView({
  step,
  lookup,
}: {
  step: StepOut;
  lookup: Map<string, Citation>;
}): JSX.Element {
  return (
    <div className="step" data-testid="routine-step" data-step-label={step.label}>
      <div className="step-head">
        <span className="step-label">
          {step.position}. {step.label}
        </span>
        {step.frequency && <Badge>{step.frequency}</Badge>}
        {step.review_flag && <Badge tone="warn">此前的负面反馈复核标记</Badge>}
        {step.is_general_advice && <Badge tone="warn">经审核的一般建议（非产品专属）</Badge>}
      </div>
      <p style={{ margin: "6px 0 0" }}>{step.instruction}</p>
      <div className="step-basis">依据：{step.basis}</div>
      {step.review_note && <div className="step-basis">复核说明：{step.review_note}</div>}
      <CitationChips citationIds={step.citation_ids} lookup={lookup} />
    </div>
  );
}

export function CombinationNoteCardView({
  card,
  lookup,
  onChanged,
}: {
  card: CombinationNoteCard;
  lookup: Map<string, Citation>;
  onChanged?: () => void;
}): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="warn">组合适用性提示</Badge>
        {card.ingredient_inci && <Badge>{card.ingredient_inci}</Badge>}
        <Badge tone={card.decided_by_system ? "error" : "ok"}>
          {card.decided_by_system ? "系统已代你决定（异常）" : "由你自己决定"}
        </Badge>
      </div>
      <p style={{ marginTop: 6 }}>{card.text}</p>
      <CitationChips citationIds={card.citation_ids} lookup={lookup} label="依据来源" />
      <p className="small muted" style={{ marginTop: 6 }}>
        可选项：{card.options.map((option) => combinationOptionLabel(option)).join(" / ")}
        。选择「间隔」或「移除」会生成新的计划草稿，仍需你在计划页显式接受。
      </p>
      <div className="row tight" style={{ marginTop: 6 }}>
        <a className="btn" href="/routine">
          到计划页选择保留 / 间隔 / 移除
        </a>
        {onChanged && (
          <span className="small muted">（对话中的组合提示不会自动改计划）</span>
        )}
      </div>
    </div>
  );
}

function ImportCandidatesCardView({ card }: { card: ImportCandidatesCard }): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">导入候选 {card.candidate_count} 件</Badge>
        <Badge>{card.status}</Badge>
        <Badge tone="mock">识别模式：{card.provider_mode}</Badge>
        {card.low_confidence && <Badge tone="warn">存在低置信候选</Badge>}
      </div>
      <p className="small" style={{ marginTop: 6 }}>
        {card.notice}
      </p>
      <div className="row tight">
        <a className="btn" href={`/imports/${card.entity_id}`}>
          查看识别结果并确认入柜
        </a>
      </div>
    </div>
  );
}

function OwnedProductCardView({ card }: { card: OwnedProductCard }): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">{card.name}</Badge>
        <Badge>{lifecycleLabel(card.lifecycle_status)}</Badge>
        <Badge>{usageLabel(card.usage_status)}</Badge>
        <Badge tone={card.ingredient_source_status === "available" ? "ok" : "warn"}>
          成分资料：{card.ingredient_source_status}
        </Badge>
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>
        到期：{formatDate(card.effective_expiry)}
        {card.expiry_unknown_reason ? `（${card.expiry_unknown_reason}）` : ""}
      </div>
      <div className="row tight">
        <a className="btn" href={`/products/${card.entity_id}`}>
          打开我的这件产品
        </a>
      </div>
    </div>
  );
}

function MemoryRecordCardView({
  card,
  onChanged,
}: {
  card: MemoryRecordCard;
  onChanged?: () => void;
}): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">记忆：{card.label ?? card.key}</Badge>
        <Badge>{card.kind}</Badge>
        <Badge tone={card.status === "active" ? "ok" : "warn"}>{card.status}</Badge>
        {card.requires_confirmation && <Badge tone="warn">需要你确认</Badge>}
      </div>
      <div className="small" style={{ marginTop: 6 }}>
        值：{formatValue(card.value)}
        {card.provenance_type ? ` · 来源类型：${card.provenance_type}` : ""}
      </div>
      <div className="row tight">
        <a className="btn" href="/memory">
          到记忆页修改或删除
        </a>
        {onChanged && (
          <button type="button" onClick={onChanged}>
            刷新
          </button>
        )}
      </div>
    </div>
  );
}

function ReviewPromptCardView({
  card,
  onChanged,
}: {
  card: ReviewPromptCard;
  onChanged?: () => void;
}): JSX.Element {
  const [note, setNote] = useState("");
  const toast = useToast();
  const action = useAction<[("pause" | "keep" | "adjust")], ReviewDecisionResponse>(
    (choice) =>
      reviewDecision(card.entity_id, {
        action: choice,
        expected_version: card.plan_version,
        note: note || null,
      }),
  );

  const run = async (choice: "pause" | "keep" | "adjust") => {
    const result = await action.run(choice);
    if (result) {
      toast.show(result.message ?? result.notice);
      onChanged?.();
    }
  };

  return (
    <div className="turn-card accent">
      <div className="row tight">
        <Badge tone="warn">复核询问</Badge>
        {card.plan_version !== null && <Badge>计划 v{card.plan_version}</Badge>}
      </div>
      <p style={{ marginTop: 6 }}>{card.question}</p>
      <input
        type="text"
        placeholder="补充说明（可选）"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        style={{ marginBottom: 6 }}
      />
      <div className="row tight">
        {(card.options.length > 0 ? card.options : ["pause", "keep", "adjust"]).map((option) => (
          <button
            key={option}
            type="button"
            data-testid={REVIEW_OPTION_TEST_IDS[option]}
            className={option === "pause" ? "primary" : ""}
            disabled={action.running}
            onClick={() => void run(option as "pause" | "keep" | "adjust")}
          >
            {reviewOptionLabel(option)}
          </button>
        ))}
      </div>
      {action.running && <p className="small muted">提交中…</p>}
      <ActionFeedback error={action.error} />
      <p className="small muted">
        负面反馈只会生成复核询问，不会自动暂停产品或修改计划；选择「暂停」会生成新草稿，仍需你接受。
      </p>
    </div>
  );
}

function TicketCardView({ card }: { card: TicketCard }): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">工单</Badge>
        <Badge>{ticketStatusLabel(card.status)}</Badge>
        <Badge tone="mock">适配器：{card.adapter_mode}</Badge>
      </div>
      {card.next_action && <p className="small">下一步：{card.next_action}</p>}
      {card.notice && <Notice>{card.notice}</Notice>}
      <div className="row tight">
        <a className="btn" href={`/service`}>
          打开我的工单
        </a>
        <a className="btn" href={`/staff/tickets/${card.entity_id}`}>
          演示客服视图
        </a>
      </div>
    </div>
  );
}

function ServiceStatusCardView({ card }: { card: ServiceStatusCard }): JSX.Element {
  if (!card.found) {
    return (
      <div className="turn-card">
        <Badge tone="warn">未找到工单</Badge>
        <p className="small muted" style={{ marginTop: 6 }}>
          没有查到工单记录。系统不会编造进度、承诺或退款结果；如需新建，请先预览交接摘要并确认提交。
        </p>
        <div className="row tight">
          <a className="btn" href="/service">
            去创建交接草稿
          </a>
        </div>
      </div>
    );
  }
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">工单状态</Badge>
        <Badge>{card.status ? ticketStatusLabel(card.status) : "未知"}</Badge>
        <Badge>时间线 {card.timeline_count} 条</Badge>
      </div>
      {card.next_action && <p className="small">下一步：{card.next_action}</p>}
      {card.ticket_id && (
        <div className="row tight">
          <a className="btn" href="/service">
            查看工单与时间线
          </a>
        </div>
      )}
    </div>
  );
}

function metricsSummary(metrics: Record<string, unknown>): string {
  const parts: string[] = [];
  const push = (label: string, key: string, unit = "") => {
    const value = metrics[key];
    if (value !== undefined && value !== null) {
      parts.push(`${label} ${String(value)}${unit}`);
    }
  };
  push("气温", "temperature_c", "°C");
  push("湿度", "relative_humidity", "%");
  push("风速", "wind_speed_ms", " m/s");
  push("紫外线", "uv_index");
  push("降水", "precipitation_mm", " mm");
  push("天气", "condition");
  return parts.length > 0 ? parts.join(" · ") : "指标缺失";
}

function EnvironmentCardView({ card }: { card: EnvironmentCard }): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">{card.city_name}</Badge>
        <Badge>{card.kind === "current" ? "当前" : "预报"}</Badge>
        <Badge tone="mock">模式：{card.mode}</Badge>
        <Badge tone={card.quality === "ok" ? "ok" : "warn"}>质量：{card.quality}</Badge>
      </div>
      <p className="small" style={{ marginTop: 6 }}>
        {metricsSummary(card.metrics)}
      </p>
      <div className="small muted">
        数据时间：{formatDateTime(card.issued_at)} · 有效期至：{formatDateTime(card.valid_to)}
      </div>
      {card.missing_fields.length > 0 && (
        <p className="small muted">缺失字段：{card.missing_fields.join("、")}</p>
      )}
      {card.notice && <Notice>{card.notice}</Notice>}
      <div className="row tight">
        <a className="btn" href="/environment">
          查看来源与更新时间
        </a>
      </div>
    </div>
  );
}

function IngredientCardView({ card }: { card: IngredientCard }): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">{card.common_name}</Badge>
        <Badge>{card.inci_name}</Badge>
        <Badge tone={card.data_status === "approved" ? "ok" : "warn"}>{card.data_status}</Badge>
      </div>
      {card.data_note && <p className="small">{card.data_note}</p>}
      <div className="row tight">
        <a className="btn" href={`/ingredients/atlas#${card.entity_id}`}>
          在图鉴中查看详情与来源
        </a>
      </div>
    </div>
  );
}

function AtlasCardView({ card }: { card: AtlasCard }): JSX.Element {
  return (
    <div className="turn-card accent">
      <div className="row tight">
        <Badge tone="accent">成分图鉴</Badge>
        {card.version !== null && <Badge>版本 {card.version}</Badge>}
        <Badge>卡片 {card.card_count}</Badge>
        <Badge tone="warn">样本不足 {card.below_threshold_count}</Badge>
        <Badge tone="warn">待审核 {card.pending_count}</Badge>
      </div>
      <Notice>{card.notice}</Notice>
      <div className="row tight">
        <a className="btn primary" href="/ingredients/atlas">
          打开成分图鉴
        </a>
      </div>
    </div>
  );
}

function AuditSummaryCardView({ card }: { card: AuditSummaryCard }): JSX.Element {
  return (
    <div className="turn-card">
      <Badge tone="accent">审计摘要</Badge>
      <p style={{ marginTop: 6 }}>{card.headline}</p>
      {card.items.length > 0 && (
        <ul className="small">
          {card.items.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ProactiveMessageCardView({ card }: { card: ProactiveMessageCard }): JSX.Element {
  return (
    <div className="turn-card">
      <div className="row tight">
        <Badge tone="accent">主动服务</Badge>
        <Badge>{card.decision_outcome}</Badge>
        {card.channel && <Badge>{card.channel}</Badge>}
      </div>
      <strong style={{ display: "block", marginTop: 6 }}>{card.title}</strong>
      <p>{card.body}</p>
      {card.reason_codes.length > 0 && (
        <p className="small muted">触发原因：{card.reason_codes.join("、")}</p>
      )}
      <div className="row tight">
        <a className="btn" href="/inbox">
          到收件箱处理
        </a>
      </div>
    </div>
  );
}

function TravelChecklistCardView({ card }: { card: TravelChecklistCard }): JSX.Element {
  return (
    <div className="turn-card">
      <Badge tone="accent">出行清单</Badge>
      <strong style={{ display: "block", marginTop: 6 }}>{card.title}</strong>
      <ul className="small">
        {card.items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
      {card.unknown_days.length > 0 && (
        <p className="small muted">
          预报未覆盖的日期（显示为未知，不伪造天气）：{card.unknown_days.join("、")}
        </p>
      )}
      {card.notice && <Notice>{card.notice}</Notice>}
    </div>
  );
}

function ErrorCardView({ card }: { card: ErrorCard }): JSX.Element {
  return (
    <div className="turn-card error">
      <div className="row tight">
        <Badge tone="error">错误 {card.code}</Badge>
        <Badge tone={card.retryable ? "warn" : "default"}>
          {card.retryable ? "可重试" : "不可重试"}
        </Badge>
      </div>
      <p style={{ marginTop: 6 }}>{card.message}</p>
      {card.manual_path && <p className="small muted">手动路径：{card.manual_path}</p>}
    </div>
  );
}

// --- pending_actions -------------------------------------------------------

/**
 * pending_actions 渲染为按钮：
 * - accept_routine -> POST /routines/{entity_id}/accept（带 expected_version）
 * - submit_handoff -> POST /handoffs/{entity_id}/submit
 * - 其余跳转到相关页面
 * 确认动作成功后调用 onChanged 刷新相关数据。
 */
export function PendingActions({
  actions,
  onChanged,
}: {
  actions: PendingAction[];
  onChanged?: () => void;
}): JSX.Element {
  const navigate = useNavigate();
  const toast = useToast();
  const [busyIndex, setBusyIndex] = useState<number | null>(null);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);

  const runAction = async (action: PendingAction, index: number) => {
    setBusyIndex(index);
    setError(null);
    try {
      if (action.type === "accept_routine") {
        if (!action.entity_id) {
          throw new Error("缺少计划 ID，无法接受。");
        }
        const result = await acceptRoutine(action.entity_id, action.expected_version);
        toast.show(result.notice);
        onChanged?.();
      } else if (action.type === "submit_handoff") {
        if (!action.entity_id) {
          throw new Error("缺少工单 ID，无法提交。");
        }
        const result = await submitHandoff(action.entity_id, {
          expected_version: action.expected_version,
        });
        toast.show(result.notice);
        onChanged?.();
      } else {
        navigate(pendingActionTarget(action));
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusyIndex(null);
    }
  };

  return (
    <div>
      <div className="pending-actions">
        {actions.map((action, index) => (
          <button
            key={`${action.type}-${index}`}
            type="button"
            data-testid={`chat-pending-action-${action.type}`}
            className={action.type === "accept_routine" ? "primary" : ""}
            disabled={busyIndex !== null || Boolean(action.blocked_reason)}
            title={action.blocked_reason ?? PENDING_ACTION_LABELS[action.type] ?? action.type}
            onClick={() => void runAction(action, index)}
          >
            {busyIndex === index ? "处理中…" : action.label}
          </button>
        ))}
      </div>
      {actions.some((action) => action.blocked_reason) && (
        <p className="small muted">
          {actions
            .filter((action) => action.blocked_reason)
            .map((action) => `${action.label}：${action.blocked_reason}`)
            .join("；")}
        </p>
      )}
      {error && <ActionFeedback error={error} />}
      <p className="small muted" style={{ marginTop: 4 }}>
        这些按钮由你显式确认；模型不能自行批准写操作。类型：
        {actions.map((action) => action.type).join("、")}
      </p>
    </div>
  );
}

export function pendingActionTarget(action: PendingAction): string {
  switch (action.type) {
    case "confirm_import":
      return action.entity_id ? `/imports/${action.entity_id}` : "/cabinet";
    case "confirm_memory":
      return "/memory";
    case "review_routine":
      return "/routine";
    case "add_owned_product":
      return "/cabinet";
    case "open_atlas":
      return "/ingredients/atlas";
    case "provide_missing_info":
      return "/chat";
    default:
      return "/";
  }
}

function describePendingProduct(item: Record<string, unknown>): string {
  const name = item.name ?? item.custom_name ?? item.label ?? "未命名产品";
  const reason = item.reason ?? item.message ?? item.status ?? "资料不足或有冲突";
  return `${String(name)}：${String(reason)}`;
}
