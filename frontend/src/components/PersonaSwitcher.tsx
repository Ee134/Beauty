/**
 * 演示身份切换器（本地 demo identity exchange）。
 *
 * 这是本地演示用的身份交换入口：选择 persona_code 后调用
 * POST /api/v1/auth/demo-session 换取服务端令牌。
 * 前端从不提交 user_id；body 里只有 persona_code + device_label。
 * 该控件在界面上显著标注为「演示身份」，不冒充真实登录。
 */

import { useState } from "react";
import type { PersonaCode } from "../api/types";
import { useSession } from "../state/SessionContext";
import { Badge, ErrorState, useToast } from "./ui";

export const PERSONAS: Array<{ code: PersonaCode; label: string; hint: string; testId: string }> = [
  { code: "consumer_a", label: "消费者 A", hint: "反馈积累充分，可触发成分图鉴", testId: "persona-consumer_a" },
  { code: "consumer_b", label: "消费者 B", hint: "另一独立用户（用于验证数据隔离）", testId: "persona-consumer_b" },
  { code: "staff", label: "客服（演示工作台）", hint: "可查看演示工单队列与审计", testId: "persona-staff" },
  { code: "brand", label: "品牌（演示面板）", hint: "只看聚合汇总，群体不足时抑制", testId: "persona-brand" },
];

export function PersonaSwitcher({ compact = false }: { compact?: boolean }): JSX.Element {
  const { persona, login, loading, error, logout, token } = useSession();
  const [pending, setPending] = useState<PersonaCode | null>(null);
  const toast = useToast();

  const switchTo = async (code: PersonaCode) => {
    setPending(code);
    const ok = await login(code);
    setPending(null);
    if (ok) {
      toast.show(`已切换到演示身份：${PERSONAS.find((p) => p.code === code)?.label ?? code}`);
    }
  };

  return (
    <div className={compact ? "stack" : "panel stack"} data-testid="persona-switcher">
      {!compact && (
        <div>
          <div className="panel-title">演示身份</div>
          <div className="panel-sub">
            服务端固定演示身份，仅用于本地演示；等同于真实登录前的本地演示入口。
          </div>
        </div>
      )}
      <div className="row tight">
        {PERSONAS.map((item) => (
          <button
            key={item.code}
            type="button"
            data-testid={item.testId}
            className={persona === item.code ? "primary" : ""}
            disabled={loading || pending !== null}
            title={item.hint}
            onClick={() => void switchTo(item.code)}
          >
            {pending === item.code ? "切换中…" : item.label}
          </button>
        ))}
        {token && (
          <button type="button" onClick={logout}>
            退出（清除本地令牌）
          </button>
        )}
      </div>
      {persona && (
        <div className="row tight">
          <Badge tone="mock">当前演示身份：{persona}</Badge>
          <span className="small muted">
            {PERSONAS.find((p) => p.code === persona)?.hint ?? ""}
          </span>
        </div>
      )}
      {error && <ErrorState error={error} title="演示身份登录失败" />}
    </div>
  );
}
