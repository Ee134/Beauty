/**
 * /chat 对话：消息、结构化卡片渲染、追问、交接入口。
 * 每条助手消息都渲染 TurnOutput 的 cards / pending_actions / questions /
 * citations / memory_changes / uncertainties，而不是把 answer 当纯文本墙。
 */

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { describeError } from "../api/client";
import { getSessionMessages, listChatSessions, postChatMessage } from "../api/endpoints";
import type { ChatMessageRecord, ChatResponse, Question, TurnCard, TurnOutput } from "../api/types";
import { TurnCards } from "../components/cards/TurnCards";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  EmptyState,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDateTime } from "../lib/format";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

interface DisplayMessage {
  id: string;
  role: string;
  content: string;
  cards: TurnCard[];
  citations: TurnOutput["citations"];
  pending_actions: TurnOutput["pending_actions"];
  questions: Question[];
  uncertainties: string[];
  memoryChanges: TurnOutput["memory_changes"];
  mode: string | null;
  modelUnavailable: boolean;
  validationErrors: Array<Record<string, unknown>>;
  createdAt: string | null;
}

function fromRecord(record: ChatMessageRecord): DisplayMessage {
  return {
    id: record.id,
    role: record.role,
    content: record.content,
    cards: (record.cards ?? []) as TurnCard[],
    citations: record.citations ?? [],
    pending_actions: [],
    questions: [],
    uncertainties: [],
    memoryChanges: [],
    mode: null,
    modelUnavailable: false,
    validationErrors: [],
    createdAt: record.created_at,
  };
}

function fromTurn(response: ChatResponse): DisplayMessage {
  const output = response.output;
  return {
    id: output.run_id,
    role: "assistant",
    content: output.answer,
    cards: output.cards,
    citations: output.citations,
    pending_actions: output.pending_actions,
    questions: output.questions,
    uncertainties: output.uncertainties,
    memoryChanges: output.memory_changes,
    mode: output.mode,
    modelUnavailable: output.model_unavailable,
    validationErrors: output.validation_errors,
    createdAt: null,
  };
}

const SUGGESTIONS = [
  "帮我安排柜子里的产品，生成早晚计划",
  "看看我的成分图鉴",
  "我以后每天只想三步",
  "昨晚用了精华后有点刺痛",
  "我的客服工单进度怎么样了",
  "广州现在天气怎么样",
];

