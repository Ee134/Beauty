/**
 * /environment 城市、当前与预测环境、来源/更新时间/缺失字段、活动与行程。
 * 缺失、过时、提供方失败都如实显示；不用 0 代替未知，也不用 mock 冒充 live。
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import {
  cancelActivity,
  createActivity,
  getEnvironment,
  getForecastFor,
  listActivities,
  listCities,
  listTriggerRules,
  putLocation,
} from "../api/endpoints";
import type { EnvironmentResponse, EnvironmentSnapshot } from "../api/types";
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
import { formatDateTime, fromDateTimeLocal } from "../lib/format";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

export function EnvironmentPage(): JSX.Element {
  const toast = useToast();
  const { lastLoadedAt, refreshMe } = useSession();
  const [cityOverride, setCityOverride] = useState<string>("");
  const environment = useAsync<EnvironmentResponse>(
    () => getEnvironment(cityOverride || undefined),
    { deps: [cityOverride, lastLoadedAt] },
  );
  const cities = useAsync(() => listCities(), { deps: [] });
  const activities = useAsync(() => listActivities(), { deps: [lastLoadedAt] });
  const rules = useAsync(() => listTriggerRules(), { deps: [] });

  const setLocation = useAction<[string], Awaited<ReturnType<typeof putLocation>>>((cityId) =>
    putLocation({ city_id: cityId, purpose: "home", provenance: "manual" }),
  );
  const cancel = useAction<[string], Awaited<ReturnType<typeof cancelActivity>>>((id) => cancelActivity(id));

  return (
    <div className="stack">
      <Panel
        title="环境与出行"
        subtitle="城市、当前与预测数据、来源与更新时间、活动与行程"
        actions={
          <>
            <select
              data-testid="city-select"
              value={cityOverride}
              onChange={(event) => setCityOverride(event.target.value)}
            >
              <option value="">使用我的城市设置</option>
              {(cities.data?.cities ?? []).map((city) => (
                <option key={city.city_id} value={city.city_id}>
                  {city.name_zh}
                </option>
              ))}
            </select>
            <button
              type="button"
              data-testid="city-save"
              disabled={setLocation.running || cityOverride === ""}
              onClick={() => {
                void (async () => {
                  const result = await setLocation.run(cityOverride);
                  if (result) {
                    toast.show(result.notice);
                    setCityOverride("");
                    environment.reload();
                    void refreshMe();
                  }
                })();
              }}
            >
              保存为我的城市
            </button>
            <button type="button" onClick={() => environment.reload()}>
              刷新
            </button>
          </>
        }
      >
        <AsyncBlock
          loading={environment.loading}
          error={environment.error}
          data={environment.data}
          onRetry={environment.reload}
          loadingLabel="加载环境快照…"
        >
          {(data) => (
            <div className="stack">
              {!data.available || data.current === null || data.current === undefined ? (
                <EmptyState hint={data.notice ?? "可选择城市后重试。"}>
                  环境数据当前不可用（可能是未选择城市、提供方失败或数据过期）。
                </EmptyState>
              ) : (
                <div className="stack">
                  <div className="row tight">
                    <Badge tone="accent">{data.city_name}</Badge>
                    <Badge tone="mock">provider：{data.provider}</Badge>
                    <Badge tone="mock">mode：{data.mode}</Badge>
                    <Badge tone={data.quality === "ok" ? "ok" : "warn"}>quality：{data.quality}</Badge>
                    {data.scenario && <Badge tone="mock">scenario：{data.scenario}</Badge>}
                    {data.is_demo && <Badge tone="mock">演示数据</Badge>}
                    <Badge>{data.using_user_city ? "使用我的城市设置" : "按 city_id 查询"}</Badge>
                  </div>
                  <SnapshotView
                    snapshot={data.current}
                    title="当前"
                    testId="env-current"
                    qualityTestId="env-quality"
                    missingTestId="env-missing-fields"
                  />
                </div>
              )}

              <div>
                <div className="panel-sub">预测（按天）</div>
                {data.forecast && data.forecast.length > 0 ? (
                  <div className="grid">
                    {data.forecast.map((snapshot) => (
                      <SnapshotView key={snapshot.id} snapshot={snapshot} title="预报" compact />
                    ))}
                  </div>
                ) : (
                  <EmptyState>没有可用的预报数据（超出覆盖范围时保持未知）。</EmptyState>
                )}
              </div>

              {data.notice && <Notice>{data.notice}</Notice>}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="我的城市设置" subtitle="PUT /location-preferences（手动选择，不使用 IP 推断）">
        <AsyncBlock loading={cities.loading} error={cities.error} data={cities.data} onRetry={cities.reload}>
          {(data) => (
            <div className="stack">
              <div className="row tight">
                {data.cities.map((city) => (
                  <button
                    key={city.city_id}
                    type="button"
                    disabled={setLocation.running}
                    onClick={() => {
                      void (async () => {
                        const result = await setLocation.run(city.city_id);
                        if (result) {
                          toast.show(result.notice);
                          setCityOverride("");
                          environment.reload();
                          void refreshMe();
                        }
                      })();
                    }}
                  >
                    设为 {city.name_zh}
                  </button>
                ))}
              </div>
              <Notice>{data.notice}</Notice>
              <ActionFeedback error={setLocation.error} />
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <ForecastLookup />

      <Panel title="活动与行程" subtitle="仅来自你的确认，不根据定位推断">
        <AsyncBlock
          loading={activities.loading}
          error={activities.error}
          data={activities.data}
          onRetry={activities.reload}
          isEmpty={(data) => data.activities.length === 0}
          empty="还没有已确认的活动或行程。"
        >
          {(data) => (
            <div className="stack">
              <table className="table">
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>类型</th>
                    <th>开始</th>
                    <th>结束</th>
                    <th>目的地</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {data.activities.map((activity) => (
                    <tr key={activity.id} data-testid="activity-row" data-activity-id={activity.id}>
                      <td>{activity.title}</td>
                      <td>{activity.activity_type}</td>
                      <td>{formatDateTime(activity.starts_at)}</td>
                      <td>{formatDateTime(activity.ends_at)}</td>
                      <td>{activity.destination_city_id ?? "—"}</td>
                      <td>
                        <Badge tone={activity.status === "cancelled" ? "warn" : "ok"}>{activity.status}</Badge>
                      </td>
                      <td>
                        {activity.status !== "cancelled" && (
                          <button
                            type="button"
                            className="danger"
                            data-testid="activity-cancel"
                            disabled={cancel.running}
                            onClick={() => {
                              void (async () => {
                                const result = await cancel.run(activity.id);
                                if (result) {
                                  toast.show("已取消活动，依赖它的待发消息会在发送前取消。");
                                  activities.reload();
                                }
                              })();
                            }}
                          >
                            取消
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
        <ActionFeedback error={cancel.error} />
        <ActivityForm
          onCreated={() => {
            activities.reload();
            void refreshMe();
          }}
        />
      </Panel>

      <Panel title="触发规则（演示规则）" subtitle="阈值来源与审核状态逐条标注，不代表医学依据">
        <AsyncBlock
          loading={rules.loading}
          error={rules.error}
          data={rules.data}
          onRetry={rules.reload}
          isEmpty={(data) => data.rules.length === 0}
          empty="没有可展示的触发规则。"
        >
          {(data) => (
            <div className="stack">
              <table className="table">
                <thead>
                  <tr>
                    <th>服务类型</th>
                    <th>条件</th>
                    <th>阈值来源</th>
                    <th>审核状态</th>
                    <th>冷却/最小间隔</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rules.map((rule) => (
                    <tr key={rule.service_type}>
                      <td>{rule.service_type}</td>
                      <td className="mono small">{JSON.stringify(rule.conditions)}</td>
                      <td>{rule.threshold_source}</td>
                      <td>{rule.approval_status}</td>
                      <td>
                        {rule.cooldown_minutes} / {rule.min_interval_minutes} 分钟
                      </td>
                      <td className="small">{rule.notes ?? rule.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <p className="small muted">
        相关页面：<Link to="/inbox">收件箱</Link> · <Link to="/settings">通知设置</Link> ·{" "}
        <Link to="/routine">计划</Link>
      </p>
    </div>
  );
}

function SnapshotView({
  snapshot,
  title,
  compact = false,
  testId,
  qualityTestId,
  missingTestId,
}: {
  snapshot: EnvironmentSnapshot;
  title: string;
  compact?: boolean;
  /** 稳定的 E2E 钩子。 */
  testId?: string;
  qualityTestId?: string;
  missingTestId?: string;
}): JSX.Element {
  const metrics = snapshot.metrics ?? {};
  const entries = Object.entries(metrics);
  return (
    <div className="step" data-testid={testId}>
      <div className="row tight">
        <Badge tone={snapshot.freshness === "ok" ? "ok" : "warn"}>{title}</Badge>
        <Badge>{snapshot.kind}</Badge>
        <span data-testid={qualityTestId}>
          <Badge tone={snapshot.quality === "ok" ? "ok" : "warn"}>quality：{snapshot.quality}</Badge>
        </span>
        <Badge tone={snapshot.freshness === "ok" ? "ok" : "warn"}>freshness：{snapshot.freshness}</Badge>
        {snapshot.is_demo && <Badge tone="mock">演示数据</Badge>}
        {snapshot.error_code && <Badge tone="error">{snapshot.error_code}</Badge>}
      </div>
      {entries.length === 0 ? (
        <EmptyState>该快照没有可用指标（缺失字段不会用 0 代替）。</EmptyState>
      ) : (
        <KeyValue
          items={entries.map(([key, value]) => [
            `${key}${snapshot.units?.[key] ? `（${snapshot.units[key]}）` : ""}`,
            value === null || value === undefined ? "未知" : String(value),
          ])}
        />
      )}
      <p className="small muted" data-testid={missingTestId}>
        缺失字段：
        {snapshot.missing_fields.length > 0
          ? `${snapshot.missing_fields.join("、")}（保持未知，不填充）`
          : "无（全部字段可用）"}
      </p>
      {!compact && (
        <div className="small muted">
          提供方：{snapshot.provider} · 数据时间：{formatDateTime(snapshot.issued_at)} · 抓取时间：
          {formatDateTime(snapshot.fetched_at)} · 有效期：{formatDateTime(snapshot.valid_from)} →{" "}
          {formatDateTime(snapshot.valid_to)} · 缓存年龄 {snapshot.age_minutes ?? "未知"} / 上限{" "}
          {snapshot.max_age_minutes} 分钟
        </div>
      )}
    </div>
  );
}

