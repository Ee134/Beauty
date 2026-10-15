/**
 * 会话与「服务上下文」共享状态。
 *
 * 身份交换流程（本地演示）：选择 persona -> POST /api/v1/auth/demo-session
 * -> {token,user} -> token 存 localStorage -> 之后所有请求带 Authorization: Bearer。
 * 前端永远不会提交 user_id；服务端也不接受 body 里的 user_id。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  describeError,
  getStoredPersona,
  getToken,
  onUnauthorized,
  setStoredPersona,
  setToken,
} from "../api/client";
import { createDemoSession, getInboxSummary, getMe, listReviewPrompts } from "../api/endpoints";
import type { InboxSummaryResponse, MeResponse, PersonaCode, ReviewPromptRecord } from "../api/types";

export interface SessionContextValue {
  token: string | null;
  persona: string | null;
  me: MeResponse | null;
  reviewPrompts: ReviewPromptRecord[];
  inbox: InboxSummaryResponse | null;
  loading: boolean;
  /** 登录/拉取「我」的信息失败时的可见错误。 */
  error: ReturnType<typeof describeError> | null;
  /** 上下文面板数据的独立错误（不影响主页面）。 */
  contextError: ReturnType<typeof describeError> | null;
  login: (persona: PersonaCode) => Promise<boolean>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  refreshContext: () => Promise<void>;
  /** 上次成功刷新「我」的时间。 */
  lastLoadedAt: string | null;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }): JSX.Element {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [persona, setPersonaState] = useState<string | null>(() => getStoredPersona());
  const [me, setMe] = useState<MeResponse | null>(null);
  const [reviewPrompts, setReviewPrompts] = useState<ReviewPromptRecord[]>([]);
  const [inbox, setInbox] = useState<InboxSummaryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(() => getToken() !== null);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);
  const [contextError, setContextError] = useState<ReturnType<typeof describeError> | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setStoredPersona(null);
    setTokenState(null);
    setPersonaState(null);
    setMe(null);
    setReviewPrompts([]);
    setInbox(null);
    setError(null);
    setContextError(null);
  }, []);

  // 令牌被服务端判定失效时统一回到未登录状态（不静默重试）。
  useEffect(() => {
    onUnauthorized(() => {
      setToken(null);
      setStoredPersona(null);
      setTokenState(null);
      setPersonaState(null);
      setMe(null);
      setReviewPrompts([]);
      setInbox(null);
    });
    return () => onUnauthorized(null);
  }, []);

  const refreshMe = useCallback(async () => {
    if (!getToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const value = await getMe();
      if (!mountedRef.current) {
        return;
      }
      setMe(value);
      setError(null);
      setLastLoadedAt(new Date().toISOString());
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      if (err instanceof ApiError && err.status === 401) {
        // 令牌失效：onUnauthorized 已经清理状态，这里只保留可见错误。
        setMe(null);
        setError(describeError(err));
      } else {
        setError(describeError(err));
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  const refreshContext = useCallback(async () => {
    if (!getToken()) {
      setReviewPrompts([]);
      setInbox(null);
      return;
    }
    try {
      const [prompts, summary] = await Promise.all([listReviewPrompts(), getInboxSummary()]);
      if (!mountedRef.current) {
        return;
      }
      setReviewPrompts(prompts.prompts);
      setInbox(summary);
      setContextError(null);
    } catch (err) {
      if (mountedRef.current) {
        setContextError(describeError(err));
      }
    }
  }, []);

  useEffect(() => {
    if (token) {
      void refreshMe();
      void refreshContext();
    } else {
      setMe(null);
      setReviewPrompts([]);
      setInbox(null);
      setLoading(false);
    }
  }, [token, refreshMe, refreshContext]);

  const login = useCallback(async (nextPersona: PersonaCode): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const session = await createDemoSession(nextPersona);
      setToken(session.token);
      setStoredPersona(nextPersona);
      setTokenState(session.token);
      setPersonaState(nextPersona);
      // me / context 由 token 变化的 effect 统一拉取。
      return true;
    } catch (err) {
      setError(describeError(err));
      setLoading(false);
      return false;
    }
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      token,
      persona,
      me,
      reviewPrompts,
      inbox,
      loading,
      error,
      contextError,
      login,
      logout,
      refreshMe,
      refreshContext,
      lastLoadedAt,
    }),
    [
      token,
      persona,
      me,
      reviewPrompts,
      inbox,
      loading,
      error,
      contextError,
      login,
      logout,
      refreshMe,
      refreshContext,
      lastLoadedAt,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("useSession 必须在 SessionProvider 内使用");
  }
  return value;
}