export function ChatPage(): JSX.Element {
  const toast = useToast();
  const { refreshContext, refreshMe, me } = useSession();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<ReturnType<typeof describeError> | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const sessions = useAsync(() => listChatSessions(), { deps: [sessionId] });

  const send = useAction<[string], ChatResponse>((text) =>
    postChatMessage({ session_id: sessionId, message: text }),
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  const loadSession = async (id: string) => {
    setSessionId(id);
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const result = await getSessionMessages(id);
      setMessages(result.messages.map(fromRecord));
    } catch (error) {
      setHistoryError(describeError(error));
    } finally {
      setHistoryLoading(false);
    }
  };

  const submit = async (text: string) => {
    const trimmed = text.trim();
    if (trimmed.length === 0) {
      return;
    }
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}`,
        role: "user",
        content: trimmed,
        cards: [],
        citations: [],
        pending_actions: [],
        questions: [],
        uncertainties: [],
        memoryChanges: [],
        mode: null,
        modelUnavailable: false,
        validationErrors: [],
        createdAt: new Date().toISOString(),
      },
    ]);
    setInput("");
    const result = await send.run(trimmed);
    if (result) {
      setSessionId(result.session_id);
      setMessages((prev) => [...prev, fromTurn(result)]);
      toast.show(result.notice);
      void refreshContext();
      void refreshMe();
      sessions.reload();
    }
  };

  return (
    <div className="stack">
      <Panel
        title="对话"
        subtitle="单一编排入口：POST /api/v1/chat/messages，返回标准输出（结构化卡片）"
        actions={
          <>
            <button
              type="button"
              onClick={() => {
                setSessionId(null);
                setMessages([]);
              }}
            >
              新建会话
            </button>
            <button type="button" onClick={sessions.reload}>
              刷新会话列表
            </button>
            <Link className="btn" to="/service">
              客服交接
            </Link>
          </>
        }
      >
        <div className="row tight">
          <Badge tone={me?.mode.model_mode === "mock" ? "mock" : "ok"}>
            MODEL_MODE：{me?.mode.model_mode ?? "未知"}
          </Badge>
          {sessionId ? <Badge>会话：{sessionId.slice(0, 8)}</Badge> : <Badge>新会话（未创建）</Badge>}
          <Badge tone="mock">mock 模式不称真实模型或真实识别能力</Badge>
        </div>
        <Notice>
          模型只能提出草稿；接受计划、提交工单等写操作必须由你在按钮上显式确认（POST accept/submit）。
        </Notice>
      </Panel>

      <Panel title="历史会话" subtitle="GET /chat/sessions">
        <AsyncBlock
          loading={sessions.loading}
          error={sessions.error}
          data={sessions.data}
          onRetry={sessions.reload}
          isEmpty={(data) => data.sessions.length === 0}
          empty="还没有历史会话。发送第一条消息即可创建。"
        >
          {(data) => (
            <div className="row tight">
              {data.sessions.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  className={sessionId === session.id ? "primary" : ""}
                  onClick={() => void loadSession(session.id)}
                >
                  {session.title ?? `会话 ${session.id.slice(0, 8)}`} ·{" "}
                  {session.last_message_at ? formatDateTime(session.last_message_at) : "无消息"}
                </button>
              ))}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="对话记录" subtitle="助手消息会渲染为结构化卡片与可点的确认按钮">
        {historyLoading && <div className="state loading">加载历史消息…</div>}
        {historyError && <ActionFeedback error={historyError} />}
        {messages.length === 0 && !historyLoading ? (
          <EmptyState hint="试试下面的示例，或直接输入你的问题。">
            还没有消息。可以先从示例开始。
          </EmptyState>
        ) : (
          <div className="chat-log">
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                onChanged={() => {
                  void refreshContext();
                  void refreshMe();
                }}
              />
            ))}
          </div>
        )}
        <div ref={bottomRef} />
        <ActionFeedback error={send.error} onRetry={() => void submit(input)} />
      </Panel>

      <Panel title="输入" subtitle="每轮最多两个必要追问；已确认信息不会重复问">
        <div className="row tight" style={{ marginBottom: 8 }}>
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => void submit(suggestion)} disabled={send.running}>
              {suggestion}
            </button>
          ))}
        </div>
        <div className="composer">
          <textarea
            data-testid="chat-input"
            value={input}
            placeholder="例如：帮我安排这些产品 / 用了某产品后不舒服 / 看看成分图鉴"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                void submit(input);
              }
            }}
          />
          <button
            type="button"
            className="primary"
            data-testid="chat-send"
            disabled={send.running || input.trim().length === 0}
            onClick={() => void submit(input)}
          >
            {send.running ? "发送中…" : "发送"}
          </button>
        </div>
        <p className="small muted">按 ⌘/Ctrl + Enter 也可发送。</p>
      </Panel>
    </div>
  );
}

function MessageBubble({
  message,
  onChanged,
}: {
  message: DisplayMessage;
  onChanged: () => void;
}): JSX.Element {
  if (message.role === "user") {
    return (
      <div className="msg user" data-testid="chat-message" data-role="user">
        <div className="msg-meta">我 · {formatDateTime(message.createdAt)}</div>
        {message.content}
      </div>
    );
  }
  const empty =
    message.cards.length === 0 &&
    message.pending_actions.length === 0 &&
    message.questions.length === 0 &&
    message.citations.length === 0;
  return (
    <div className="msg assistant" data-testid="chat-message" data-role="assistant">
      <div className="msg-meta">
        助手 · {formatDateTime(message.createdAt)}
        {message.mode ? ` · mode=${message.mode}` : ""}
      </div>
      <div style={{ whiteSpace: "pre-wrap" }}>{message.content}</div>

      {message.modelUnavailable && (
        <div className="turn-card error" style={{ marginTop: 8 }}>
          <Badge tone="error">模型/提供方不可用</Badge>
          <p className="small">
            本次没有可用模型输出，系统没有伪装成功。可显式切换到 mock 模式继续演示。
          </p>
        </div>
      )}

      {message.validationErrors.length > 0 && (
        <div className="turn-card error" style={{ marginTop: 8 }}>
          <Badge tone="error">输出验证失败 {message.validationErrors.length} 项</Badge>
          <ul className="small">
            {message.validationErrors.map((item, index) => (
              <li key={index}>{JSON.stringify(item)}</li>
            ))}
          </ul>
        </div>
      )}

      <TurnCards
        cards={message.cards}
        pendingActions={message.pending_actions}
        citations={message.citations}
        onChanged={onChanged}
      />

      {message.questions.length > 0 && (
        <div className="turn-card" style={{ marginTop: 10 }}>
          <div className="panel-sub">追问（最多两个必要问题）</div>
          <ol className="small">
            {message.questions.map((question) => (
              <li key={question.key}>
                {question.question}
                {question.why ? `（${question.why}）` : ""}
              </li>
            ))}
          </ol>
        </div>
      )}

      {message.citations.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="small muted">本轮引用 {message.citations.length} 条（点击展开）</summary>
          <ul className="small">
            {message.citations.map((citation) => (
              <li key={citation.citation_id}>
                {citation.title}
                {citation.locator ? ` · ${citation.locator}` : ""}
                {citation.is_demo ? "（DEMO 演示来源）" : ""}
              </li>
            ))}
          </ul>
        </details>
      )}

      {message.memoryChanges.length > 0 && (
        <div className="turn-card" style={{ marginTop: 8 }}>
          <div className="panel-sub">记忆变化</div>
          <ul className="small">
            {message.memoryChanges.map((change, index) => (
              <li key={index}>
                [{change.type}] {change.key ?? change.entity_id ?? "—"} = {JSON.stringify(change.value)}（
                {change.status ?? "—"}）
              </li>
            ))}
          </ul>
          <div className="row tight">
            <Link className="btn" to="/memory">
              到记忆页修改或删除
            </Link>
          </div>
        </div>
      )}

      {message.uncertainties.length > 0 && (
        <div className="turn-card" style={{ marginTop: 8 }}>
          <div className="panel-sub">不确定性</div>
          <ul className="small">
            {message.uncertainties.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {empty && <p className="small muted">本轮没有结构化卡片。</p>}
    </div>
  );
}