function ForecastLookup(): JSX.Element {
  const [cityId, setCityId] = useState("CN-BJ");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const result = useAsync(() => getForecastFor(cityId, date), { deps: [cityId, date] });
  return (
    <Panel title="按日期查询预报" subtitle="GET /environment/forecast-for（覆盖范围外返回未知）">
      <div className="row">
        <div className="field">
          <label htmlFor="fc-city">城市 ID</label>
          <input id="fc-city" value={cityId} onChange={(event) => setCityId(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="fc-date">日期</label>
          <input
            id="fc-date"
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </div>
        <button type="button" onClick={result.reload}>
          查询
        </button>
      </div>
      <AsyncBlock loading={result.loading} error={result.error} data={result.data} onRetry={result.reload}>
        {(data) =>
          !data.found || data.day === null ? (
            <EmptyState hint={`可用日期：${data.available_days.join("、") || "无"}`}>
              该日期超出预报覆盖范围，显示为未知（不伪造天气）。
            </EmptyState>
          ) : (
            <KeyValue
              items={Object.entries(data.day.metrics ?? {}).map(([key, value]) => [
                key,
                value === null || value === undefined ? "未知" : String(value),
              ])}
            />
          )
        }
      </AsyncBlock>
    </Panel>
  );
}

function ActivityForm({ onCreated }: { onCreated: () => void }): JSX.Element {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<"outdoor" | "trip">("outdoor");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [destination, setDestination] = useState("");
  const cities = useAsync(() => listCities(), { deps: [] });
  const create = useAction(() =>
    createActivity({
      activity_type: type,
      title,
      starts_at: fromDateTimeLocal(startsAt) ?? new Date().toISOString(),
      ends_at: fromDateTimeLocal(endsAt),
      destination_city_id: destination || null,
      user_confirmed: true,
    }),
  );

  return (
    <div className="stack" style={{ marginTop: 10 }}>
      <div className="panel-sub">新增活动/行程（user_confirmed=true）</div>
      <div className="row">
        <div className="field">
          <label htmlFor="act-title">标题 *</label>
          <input
            id="act-title"
            data-testid="activity-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="act-type">类型</label>
          <select
            id="act-type"
            data-testid="activity-type"
            value={type}
            onChange={(event) => setType(event.target.value as "outdoor" | "trip")}
          >
            <option value="outdoor">户外活动</option>
            <option value="trip">行程</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="act-start">开始 *</label>
          <input
            id="act-start"
            data-testid="activity-start"
            type="datetime-local"
            value={startsAt}
            onChange={(event) => setStartsAt(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="act-end">结束</label>
          <input
            id="act-end"
            type="datetime-local"
            value={endsAt}
            onChange={(event) => setEndsAt(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="act-dest">目的地城市</label>
          <select
              id="act-dest"
              data-testid="activity-destination"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            >
            <option value="">（不指定）</option>
            {(cities.data?.cities ?? []).map((city) => (
              <option key={city.city_id} value={city.city_id}>
                {city.name_zh}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          className="primary"
          data-testid="activity-create"
          disabled={create.running || title.trim().length === 0}
          onClick={() => {
            void (async () => {
              const result = await create.run();
              if (result) {
                setTitle("");
                setStartsAt("");
                setEndsAt("");
                onCreated();
              }
            })();
          }}
        >
          {create.running ? "保存中…" : "添加活动"}
        </button>
      </div>
      <Notice>
        未提供户外活动时，系统不会仅由定位推断你正在户外；预报未覆盖的日期显示未知。
      </Notice>
      <ActionFeedback error={create.error} />
    </div>
  );
}
