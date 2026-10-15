/**
 * 枚举的中文标签与「合规措辞」常量。
 *
 * 重要：成分图鉴/主动服务的措辞全部复用后端返回值（user_signal.statement、
 * combination_notes[].text、notice 等）。这里只放中性的界面标签，
 * 绝不出现「过敏」「导致」「避免」这类断言（spec 8.1.1 / 8.1.2 / 第 22 节）。
 */

export const PERIOD_LABELS: Record<string, string> = {
  morning: "早间",
  evening: "晚间",
  both: "早晚均可用",
  as_needed: "按需使用",
  weekly: "每周固定",
  unknown: "时段未知",
};

export function periodLabel(period: string): string {
  return PERIOD_LABELS[period] ?? period;
}

export const LIFECYCLE_LABELS: Record<string, string> = {
  unopened: "未开封",
  opened: "已开封",
  finished: "已用完",
  discarded: "已丢弃",
  unknown: "开封状态未知",
};

export function lifecycleLabel(status: string): string {
  return LIFECYCLE_LABELS[status] ?? status;
}

export const USAGE_LABELS: Record<string, string> = {
  active: "使用中",
  paused: "已暂停",
  unknown: "使用状态未知",
};

export function usageLabel(status: string): string {
  return USAGE_LABELS[status] ?? status;
}

export const PLAN_STATUS_LABELS: Record<string, string> = {
  draft: "草稿（未生效）",
  active: "当前生效",
  superseded: "已被新版本取代",
  rejected: "已拒绝",
  stale: "需要复核",
};

export function planStatusLabel(status: string): string {
  return PLAN_STATUS_LABELS[status] ?? status;
}

export const MATCH_STATUS_LABELS: Record<string, string> = {
  matched: "已匹配目录",
  low_confidence: "低置信匹配",
  custom: "自定义名称（未匹配目录）",
};

export function matchStatusLabel(status: string): string {
  return MATCH_STATUS_LABELS[status] ?? status;
}

export const TICKET_STATUS_LABELS: Record<string, string> = {
  draft: "草稿（未提交）",
  submitted: "已提交到本地演示工作台",
  awaiting_user: "等待你补充信息",
  in_review: "演示工作台处理中",
  resolved: "演示工作台标记已处理",
  cancelled: "已取消",
};

export function ticketStatusLabel(status: string): string {
  return TICKET_STATUS_LABELS[status] ?? status;
}

export const MESSAGE_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  approved: "已批准",
  queued: "排队中",
  sent: "已发送（内应用）",
  read: "已读",
  expired: "已过期",
  cancelled: "已取消",
};

export function messageStatusLabel(status: string): string {
  return MESSAGE_STATUS_LABELS[status] ?? status;
}

export const MESSAGE_ACTION_LABELS: Record<string, string> = {
  read: "标记已读",
  adopt_intent: "采用（仅记录意向）",
  reject: "不需要",
  later: "稍后",
  not_helpful: "无帮助",
  mute_type: "关闭此类",
};

export const REVIEW_OPTION_LABELS: Record<string, string> = {
  pause: "暂停该步骤",
  keep: "保持不变",
  adjust: "再调整",
};

export function reviewOptionLabel(option: string): string {
  return REVIEW_OPTION_LABELS[option] ?? option;
}

/** 稳定的 E2E 钩子：复核询问的三个选项按钮。 */
export const REVIEW_OPTION_TEST_IDS: Record<string, string> = {
  pause: "review-prompt-pause",
  keep: "review-prompt-keep",
  adjust: "review-prompt-adjust",
};

export const COMBINATION_OPTION_LABELS: Record<string, string> = {
  keep: "保留",
  space_out: "间隔",
  remove_one: "移除",
};

export function combinationOptionLabel(option: string): string {
  return COMBINATION_OPTION_LABELS[option] ?? option;
}

/** 稳定的 E2E 钩子：组合提示的三个选项按钮。 */
export const COMBINATION_OPTION_TEST_IDS: Record<string, string> = {
  keep: "combination-option-keep",
  space_out: "combination-option-space_out",
  remove_one: "combination-option-remove_one",
};

export const HANDOFF_STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "submitted", label: "submitted（已提交到演示工作台）" },
  { value: "awaiting_user", label: "awaiting_user（等待用户）" },
  { value: "in_review", label: "in_review（处理中）" },
  { value: "resolved", label: "resolved（演示工作台标记已处理）" },
  { value: "cancelled", label: "cancelled（已取消）" },
];

export const PENDING_ACTION_LABELS: Record<string, string> = {
  accept_routine: "接受计划",
  submit_handoff: "提交工单",
  confirm_import: "确认入柜",
  confirm_memory: "确认记忆",
  review_routine: "复核计划",
  add_owned_product: "添加产品",
  open_atlas: "查看成分图鉴",
  provide_missing_info: "补充缺失信息",
};

/** 演示环境统一标识文案（界面必须显著标注 mock/演示）。 */
export const DEMO_NOTICE =
  "本地演示数据：产品目录含虚构 DEMO SKU；识别、天气、推送与品牌台均为本地模拟，未接入真实品牌、订单、OCR 或推送通道。";

/** 成分图鉴数据状态文案（spec 8.1.1）。 */
export const ATLAS_DATA_STATUS_LABELS: Record<string, string> = {
  approved: "已审核来源",
  insufficient: "暂无充分信息",
  pending_review: "信息存在冲突，待审核",
  pending: "待审核",
};

export function atlasDataStatusLabel(status: string): string {
  return ATLAS_DATA_STATUS_LABELS[status] ?? status;
}

export const DROPPED_EXTENSION_REASON_LABELS: Record<string, string> = {
  SOURCE_NOT_APPROVED: "来源未审核/缺失",
  SOURCE_CONFLICT: "来源冲突",
  NOT_RELATED: "与成分功效或致敏性无直接关系",
  MEDICAL_CLAIM: "构成医疗/诊断表述",
};

export function droppedReasonLabel(reason: string): string {
  return DROPPED_EXTENSION_REASON_LABELS[reason] ?? reason;
}

export const SERVICE_TYPE_LABELS: Record<string, string> = {
  travel_support: "旅行提醒",
  outdoor_support: "户外活动提醒",
  environment_checkin: "环境变化询问",
  service_progress: "工单进度提醒",
  routine_followup: "计划跟进",
};

export function serviceTypeLabel(type: string): string {
  return SERVICE_TYPE_LABELS[type] ?? type;
}

export const CHANNEL_LABELS: Record<string, string> = {
  in_app: "内应用消息",
  web_push: "Web Push（浏览器推送）",
  native_push: "原生 App 推送（P1，未交付）",
};

export function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] ?? channel;
}
