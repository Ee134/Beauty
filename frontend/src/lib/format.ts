/** 展示层格式化工具（中文优先，时区按用户设置，默认 Asia/Shanghai）。 */

const DEFAULT_TIMEZONE = "Asia/Shanghai";

function toDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined, timezone?: string): string {
  const date = toDate(value);
  if (date === null) {
    return "未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone || DEFAULT_TIMEZONE,
  }).format(date);
}

export function formatDate(value: string | null | undefined, timezone?: string): string {
  const date = toDate(value);
  if (date === null) {
    return "未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeZone: timezone || DEFAULT_TIMEZONE,
  }).format(date);
}

/** 日期或「未知」；未知时附加原因，避免把未知伪装成今天。 */
export function formatDateOrUnknown(
  value: string | null | undefined,
  unknownReason?: string | null,
  timezone?: string,
): string {
  const date = toDate(value);
  if (date === null) {
    return unknownReason ? `未知（${unknownReason}）` : "未知";
  }
  return formatDate(date.toISOString(), timezone);
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "未设置";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** datetime-local 输入需要 "YYYY-MM-DDTHH:mm"。 */
export function toDateTimeLocal(value: string | null | undefined): string {
  const date = toDate(value);
  if (date === null) {
    return "";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export function fromDateTimeLocal(value: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function relativeFromNow(value: string | null | undefined): string {
  const date = toDate(value);
  if (date === null) {
    return "未知";
  }
  const diffMs = date.getTime() - Date.now();
  const minutes = Math.round(diffMs / 60000);
  const abs = Math.abs(minutes);
  const suffix = minutes >= 0 ? "后" : "前";
  if (abs < 60) {
    return `${abs} 分钟${suffix}`;
  }
  if (abs < 60 * 24) {
    return `${Math.round(abs / 60)} 小时${suffix}`;
  }
  return `${Math.round(abs / (60 * 24))} 天${suffix}`;
}

export function truncate(text: string, max = 90): string {
  return text.length <= max ? text : `${text.slice(0, max)}…`;
}
