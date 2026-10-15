/**
 * 通用展示组件：加载 / 错误（含 code/message/retryable + 重试）/ 空状态，
 * 以及徽标、面板、提示条。全部手写，不引入 UI 框架。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { onApiError, type ApiFailure, type describeError } from "../api/client";

export type DescribedError = ReturnType<typeof describeError>;

export type BadgeTone = "default" | "accent" | "warn" | "error" | "ok" | "mock";

/**
 * 徽标。除了 tone/title 之外的所有属性（尤其是 data-testid / data-*）
 * 都会原样透传到 <span>，否则调用方传的 testid 会被静默丢弃。
 */
export function Badge({
  children,
  tone = "default",
  title,
  className,
  ...rest
}: { children: ReactNode; tone?: BadgeTone; title?: string } & Omit<
  HTMLAttributes<HTMLSpanElement>,
  "children" | "title"
>): JSX.Element {
  const classes = ["badge", tone === "default" ? null : tone, className]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes} title={title} {...rest}>
      {children}
    </span>
  );
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  tight = false,
  testId,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  tight?: boolean;
  /** 稳定的 E2E 钩子（data-testid），不参与样式。 */
  testId?: string;
}): JSX.Element {
  return (
    <section className={tight ? "panel tight" : "panel"} data-testid={testId}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <div className="panel-title">{title}</div>}
            {subtitle && <div className="panel-sub">{subtitle}</div>}
          </div>
          {actions && <div className="row tight">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/** 提示条：优先复用后端返回的 notice 文案。 */
export function Notice({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "mock";
}): JSX.Element {
  return <p className={tone === "mock" ? "notice mock" : "notice"}>{children}</p>;
}

export function Loading({ label = "加载中…" }: { label?: string }): JSX.Element {
  return (
    <div className="state loading" role="status" aria-live="polite">
      {label}
    </div>
  );
}

/** 统一错误块：显示 {code,message,retryable}，并提供重试按钮。 */
export function ErrorState({
  error,
  onRetry,
  title = "加载失败",
}: {
  error: DescribedError;
  onRetry?: () => void;
  title?: string;
}): JSX.Element {
  return (
    <div className="state error" role="alert">
      <div>
        <strong>{title}</strong>
      </div>
      <div>
        {error.message}
        {error.code ? `（${error.code}）` : ""}
        {error.retryable ? " · 该错误可重试" : " · 该错误不可重试"}
      </div>
      {error.status !== null && <div className="error-detail">HTTP {error.status}</div>}
      {error.runId && <div className="error-detail mono">run_id: {error.runId}</div>}
      {onRetry && (
        <div style={{ marginTop: 8 }}>
          <button type="button" onClick={onRetry}>
            重试
          </button>
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  children,
  hint,
}: {
  children: ReactNode;
  hint?: ReactNode;
}): JSX.Element {
  return (
    <div className="state empty">
      <div>{children}</div>
      {hint && <div className="error-detail">{hint}</div>}
    </div>
  );
}

/**
 * 异步区块：一次性处理 loading / error（带重试）/ empty / 正常渲染。
 * 每个异步动作都必须经过它，确保四态都存在。
 */
export function AsyncBlock<T>({
  loading,
  error,
  data,
  onRetry,
  isEmpty,
  empty,
  loadingLabel,
  children,
}: {
  loading: boolean;
  error: DescribedError | null;
  data: T | null;
  onRetry?: () => void;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  loadingLabel?: string;
  children: (data: T) => ReactNode;
}): JSX.Element {
  if (loading && data === null) {
    return <Loading label={loadingLabel} />;
  }
  if (error && data === null) {
    return <ErrorState error={error} onRetry={onRetry} />;
  }
  if (data === null) {
    return <EmptyState>{empty ?? "暂无数据。"}</EmptyState>;
  }
  if (isEmpty && isEmpty(data)) {
    return (
      <>
        {error && <ErrorState error={error} onRetry={onRetry} title="刷新失败（显示的是上次结果）" />}
        <EmptyState>{empty ?? "暂无数据。"}</EmptyState>
      </>
    );
  }
  return (
    <>
      {error && <ErrorState error={error} onRetry={onRetry} title="刷新失败（显示的是上次结果）" />}
      {children(data)}
    </>
  );
}

// --- 轻量 toast（用于确认动作的结果反馈，手写实现） -------------------------

interface ToastValue {
  show: (message: string) => void;
}

const ToastContext = createContext<ToastValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }): JSX.Element {
  const [message, setMessage] = useState<string | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const show = useCallback((next: string) => {
    setMessage(next);
    window.setTimeout(() => setMessage(null), 4200);
  }, []);

  // 任何 API 请求失败都会在这里出现可见提示，并带上错误 code（错误不被吞掉）。
  useEffect(() => {
    onApiError((next) => {
      setFailure(next);
      window.setTimeout(() => {
        setFailure((current) => (current === next ? null : current));
      }, 8000);
    });
    return () => onApiError(null);
  }, []);

  const value = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {message && (
        <div className="toast" role="status" aria-live="polite">
          {message}
        </div>
      )}
      {failure && (
        <div className="toast" role="alert" data-testid="toast-error">
          {failure.code}
          {failure.status !== null ? ` (HTTP ${failure.status})` : ""}：{failure.message}
          {failure.retryable ? " · 可重试" : " · 不可重试"}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastValue {
  const value = useContext(ToastContext);
  if (value === null) {
    return { show: () => undefined };
  }
  return value;
}

/** 关键值展示。 */
export function Stat({ label, value }: { label: string; value: ReactNode }): JSX.Element {
  return (
    <div className="stat-item">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function KeyValue({ items }: { items: Array<[string, ReactNode]> }): JSX.Element {
  return (
    <dl className="kv">
      {items.map(([key, value]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 提交动作的错误/成功提示（用于表单与按钮动作）。 */
export function ActionFeedback({
  error,
  message,
  onRetry,
}: {
  error: DescribedError | null;
  message?: string | null;
  onRetry?: () => void;
}): JSX.Element | null {
  if (error) {
    return <ErrorState error={error} onRetry={onRetry} title="操作失败" />;
  }
  if (message) {
    return <div className="state">{message}</div>;
  }
  return null;
}
