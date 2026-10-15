/**
 * 统一的异步状态 hook：每个异步动作都有 loading / error / retry / empty 四态。
 * 错误一律保存在 state 中由页面渲染，不做静默吞掉。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { describeError } from "../api/client";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: ReturnType<typeof describeError> | null;
  /** 空状态判定由调用方通过 isEmpty 决定；这里只暴露 reload 能力。 */
  reload: () => void;
  setData: (next: T | null) => void;
}

export interface UseAsyncOptions {
  /** 为 false 时不发请求（例如未登录）。 */
  enabled?: boolean;
  /** 依赖变化时重新拉取。 */
  deps?: ReadonlyArray<unknown>;
}

export function useAsync<T>(
  loader: () => Promise<T>,
  options: UseAsyncOptions = {},
): AsyncState<T> {
  const { enabled = true } = options;
  const deps = options.deps ?? [];
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);
  const [nonce, setNonce] = useState(0);
  const mounted = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    loaderRef
      .current()
      .then((result) => {
        if (!cancelled && mounted.current) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled && mounted.current) {
          setError(describeError(err));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce, ...deps]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, loading, error, reload, setData };
}

/** 一次性动作（提交/删除/确认）的状态封装。 */
export interface ActionState<TArgs extends unknown[], TResult> {
  run: (...args: TArgs) => Promise<TResult | null>;
  running: boolean;
  error: ReturnType<typeof describeError> | null;
  result: TResult | null;
  reset: () => void;
}

export function useAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
): ActionState<TArgs, TResult> {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);
  const [result, setResult] = useState<TResult | null>(null);
  const actionRef = useRef(action);
  actionRef.current = action;

  const run = useCallback(async (...args: TArgs): Promise<TResult | null> => {
    setRunning(true);
    setError(null);
    try {
      const value = await actionRef.current(...args);
      setResult(value);
      setRunning(false);
      return value;
    } catch (err) {
      setError(describeError(err));
      setRunning(false);
      return null;
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setResult(null);
  }, []);

  return { run, running, error, result, reset };
}
