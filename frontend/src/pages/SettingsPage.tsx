/**
 * /settings 数据导出/删除、地点、通知类型/渠道/频率/免打扰、模型模式说明、PWA 通知订阅。
 *
 * 通知权限：只在用户点击按钮后才调用 Notification.requestPermission()；
 * 有 VAPID 公钥时才 pushManager.subscribe，否则如实显示 mock/未启用状态。
 */

import { useEffect, useState } from "react";
import {
  createPushSubscription,
  deleteAccountData,
  exportData,
  getClock,
  getMeta,
  getNotificationPreferences,
  getWeatherScenario,
  listCities,
  listPushSubscriptions,
  putLocation,
  putNotificationPreferences,
  revokePushSubscription,
  setClock,
  setWeatherScenario,
} from "../api/endpoints";
import { getLocation } from "../api/endpoints";
import { describeError } from "../api/client";
import type {
  LocationPreference,
  NotificationPreferencePatch,
  NotificationPreferencesResponse,
} from "../api/types";
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
import { formatDateTime } from "../lib/format";
import { channelLabel, serviceTypeLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

const SERVICE_TYPES = [
  "travel_support",
  "outdoor_support",
  "environment_checkin",
  "service_progress",
  "routine_followup",
];

const CHANNELS = ["in_app", "web_push"];

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY ?? "";

export function SettingsPage(): JSX.Element {
  const toast = useToast();
  const { me, refreshMe, refreshContext, lastLoadedAt } = useSession();
  const prefs = useAsync(() => getNotificationPreferences(), { deps: [lastLoadedAt] });
  const subscriptions = useAsync(() => listPushSubscriptions(), { deps: [lastLoadedAt] });
  const cities = useAsync(() => listCities(), { deps: [] });
  const location = useAsync(() => getLocation(), { deps: [lastLoadedAt] });
  const meta = useAsync(() => getMeta(), { deps: [] });
  const clock = useAsync(() => getClock(), { deps: [lastLoadedAt] });
  const scenario = useAsync(() => getWeatherScenario(), { deps: [lastLoadedAt] });

  const saveLocation = useAction<[string], Awaited<ReturnType<typeof putLocation>>>((cityId) =>
    putLocation({ city_id: cityId, purpose: "home", provenance: "manual" }),
  );
  const exportAction = useAction<[], Record<string, unknown>>(() => exportData());
  const deleteAction = useAction<[], Awaited<ReturnType<typeof deleteAccountData>>>(() => deleteAccountData());
  const revoke = useAction<[string | undefined], Awaited<ReturnType<typeof revokePushSubscription>>>((id) =>
    revokePushSubscription(id),
  );
  const setScenario = useAction<[string], Awaited<ReturnType<typeof setWeatherScenario>>>((name) =>
    setWeatherScenario(name),
  );
  const setDemoClock = useAction<[("real" | "demo")], Awaited<ReturnType<typeof setClock>>>((mode) =>
    setClock(mode === "real" ? { mode: "real" } : { mode: "demo", day: 5, label: "演示第 5 天" }),
  );

  const refreshPrefs = () => {
    prefs.reload();
    subscriptions.reload();
    void refreshMe();
    void refreshContext();
  };

  return (
    <div className="stack">
      <Panel title="设置" subtitle="状态以服务器为准；网站修改后 PWA 与已排队消息立即使用新状态">
        <div className="row tight">
          <Badge tone={me?.mode.model_mode === "mock" ? "mock" : "ok"}>
            MODEL_MODE：{me?.mode.model_mode ?? "未知"}
          </Badge>
          <Badge tone="mock">WEATHER_MODE：{me?.mode.weather_mode ?? "未知"}</Badge>
          <Badge tone="accent">NOTIFICATION_MODE：{me?.mode.notification_mode ?? "未知"}</Badge>
          <Badge>AUTH_MODE：{me?.mode.auth_mode ?? "未知"}</Badge>
        </div>
      </Panel>

      <Panel title="模式说明" subtitle="GET /meta、GET /health（不含密钥或路径）">
        <AsyncBlock loading={meta.loading} error={meta.error} data={meta.data} onRetry={meta.reload}>
          {(data) => (
            <div className="stack">
              <KeyValue
                items={[
                  ["应用", `${data.app.name} · 时区 ${data.app.timezone}`],
                  ["演示身份可登录", data.demo_auth ? "是（AUTH_MODE=demo）" : "否"],
                  ["可切换身份", data.personas.join("、")],
                  ["模型适配器", JSON.stringify(data.model)],
                  ["数据说明", data.data_notice],
                ]}
              />
              <Notice tone="mock">
                mock 模式使用确定性 fixtures，不声称真实模型/识别能力；live 未配置密钥时如实显示不可用，
                由用户显式切回 mock。前端不获取也不展示任何 API 密钥。
              </Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="地点" subtitle="MVP 默认手动选择城市；不使用 IP 作为真实居住地">
        <AsyncBlock
          loading={location.loading}
          error={location.error}
          data={location.data}
          onRetry={location.reload}
        >
          {(data) => (
            <div className="stack">
              {data.location === null ? (
                <EmptyState>尚未选择城市。</EmptyState>
              ) : (
                <KeyValue
                  items={[
                    ["当前城市", `${data.location.city_name}（${data.location.city_id}）`],
                    ["用途 / 来源", `${data.location.purpose} / ${data.location.provenance}`],
                    ["时区", data.location.timezone],
                    ["版本", `v${data.location.version}`],
                    ["更新时间", formatDateTime(data.location.updated_at)],
                  ]}
                />
              )}
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
        <AsyncBlock loading={cities.loading} error={cities.error} data={cities.data} onRetry={cities.reload}>
          {(data) => (
            <div className="row tight">
              {data.cities.map((city) => (
                <button
                  key={city.city_id}
                  type="button"
                  className={location.data?.location?.city_id === city.city_id ? "primary" : ""}
                  disabled={saveLocation.running}
                  onClick={() => {
                    void (async () => {
                      const result = await saveLocation.run(city.city_id);
                      if (result) {
                        toast.show(result.notice);
                        location.reload();
                        void refreshMe();
                      }
                    })();
                  }}
                >
                  {city.name_zh}
                </button>
              ))}
              <span className="small muted">
                {data.notice}
              </span>
            </div>
          )}
        </AsyncBlock>
        <ActionFeedback error={saveLocation.error} />
      </Panel>

      <NotificationForm
        response={prefs.data}
        loading={prefs.loading}
        error={prefs.error}
        onRetry={prefs.reload}
        onSaved={refreshPrefs}
      />
      <Panel title="浏览器通知订阅（PWA）" subtitle="只在点击后请求权限；没有 VAPID 公钥时如实显示未启用">
        <NotificationOptIn onChanged={refreshPrefs} />
        <AsyncBlock
          loading={subscriptions.loading}
          error={subscriptions.error}
          data={subscriptions.data}
          onRetry={subscriptions.reload}
          isEmpty={(data) => data.subscriptions.length === 0}
          empty="当前没有设备订阅。"
        >
          {(data) => (
            <div className="stack">
              <table className="table">
                <thead>
                  <tr>
                    <th>设备</th>
                    <th>平台</th>
                    <th>状态</th>
                    <th>授权时间</th>
                    <th>撤销时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {data.subscriptions.map((subscription) => (
                    <tr key={subscription.id}>
                      <td>{subscription.device_id}</td>
                      <td>{subscription.platform}</td>
                      <td>{subscription.status}</td>
                      <td>{formatDateTime(subscription.granted_at)}</td>
                      <td>{formatDateTime(subscription.revoked_at)}</td>
                      <td>
                        <button
                          type="button"
                          className="danger"
                          disabled={revoke.running}
                          onClick={() => {
                            void (async () => {
                              const result = await revoke.run(subscription.id);
                              if (result) {
                                toast.show(result.notice);
                                refreshPrefs();
                              }
                            })();
                          }}
                        >
                          撤销
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
        <ActionFeedback error={revoke.error} />
      </Panel>

      <Panel title="演示时钟与天气场景" subtitle="本地演示控制：所有输出都会标记 is_demo_time / scenario">
        <div className="row tight">
          <Badge tone={clock.data?.clock.is_demo_time ? "warn" : "ok"}>
            当前：{clock.data?.clock.label ?? "未知"}（is_demo_time=
            {String(clock.data?.clock.is_demo_time ?? false)}）
          </Badge>
          <button
            type="button"
            disabled={setDemoClock.running}
            onClick={() => {
              void (async () => {
                const result = await setDemoClock.run("demo");
                if (result) {
                  toast.show(result.notice);
                  clock.reload();
                  void refreshMe();
                }
              })();
            }}
          >
            切到演示第 5 天
          </button>
          <button
            type="button"
            disabled={setDemoClock.running}
            onClick={() => {
              void (async () => {
                const result = await setDemoClock.run("real");
                if (result) {
                  toast.show(result.notice);
                  clock.reload();
                  void refreshMe();
                }
              })();
            }}
          >
            恢复真实时间
          </button>
        </div>
        <ActionFeedback error={setDemoClock.error} />
        <AsyncBlock
          loading={scenario.loading}
          error={scenario.error}
          data={scenario.data}
          onRetry={scenario.reload}
        >
          {(data) => (
            <div className="stack">
              <div className="small muted">
                当前场景：{data.current} · {data.notice}
              </div>
              <div className="row tight">
                {data.available.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className={data.current === name ? "primary" : ""}
                    disabled={setScenario.running}
                    title={data.description[name]}
                    onClick={() => {
                      void (async () => {
                        const result = await setScenario.run(name);
                        if (result) {
                          toast.show(result.notice);
                          scenario.reload();
                        }
                      })();
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="我的数据" subtitle="导出与删除（全量删除涵盖原文、图片、计划、记忆、事件、工单、任务、订阅与派生内容）">
        <div className="row tight">
          <button
            type="button"
            data-testid="privacy-export"
            disabled={exportAction.running}
            onClick={() => {
              void (async () => {
                const result = await exportAction.run();
                if (result) {
                  const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
                  const url = URL.createObjectURL(blob);
                  const anchor = document.createElement("a");
                  anchor.href = url;
                  anchor.download = `beautycare-export-${new Date().toISOString().slice(0, 10)}.json`;
                  anchor.click();
                  URL.revokeObjectURL(url);
                  toast.show("已下载导出文件（本地生成，不含他人数据）。");
                }
              })();
            }}
          >
            {exportAction.running ? "导出中…" : "导出我的数据（JSON）"}
          </button>
          <button
            type="button"
            className="danger"
            data-testid="privacy-delete"
            disabled={deleteAction.running}
            onClick={() => {
              void (async () => {
                const result = await deleteAction.run();
                if (result) {
                  toast.show("已请求删除账户数据。");
                  refreshPrefs();
                }
              })();
            }}
          >
            {deleteAction.running ? "删除中…" : "删除我的全部业务数据"}
          </button>
        </div>
        <Notice>
          删除不可撤销；MVP 不保留备份副本。共享产品目录、来源与他人数据不会被删除。删除后请在演示身份处重新
          登录以重建演示数据（需要重新运行 seed 才能恢复）。
        </Notice>
        <ActionFeedback error={exportAction.error} />
        <ActionFeedback error={deleteAction.error} />
        {deleteAction.result && (
          <div className="state">
            删除结果：
            <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(deleteAction.result, null, 1)}
            </pre>
          </div>
        )}
      </Panel>
    </div>
  );
}

function NotificationOptIn({ onChanged }: { onChanged: () => void }): JSX.Element {
  const toast = useToast();
  const [permission, setPermission] = useState<string>(
    typeof Notification !== "undefined" ? Notification.permission : "unsupported",
  );
  const [subscribing, setSubscribing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);

  const subscribe = async () => {
    setError(null);
    setMessage(null);
    if (typeof Notification === "undefined" || !("serviceWorker" in navigator)) {
      setMessage("当前浏览器不支持通知或 Service Worker：这是能力限制，不是已启用。");
      return;
    }
    setSubscribing(true);
    try {
      const result = await Notification.requestPermission();
      setPermission(result);
      if (result !== "granted") {
        setMessage(`用户未授权浏览器通知（permission=${result}）。不会发送任何外部推送。`);
        return;
      }
      if (VAPID_PUBLIC_KEY.length === 0) {
        setMessage(
          "已获得浏览器通知权限，但后端未提供 VAPID 公钥（VITE_VAPID_PUBLIC_KEY 为空）：" +
            "Web Push 处于明确标注的 mock/未启用状态，不会伪装成已订阅。",
        );
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const existing = await registration.pushManager.getSubscription();
      const subscription =
        existing ??
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
        }));
      const json = subscription.toJSON();
      const saved = await createPushSubscription({
        endpoint: json.endpoint ?? subscription.endpoint,
        keys: (json.keys as Record<string, unknown> | undefined) ?? null,
        device_id: "web-demo",
        platform: "web",
      });
      setMessage(saved.notice);
      toast.show("已登记设备订阅（本地演示，不会向真实推送服务发送）。");
      onChanged();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubscribing(false);
    }
  };

  return (
    <div className="stack">
      <div className="row tight">
        <Badge tone={permission === "granted" ? "ok" : "warn"}>浏览器权限：{permission}</Badge>
        <Badge tone={VAPID_PUBLIC_KEY ? "ok" : "mock"}>
          VAPID 公钥：{VAPID_PUBLIC_KEY ? "已配置" : "未配置（mock/未启用）"}
        </Badge>
        <button type="button" className="primary" disabled={subscribing} onClick={() => void subscribe()}>
          {subscribing ? "处理中…" : "点击开启浏览器通知（可选）"}
        </button>
      </div>
      <Notice>
        通知权限不会在首次访问时自动弹出，只有你点击上面的按钮才会请求。未配置 VAPID 时订阅不可用，
        界面会如实说明；离线时禁止确认计划或提交工单。
      </Notice>
      {message && <div className="state">{message}</div>}
      <ActionFeedback error={error} />
    </div>
  );
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const output = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i += 1) {
    output[i] = rawData.charCodeAt(i);
  }
  return output;
}

export function locationSummary(location: LocationPreference | null): string {
  return location === null ? "未选择城市" : `${location.city_name}（${location.city_id}）`;
}

/**
 * 通知偏好表单：本地编辑后由「保存通知设置」一次性 PUT（携带 expected_version）。
 * 只有在点击保存时才会调用 API，因此 E2E 可以先改多个字段再一次提交。
 */
function NotificationForm({
  response,
  loading,
  error,
  onRetry,
  onSaved,
}: {
  response: NotificationPreferencesResponse | null;
  loading: boolean;
  error: ReturnType<typeof describeError> | null;
  onRetry: () => void;
  onSaved: () => void;
}): JSX.Element {
  const toast = useToast();
  const [form, setForm] = useState<NotificationPreferencePatch>({});
  const prefs = response?.preferences ?? null;

  useEffect(() => {
    if (prefs) {
      setForm({
        service_types: [...prefs.service_types],
        channels: [...prefs.channels],
        daily_cap: prefs.daily_cap,
        quiet_hours_start: prefs.quiet_hours_start,
        quiet_hours_end: prefs.quiet_hours_end,
        timezone: prefs.timezone,
        marketing_opt_in: prefs.marketing_opt_in,
      });
    }
  }, [prefs]);

  const save = useAction<[], Awaited<ReturnType<typeof putNotificationPreferences>>>((..._args) =>
    putNotificationPreferences({ ...form, expected_version: prefs?.version ?? null }),
  );

  const serviceTypes = form.service_types ?? prefs?.service_types ?? [];
  const selectedChannels = form.channels ?? prefs?.channels ?? [];
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value];

  return (
    <Panel title="通知类型 / 渠道 / 频率 / 免打扰" subtitle="PUT /notification-preferences（默认关闭外部推送）">
      <AsyncBlock loading={loading} error={error} data={response} onRetry={onRetry} loadingLabel="加载通知偏好…">
        {(data) => {
          const current = data.preferences;
          return (
            <div className="stack">
              <div>
                <div className="panel-sub">服务类型</div>
                <div className="row tight">
                  {SERVICE_TYPES.map((type) => (
                    <label key={type} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
                      <input
                        type="checkbox"
                        data-testid={`notif-service-type-${type}`}
                        checked={serviceTypes.includes(type)}
                        onChange={() => setForm((prev) => ({ ...prev, service_types: toggle(serviceTypes, type) }))}
                      />
                      {serviceTypeLabel(type)}
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <div className="panel-sub">渠道</div>
                <div className="row tight">
                  {CHANNELS.map((channel) => (
                    <label key={channel} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
                      <input
                        type="checkbox"
                        data-testid={channel === "web_push" ? "notif-channel-webpush" : `notif-channel-${channel}`}
                        checked={selectedChannels.includes(channel)}
                        onChange={() => setForm((prev) => ({ ...prev, channels: toggle(selectedChannels, channel) }))}
                      />
                      {channelLabel(channel)}
                    </label>
                  ))}
                </div>
                <ul className="small muted">
                  <li>
                    内应用消息：{data.channels.in_app.mode}（available={String(data.channels.in_app.available)}）
                  </li>
                  <li>
                    Web Push：{data.channels.web_push.mode}（has_vapid={String(data.channels.web_push.has_vapid)}）—{" "}
                    {data.channels.web_push.notice}
                  </li>
                  <li>原生推送：{data.channels.native_push.notice}</li>
                </ul>
              </div>

              <div className="row">
                <div className="field">
                  <label htmlFor="daily-cap">每日上限（0–10）</label>
                  <input
                    id="daily-cap"
                    data-testid="notif-daily-cap"
                    type="number"
                    min={0}
                    max={10}
                    value={String(form.daily_cap ?? current.daily_cap)}
                    onChange={(event) => setForm((prev) => ({ ...prev, daily_cap: Number(event.target.value) }))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="quiet-start">免打扰开始</label>
                  <input
                    id="quiet-start"
                    data-testid="notif-quiet-start"
                    type="time"
                    value={form.quiet_hours_start ?? current.quiet_hours_start}
                    onChange={(event) => setForm((prev) => ({ ...prev, quiet_hours_start: event.target.value }))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="quiet-end">免打扰结束</label>
                  <input
                    id="quiet-end"
                    data-testid="notif-quiet-end"
                    type="time"
                    value={form.quiet_hours_end ?? current.quiet_hours_end}
                    onChange={(event) => setForm((prev) => ({ ...prev, quiet_hours_end: event.target.value }))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="tz">通知时区</label>
                  <input
                    id="tz"
                    value={form.timezone ?? current.timezone}
                    onChange={(event) => setForm((prev) => ({ ...prev, timezone: event.target.value }))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="marketing">营销消息（默认关闭）</label>
                  <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
                    <input
                      id="marketing"
                      type="checkbox"
                      data-testid="notif-marketing"
                      checked={form.marketing_opt_in ?? current.marketing_opt_in}
                      onChange={(event) => setForm((prev) => ({ ...prev, marketing_opt_in: event.target.checked }))}
                    />
                    {(form.marketing_opt_in ?? current.marketing_opt_in) ? "已开启" : "已关闭"}
                  </label>
                </div>
                <button
                  type="button"
                  className="primary"
                  data-testid="notif-save"
                  disabled={save.running}
                  onClick={() => {
                    void (async () => {
                      const result = await save.run();
                      if (result) {
                        toast.show(result.notice);
                        onSaved();
                      }
                    })();
                  }}
                >
                  {save.running ? "保存中…" : "保存通知设置"}
                </button>
              </div>

              {current.muted_service_types.length > 0 && (
                <div className="small muted">
                  已关闭此类：{current.muted_service_types.map(serviceTypeLabel).join("、")}
                </div>
              )}
              <KeyValue
                items={[
                  ["授权版本", current.consent_version],
                  ["偏好版本", `v${current.version}（更新携带 expected_version，冲突返回 409）`],
                  ["外部推送", current.external_push_enabled ? "已开启" : "已关闭"],
                ]}
              />
              <Notice>{data.notice}</Notice>
            </div>
          );
        }}
      </AsyncBlock>
      <ActionFeedback error={save.error} />
    </Panel>
  );
}
