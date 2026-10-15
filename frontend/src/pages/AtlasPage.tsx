/**
 * /ingredients/atlas 成分图鉴。
 *
 * 强制约束（spec 8.1）：只展示后端返回的内容；个人反馈只作为「关联统计」，
 * 逐字复用 user_signal.statement / causality_notice / notice / disclaimer，
 * 前端绝不新增「过敏 / 导致 / 避免」这类断言。data_status=insufficient 的卡片显示
 * 「暂无充分信息」，不展示任何功效或致敏性内容。
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { getAtlas, postIngredientFeedback } from "../api/endpoints";
import type { AtlasCardData, AtlasEffectNote, AtlasPayload } from "../api/types";
import { CitationDetail } from "../components/Citations";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  EmptyState,
  KeyValue,
  Notice,
  Panel,
  Stat,
  useToast,
} from "../components/ui";
import { formatDateTime } from "../lib/format";
import { atlasDataStatusLabel, droppedReasonLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

const LIFE_EXTENSION_NOTICE = "此延伸基于已审核来源，非个人诊断";

export function AtlasPage(): JSX.Element {
  const { lastLoadedAt } = useSession();
  const [minEvents, setMinEvents] = useState<number | "">("");
  const atlas = useAsync<AtlasPayload>(
    () => getAtlas(minEvents === "" ? undefined : { min_events: minEvents }),
    { deps: [lastLoadedAt, minEvents] },
  );

  return (
    <div className="stack">
      <Panel
        title="成分图鉴"
        subtitle="用户主动查看时生成；不自动推送，也不替代专业建议"
        actions={
          <>
            <div className="field">
              <label htmlFor="min-events">最小样本（min_events）</label>
              <input
                id="min-events"
                type="number"
                min={1}
                max={50}
                value={minEvents}
                placeholder="默认 3"
                onChange={(event) =>
                  setMinEvents(event.target.value === "" ? "" : Number(event.target.value))
                }
              />
            </div>
            <button type="button" data-testid="atlas-generate" onClick={() => atlas.reload()}>
              查看 / 生成图鉴
            </button>
          </>
        }
      >
        <Notice tone="mock">
          演示数据：成分-功效/致敏性映射来自演示种子里的「已审核来源」（含虚构 DEMO 成分资料）；
          个人信号只是关联统计。前端不生成任何成分结论。
        </Notice>
        {atlas.data && (
          <>
            <div className="stat" style={{ marginTop: 8 }}>
              <Stat label="图鉴卡片" value={atlas.data.stats.card_count} />
              <Stat label="样本不足" value={atlas.data.stats.below_threshold_count} />
              <Stat label="待审核" value={atlas.data.stats.pending_count} />
              <Stat label="已审核来源卡片" value={atlas.data.stats.approved_card_count} />
              <Stat label="暂无充分信息" value={atlas.data.stats.insufficient_card_count} />
            </div>
            <KeyValue
              items={[
                ["生成时间", formatDateTime(atlas.data.generated_at)],
                ["视图版本", atlas.data.version === null ? "未持久化" : `v${atlas.data.version}`],
                ["mode", atlas.data.mode],
                ["最小样本", `${atlas.data.min_events} 次关联反馈`],
                ["关联信号条数", `${atlas.data.signal_ids.length}`],
              ]}
            />
            <Notice>{atlas.data.notice}</Notice>
            <Notice>{atlas.data.signal_wording_notice}</Notice>
            <Notice>{atlas.data.disclaimer}</Notice>
          </>
        )}
      </Panel>

      <Panel title="图鉴卡片" subtitle="每张卡片包含：名称、功效、致敏性标注、你的关联事件数、生活延伸、不确定性、声明">
        <AsyncBlock
          loading={atlas.loading}
          error={atlas.error}
          data={atlas.data}
          onRetry={atlas.reload}
          loadingLabel="正在生成图鉴…"
          isEmpty={(data) => data.cards.length === 0}
          empty="暂无可生成的图鉴卡片：需要同一成分关联的反馈事件达到最小样本，且卡片必填项完整。"
        >
          {(data) => (
            <div className="stack">
              {data.cards.map((card) => (
                <AtlasCardView key={card.ingredient_id} card={card} />
              ))}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="样本不足（未生成个人化信号）" subtitle="同一成分关联反馈事件未达到 min_events">
        <AsyncBlock
          loading={atlas.loading}
          error={atlas.error}
          data={atlas.data}
          onRetry={atlas.reload}
          isEmpty={(data) => data.below_threshold.length === 0}
          empty="没有样本不足的成分。"
        >
          {(data) => (
            <table className="table" data-testid="atlas-below-threshold">
              <thead>
                <tr>
                  <th>成分（通俗名 / INCI）</th>
                  <th>正面关联</th>
                  <th>负面关联</th>
                  <th>最小样本</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {data.below_threshold.map((entry) => (
                  <tr key={entry.ingredient_id}>
                    <td>
                      {entry.common_name} / {entry.inci_name}
                    </td>
                    <td>{entry.positive_count}</td>
                    <td>{entry.negative_count}</td>
                    <td>{entry.min_events}</td>
                    <td className="small">{entry.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="待审核（卡片未生成）" subtitle="必填项缺失或来源冲突时进入 pending，不展示推断内容">
        <AsyncBlock
          loading={atlas.loading}
          error={atlas.error}
          data={atlas.data}
          onRetry={atlas.reload}
          isEmpty={(data) => data.pending.length === 0}
          empty="没有待审核的成分。"
        >
          {(data) => (
            <table className="table">
              <thead>
                <tr>
                  <th>成分（通俗名 / INCI）</th>
                  <th>原因</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {data.pending.map((entry) => (
                  <tr key={entry.ingredient_id}>
                    <td>
                      {entry.common_name} / {entry.inci_name}
                    </td>
                    <td>{entry.reason ?? "必填项缺失或来源冲突"}</td>
                    <td className="small">{entry.message ?? "信息存在冲突，待审核或不展示。"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </AsyncBlock>
      </Panel>

      <Panel
        title="未展示：无已审核来源支持"
        subtitle="生活场景延伸审计列表（dropped_life_extensions）——不会由模型补全"
      >
        <AsyncBlock
          loading={atlas.loading}
          error={atlas.error}
          data={atlas.data}
          onRetry={atlas.reload}
          isEmpty={(data) => data.dropped_life_extensions.length === 0}
          empty="没有被丢弃的生活场景延伸。"
        >
          {(data) => (
            <ul className="audit-list" data-testid="atlas-dropped-extensions">
              {data.dropped_life_extensions.map((entry, index) => (
                <li key={`${entry.ingredient_id}-${index}`}>
                  「{entry.text}」（成分 {entry.inci_name}）—
                  未展示：无已审核来源支持（reason={droppedReasonLabel(entry.reason)}）
                </li>
              ))}
            </ul>
          )}
        </AsyncBlock>
        <Notice>
          生活场景延伸必须满足：有已审核来源支持、与成分已知功效/致敏性直接相关、不构成医疗诊断或购买推荐，
          并标注「{LIFE_EXTENSION_NOTICE}」。
        </Notice>
      </Panel>

      <Panel title="我在图鉴中的补充陈述" subtitle="POST /ingredients/feedback（与统计信号分开显示）">
        <StatementForm
          cards={atlas.data?.cards ?? []}
          records={atlas.data?.ingredient_feedback ?? []}
          onCreated={() => atlas.reload()}
        />
      </Panel>

      <p className="small muted">
        相关页面：<Link to="/memory">记忆与反馈</Link> · <Link to="/routine">计划</Link> ·{" "}
        <Link to="/chat">对话（说「看看我的成分图鉴」）</Link>
      </p>
    </div>
  );
}

function AtlasCardView({ card }: { card: AtlasCardData }): JSX.Element {
  const insufficient = card.data_status === "insufficient";
  const pendingReview = card.data_status === "pending_review";
  return (
    <div className="step" id={card.ingredient_id} data-testid="atlas-card" data-common-name={card.common_name}>
      <div className="row tight">
        <span style={{ fontWeight: 600 }}>
          {card.common_name} / {card.inci_name}
        </span>
        <span data-testid="atlas-card-status">
          <Badge tone={insufficient ? "warn" : pendingReview ? "warn" : "ok"}>
            {atlasDataStatusLabel(card.data_status)}
          </Badge>
        </span>
        {card.is_demo && <Badge tone="mock">DEMO 演示成分资料</Badge>}
        {card.approval_status && <Badge>审批：{card.approval_status}</Badge>}
      </div>

      {card.data_note && <p className="small">{card.data_note}</p>}

      {insufficient ? (
        <div className="state">
          <strong>「暂无充分信息」</strong>
          <div>
            该成分缺少已审核来源，因此不展示功效、致敏性或生活场景延伸；系统不会自行补全，也不会用相似成分
            的内容替代。
          </div>
        </div>
      ) : pendingReview ? (
        <div className="state">
          <strong>信息存在冲突，待审核</strong>
          <div>来源之间存在冲突，系统不选边，也不展示确定性建议。</div>
        </div>
      ) : (
        <>
          <div style={{ marginTop: 8 }}>
            <div className="panel-sub">已知功效（有来源时）</div>
            {card.known_effects.length === 0 ? (
              <p className="small muted">后端未返回已知功效。</p>
            ) : (
              card.known_effects.map((effect, index) => (
                <EffectRow key={index} effect={effect} />
              ))
            )}
          </div>

          <div style={{ marginTop: 8 }}>
            <div className="panel-sub">致敏性标注（有来源时）</div>
            {!card.irritancy.has_source ? (
              <p className="small muted">
                该成分暂无已审核的致敏性来源，因此不展示致敏性标注（不由模型推断）。
              </p>
            ) : (
              <>
                <div className="row tight">
                  <Badge tone={card.irritancy.level === "unknown" ? "warn" : "accent"}>
                    致敏性等级：{card.irritancy.level}
                  </Badge>
                </div>
                {card.irritancy.notes.map((note, index) => (
                  <EffectRow key={index} effect={note} />
                ))}
              </>
            )}
          </div>
        </>
      )}

      <div style={{ marginTop: 8 }}>
        <div className="panel-sub">你的反馈关联</div>
        {card.user_signal === null ? (
          <p className="small muted">该成分没有达到最小样本的个人信号。</p>
        ) : (
          <>
            <div className="row tight">
              <Badge tone="ok">正面关联 {card.user_signal.positive_count} 次</Badge>
              <Badge tone="warn">负面关联 {card.user_signal.negative_count} 次</Badge>
              <Badge>合计 {card.user_signal.total_count} 次</Badge>
            </div>
            {/* 逐字展示后端给出的措辞，禁止改写为「过敏/导致/避免」 */}
            <p className="assoc-wording">{card.user_signal.statement}</p>
            <p className="small muted">{card.user_signal.causality_notice}</p>
            {(card.user_signal.event_refs ?? []).length > 0 && (
              <details>
                <summary className="small muted">
                  关联事件引用 {card.user_signal.event_refs?.length ?? 0} 条（点击展开）
                </summary>
                <ul className="small mono">
                  {(card.user_signal.event_refs ?? []).map((ref) => (
                    <li key={ref}>{ref}</li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </div>

      <div style={{ marginTop: 8 }}>
        <div className="panel-sub">生活场景延伸（保养习惯 / 饮食留意）</div>
        {card.life_extensions.length === 0 ? (
          <p className="small muted">
            该成分没有已审核来源支持的生活场景延伸（没有来源支持的延伸不会展示，也不由模型补全）。
          </p>
        ) : (
          card.life_extensions.map((extension, index) => (
            <div className="citation-box" key={index}>
              <div>{extension.text}</div>
              <div className="small muted">{LIFE_EXTENSION_NOTICE}</div>
              {extension.citation && <CitationDetail citation={extension.citation} />}
            </div>
          ))
        )}
      </div>

      <div style={{ marginTop: 8 }}>
        <div className="panel-sub">不确定性说明</div>
        <p className="small">{card.uncertainty}</p>
      </div>

      <Notice>{card.disclaimer}</Notice>
    </div>
  );
}

function EffectRow({ effect }: { effect: AtlasEffectNote }): JSX.Element {
  return (
    <div className="citation-box">
      <div>{effect.text}</div>
      <div className="small muted">
        来源：{effect.citation.title}
        {effect.citation.locator ? ` · ${effect.citation.locator}` : ""}
        {effect.citation.is_demo ? " · DEMO 演示来源" : ""}
      </div>
      {effect.citation.excerpt && <p className="small">{effect.citation.excerpt}</p>}
      <CitationDetail citation={effect.citation} />
    </div>
  );
}

function StatementForm({
  cards,
  records,
  onCreated,
}: {
  cards: AtlasCardData[];
  records: AtlasPayload["ingredient_feedback"];
  onCreated: () => void;
}): JSX.Element {
  const toast = useToast();
  const [ingredientId, setIngredientId] = useState<string>(cards[0]?.ingredient_id ?? "");
  const [statement, setStatement] = useState("");
  const create = useAction<[], Awaited<ReturnType<typeof postIngredientFeedback>>>((..._args) =>
    postIngredientFeedback({ ingredient_id: ingredientId, statement: statement.trim() }),
  );

  return (
    <div className="stack">
      {records.length > 0 && (
        <ul className="small">
          {records.map((record) => (
            <li key={record.id}>
              {record.statement}
              <span className="muted">
                {" "}
                · 成分 {record.ingredient_id.slice(0, 8)} · {record.created_at ? formatDateTime(record.created_at) : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      {cards.length === 0 ? (
        <EmptyState hint="图鉴卡片生成后才能补充针对成分的陈述。">
          当前没有可选择的成分卡片。
        </EmptyState>
      ) : (
        <>
          <div className="row">
            <div className="field">
              <label htmlFor="if-ingredient">成分</label>
              <select
                id="if-ingredient"
                data-testid="atlas-feedback-ingredient"
                value={ingredientId}
                onChange={(event) => setIngredientId(event.target.value)}
              >
                {cards.map((card) => (
                  <option key={card.ingredient_id} value={card.ingredient_id}>
                    {card.common_name} / {card.inci_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ flex: 1, minWidth: 260 }}>
              <label htmlFor="if-statement">我的明确陈述 *</label>
              <input
                id="if-statement"
                data-testid="atlas-feedback-input"
                value={statement}
                onChange={(event) => setStatement(event.target.value)}
                placeholder="例如：我确定使用含该成分的产品时更容易有刺痛感"
              />
            </div>
            <button
              type="button"
              className="primary"
              data-testid="atlas-feedback-submit"
              disabled={create.running || statement.trim().length === 0 || ingredientId === ""}
              onClick={() => {
                void (async () => {
                  const result = await create.run();
                  if (result) {
                    toast.show(result.notice);
                    setStatement("");
                    onCreated();
                  }
                })();
              }}
            >
              {create.running ? "提交中…" : "补充我的陈述"}
            </button>
          </div>
          <Notice>
            这是你本人的明确陈述，会与统计信号分开显示，不作为因果结论，也不替代专业建议。
          </Notice>
          <ActionFeedback error={create.error} />
        </>
      )}
    </div>
  );
}
