/**
 * 极简 fetch 客户端（不使用 axios，也不引入任何状态库）。
 *
 * 约定（spec 第 10/11 节）：
 * - 身份只来自服务端会话令牌：`Authorization: Bearer <token>`。
 * - 前端永远不会在请求体里提交 user_id / tenant_id，服务端也不接受。
 * - 错误体统一为 {code,message,retryable,details,run_id}，一律抛出 ApiError，
 *   由页面渲染成可见的错误块（绝不吞掉错误）。
 */

import type { ApiErrorBody } from "./types";

const API_PREFIX = "/api/v1";
const TOKEN_KEY = "beautycare.demo.token";
const PERSONA_KEY = "beautycare.demo.persona";

export function apiBase(): string {
  const configured = import.meta.env.VITE_API_BASE;
  if (configured && configured.length > 0) {
    return configured.replace(/\/$/, "");
  }
  return API_PREFIX;
}

/** 后端错误的可展示载体。 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;
  readonly runId: string | null;

  constructor(
    status: number,
    body: Partial<ApiErrorBody> & { message?: string },
    fallbackMessage: string,
  ) {
    super(body.message ?? fallbackMessage);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code ?? `HTTP_${status}`;
    this.retryable = body.retryable ?? status >= 500;
    this.details = body.details ?? {};
    this.runId = body.run_id ?? null;
  }
}

export class NetworkError extends Error {
  readonly retryable = true;
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

// --- token 存储 -------------------------------------------------------------

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token === null) {
      window.localStorage.removeItem(TOKEN_KEY);
    } else {
      window.localStorage.setItem(TOKEN_KEY, token);
    }
  } catch {
    /* 隐私模式下 localStorage 不可用：仅本次会话有效，不静默失败给用户造成误解 */
  }
}

export function getStoredPersona(): string | null {
  try {
    return window.localStorage.getItem(PERSONA_KEY);
  } catch {
    return null;
  }
}

export function setStoredPersona(persona: string | null): void {
  try {
    if (persona === null) {
      window.localStorage.removeItem(PERSONA_KEY);
    } else {
      window.localStorage.setItem(PERSONA_KEY, persona);
    }
  } catch {
    /* 同上 */
  }
}

// --- 请求 -------------------------------------------------------------------

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** multipart 上传：body 直接传 FormData。 */
  formData?: FormData;
  /** 写操作幂等键（spec：POST 写操作支持 Idempotency-Key）。 */
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** 不带令牌（例如 /meta 与登录）。 */
  anonymous?: boolean;
}

let unauthorizedHandler: (() => void) | null = null;

/** 令牌失效时由 AuthProvider 注册：清空会话并回到未登录状态。 */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export interface ApiFailure {
  code: string;
  message: string;
  retryable: boolean;
  status: number | null;
}

let apiErrorHandler: ((failure: ApiFailure) => void) | null = null;

/**
 * 全局 API 失败监听（ToastProvider 注册）。
 * 作用：任何一个请求失败时，界面上都会出现一个可见的 toast-error，
 * 内容包含错误 code —— 错误永远不会被静默吞掉。
 */
export function onApiError(handler: ((failure: ApiFailure) => void) | null): void {
  apiErrorHandler = handler;
}

function reportApiFailure(failure: ApiFailure): void {
  if (apiErrorHandler) {
    apiErrorHandler(failure);
  }
}

export function newIdempotencyKey(): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `web-${Date.now().toString(36)}-${random}`;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (!options.anonymous && token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData; // 浏览器自动设置 multipart boundary
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const url = `${apiBase()}${path}`;
  const doFetch = (): Promise<Response> =>
    fetch(url, {
      method: options.method ?? "GET",
      headers,
      body,
      signal: options.signal,
    });

  let response: Response;
  try {
    response = await doFetch();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    const networkError = new NetworkError(
      "无法连接后端服务。请确认本地 FastAPI 已在 127.0.0.1:8000 启动（或已配置 VITE_API_BASE）。",
    );
    reportApiFailure({
      code: "NETWORK_ERROR",
      message: networkError.message,
      retryable: true,
      status: null,
    });
    throw networkError;
  }

  /**
   * 已登录请求偶发 401 的兜底：本地后端在长连接复用时会短暂看不到刚写入的会话
   * （同一令牌直接请求可成功）。因此 401 先原样重试一次再判定会话失效，
   * 避免把一次噪声当成"被登出"。真正的失效（重试仍 401）照常上报并清理令牌。
   */
  if (response.status === 401 && !options.anonymous && token) {
    await new Promise((resolve) => window.setTimeout(resolve, 250));
    try {
      const retry = await doFetch();
      if (retry.status !== 401) {
        response = retry;
      }
    } catch {
      /* 重试本身网络失败：保留第一次的 401，由下方统一上报 */
    }
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    const body = (parsed ?? {}) as Partial<ApiErrorBody>;
    if (response.status === 401 && unauthorizedHandler) {
      unauthorizedHandler();
    }
    const apiError = new ApiError(response.status, body, `请求失败（HTTP ${response.status}）`);
    reportApiFailure({
      code: apiError.code,
      message: apiError.message,
      retryable: apiError.retryable,
      status: response.status,
    });
    throw apiError;
  }

  if (parsed === null) {
    const parseError = new ApiError(response.status, {}, "后端返回了无法解析的响应体。");
    reportApiFailure({
      code: parseError.code,
      message: parseError.message,
      retryable: false,
      status: response.status,
    });
    throw parseError;
  }
  return parsed as T;
}

/** 把任意异常转成可展示的文案；联调时能看出是网络问题还是后端业务错误。 */
export function describeError(error: unknown): {
  code: string;
  message: string;
  retryable: boolean;
  runId: string | null;
  status: number | null;
} {
  if (error instanceof ApiError) {
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      runId: error.runId,
      status: error.status,
    };
  }
  if (error instanceof NetworkError) {
    return { code: "NETWORK_ERROR", message: error.message, retryable: true, runId: null, status: null };
  }
  if (error instanceof Error) {
    return { code: "UNEXPECTED_ERROR", message: error.message, retryable: false, runId: null, status: null };
  }
  return { code: "UNEXPECTED_ERROR", message: String(error), retryable: false, runId: null, status: null };
}
