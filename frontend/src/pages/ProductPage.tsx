/**
 * /products/:ownedId 我的这件产品：版本、日期、到期未知说明、说明与来源、事件。
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  createUsageEvent,
  deleteUsageEvent,
  getOwnedProduct,
  listUsageEvents,
} from "../api/endpoints";
import type { OwnedProductDetail, UsageEventRecord } from "../api/types";
import { CitationDetail } from "../components/Citations";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  EmptyState,
  KeyValue,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDate, formatDateTime, fromDateTimeLocal } from "../lib/format";
import { lifecycleLabel, matchStatusLabel, usageLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

export function ProductPage(): JSX.Element {
  const { ownedId = "" } = useParams();
  const toast = useToast();
  const { refreshContext } = useSession();
  const product = useAsync<OwnedProductDetail>(() => getOwnedProduct(ownedId), {
    deps: [ownedId],
    enabled: ownedId.length > 0,
  });
  const events = useAsync(() => listUsageEvents(), { deps: [ownedId] });

  const [text, setText] = useState("");
  const [occurredAt, setOccurredAt] = useState("");
  const [eventType, setEventType] = useState<"positive" | "negative" | "neutral" | "uncertain">("negative");
  const [precision, setPrecision] = useState<"unknown" | "day" | "exact" | "approximate">("unknown");

  const create = useAction(() =>
    createUsageEvent({
      reported_text: text,
      owned_product_ids: [ownedId],
      occurred_at: fromDateTimeLocal(occurredAt),
      time_precision: precision,
      event_type: eventType,
    }),
  );
  const remove = useAction<[string], Awaited<ReturnType<typeof deleteUsageEvent>>>((eventId) =>
    deleteUsageEvent(eventId),
  );

  const submit = async () => {
    const result = await create.run();
    if (result) {
      toast.show(result.notice);
      setText("");
      setOccurredAt("");
      events.reload();
      void refreshContext();
      product.reload();
    }
  };

  const productEvents: UsageEventRecord[] =
    events.data?.events.filter((event) => event.owned_product_ids.includes(ownedId)) ?? [];

  return (
    <div className="stack">
      <Panel
        title="我的这件产品"
        subtitle={ownedId}
        actions={
          <>
            <button type="button" onClick={() => product.reload()}>
              刷新
            </button>
            <Link className="btn" to="/cabinet">
              返回美妆柜
            </Link>
          </>
        }
      >
        <AsyncBlock
          loading={product.loading}
          error={product.error}
          data={product.data}
          onRetry={product.reload}
          loadingLabel="加载产品实例…"
        >
          {(data) => (
            <div className="stack">
              <div className="row tight">
                <h2 style={{ margin: 0 }}>{data.custom_name}</h2>
                <Badge tone="accent">版本号 v{data.version}</Badge>
                <Badge tone={data.match_status === "matched" ? "ok" : "warn"}>
                  {matchStatusLabel(data.match_status)}
                </Badge>
                <Badge>{lifecycleLabel(data.lifecycle_status)}</Badge>
                <Badge tone={data.usage_status === "active" ? "ok" : "warn"}>
                  {usageLabel(data.usage_status)}
                </Badge>
                {data.review_flag && <Badge tone="warn">需关注</Badge>}
              </div>

              <KeyValue
                items={[
                  ["规格", data.size ?? "未填写"],
                  ["购买日期", formatDate(data.purchase_date)],
                  ["开封日期", formatDate(data.opened_date)],
                  ["包装/确认到期日", data.expiry_date ? formatDate(data.expiry_date) : "未记录"],
                  [
                    "实际采用到期",
                    <>
                      {formatDate(data.effective_expiry)}
                      {data.effective_expiry_source ? `（来源：${data.effective_expiry_source}）` : ""}
                    </>,
                  ],
                  ["开封后可用月数（PAO）", data.pao_months ? `${data.pao_months} 个月` : "未记录"],
                  ["成分资料来源", data.ingredient_source_status],
                  ["provenance", data.provenance],
                  ["创建 / 更新", `${formatDateTime(data.created_at, undefined)} / ${formatDateTime(data.updated_at)}`],
                ]}
              />

              {data.expiry_unknown_reason ? (
                <div className="state">
                  <strong>到期日期未知</strong>
                  <div>{data.expiry_unknown_reason}</div>
                  <div className="error-detail">
                    PAO 只在「开封日期」与「包装标注的 PAO 月数」都存在时才计算；类别不会用来猜测日期
                    （spec 第 6 节 / AC20）。
                  </div>
                </div>
              ) : (
                <Notice>实际失效由更保守的已知到期约束确定，不按产品类别猜测。</Notice>
              )}

              {data.expiry_assessment.candidates.length > 0 && (
                <div>
                  <div className="panel-sub">日期候选（用于确定更保守的实际到期）</div>
                  <ul className="small">
                    {data.expiry_assessment.candidates.map((candidate, index) => (
                      <li key={index}>
                        {candidate.label}：{formatDate(candidate.value)}（source={candidate.source}）
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="说明与来源" subtitle="只展示已批准且版本匹配的资料；资料缺失时如实说明">
        <AsyncBlock
          loading={product.loading}
          error={product.error}
          data={product.data}
          onRetry={product.reload}
        >
          {(data) => (
            <div className="stack">
              {data.knowledge && (
                <div className="row tight">
                  <Badge tone={data.knowledge.has_approved_sources ? "ok" : "warn"}>
                    {data.knowledge.has_approved_sources ? "存在已批准来源" : "缺少已批准来源"}
                  </Badge>
                  {data.knowledge.error_code && <Badge tone="warn">{data.knowledge.error_code}</Badge>}
                  {data.knowledge.message && <span className="small muted">{data.knowledge.message}</span>}
                </div>
              )}
              {data.sources.length === 0 ? (
                <EmptyState hint="资料不足的产品不会被自动安排进计划，也不会参与组合推理。">
                  这件产品暂无可展示的已批准来源。
                </EmptyState>
              ) : (
                <div className="stack">
                  {data.sources.map((citation) => (
                    <CitationDetail key={citation.citation_id} citation={citation} />
                  ))}
                </div>
              )}
              {!data.knowledge && (
                <Notice>这件产品未匹配到目录产品，因此没有产品级资料；它仍可作为你的个性化记录使用。</Notice>
              )}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel
        title="使用事件（用户报告）"
        subtitle="保存为你报告的体验，不是诊断结论，也不代表因果关系"
      >
        <div className="stack">
          <div className="row">
            <div className="field" style={{ flex: 1, minWidth: 240 }}>
              <label htmlFor="event-text">我报告的体验 *</label>
              <input
                id="event-text"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="例如：昨晚用了之后有点刺痛"
              />
            </div>
            <div className="field">
              <label htmlFor="event-type">类型</label>
              <select
                id="event-type"
                value={eventType}
                onChange={(event) => setEventType(event.target.value as typeof eventType)}
              >
                <option value="negative">负面体验</option>
                <option value="positive">正面体验</option>
                <option value="neutral">无明显变化</option>
                <option value="uncertain">不确定</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="event-time">发生时间（可留空）</label>
              <input
                id="event-time"
                type="datetime-local"
                value={occurredAt}
                onChange={(event) => setOccurredAt(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="event-precision">时间精度</label>
              <select
                id="event-precision"
                value={precision}
                onChange={(event) => setPrecision(event.target.value as typeof precision)}
              >
                <option value="unknown">未知</option>
                <option value="day">日期</option>
                <option value="exact">精确</option>
                <option value="approximate">大致</option>
              </select>
            </div>
            <button
              type="button"
              className="primary"
              disabled={create.running || text.trim().length === 0}
              onClick={() => void submit()}
            >
              {create.running ? "保存中…" : "保存事件"}
            </button>
          </div>
          <Notice>
            发生时间允许未知，不会自动填成今天。保存后如需复核，服务端会生成显式的复核询问，不会自动修改计划。
          </Notice>
          <ActionFeedback error={create.error} />
          {create.result?.review_prompt && (
            <div className="state">
              已生成复核询问：{create.result.review_prompt.question}
              <div className="row tight" style={{ marginTop: 6 }}>
                <Link className="btn" to="/routine">
                  去复核
                </Link>
              </div>
            </div>
          )}

          <AsyncBlock
            loading={events.loading}
            error={events.error}
            data={events.data}
            onRetry={events.reload}
            isEmpty={() => productEvents.length === 0}
            empty="这件产品还没有你报告的事件记录。"
          >
            {() => (
              <div className="stack">
                {productEvents.map((event) => (
                  <div className="step" key={event.id}>
                    <div className="row tight" style={{ justifyContent: "space-between" }}>
                      <span>
                        <Badge tone={event.event_type === "negative" ? "warn" : "ok"}>
                          {event.event_type ?? "未标注"}
                        </Badge>{" "}
                        {event.reported_text}
                      </span>
                      <button
                        type="button"
                        className="danger"
                        disabled={remove.running}
                        onClick={() => {
                          void (async () => {
                            const result = await remove.run(event.id);
                            if (result) {
                              toast.show(result.notice);
                              events.reload();
                              void refreshContext();
                            }
                          })();
                        }}
                      >
                        删除此事件
                      </button>
                    </div>
                    <div className="small muted">
                      发生时间：{formatDateTime(event.occurred_at)}（精度：{event.time_precision}） · 记录时间：
                      {formatDateTime(event.created_at)} · provenance：{event.provenance}
                    </div>
                    {event.ingredient_snapshot.length > 0 && (
                      <div className="small muted">
                        当时提取到的成分：{event.ingredient_snapshot.map((item) => item.ingredients.join("/")).join("、")}
                      </div>
                    )}
                    <div className="notice">{event.disclaimer}</div>
                  </div>
                ))}
                <ActionFeedback error={remove.error} />
                <Notice>{events.data?.notice}</Notice>
              </div>
            )}
          </AsyncBlock>
        </div>
      </Panel>
    </div>
  );
}
