/**
 * 内联的复核询问卡片：按钮调用 POST /api/v1/review-prompts/{id}/decision。
 * 首页与计划页共用。
 */

import { useState } from "react";
import { reviewDecision } from "../api/endpoints";
import type { ReviewDecisionResponse, ReviewPromptRecord } from "../api/types";
import { REVIEW_OPTION_TEST_IDS, reviewOptionLabel } from "../lib/labels";
import { useAction } from "../state/useAsync";
import { ActionFeedback, Badge, useToast } from "./ui";

export function ReviewPromptCardLite({
  prompt,
  onDecided,
}: {
  prompt: ReviewPromptRecord;
  onDecided?: () => void;
}): JSX.Element {
  const [note, setNote] = useState("");
  const toast = useToast();
  const action = useAction<[("pause" | "keep" | "adjust")], ReviewDecisionResponse>((choice) =>
    reviewDecision(prompt.id, { action: choice, note: note || null }),
  );

  const run = async (choice: "pause" | "keep" | "adjust") => {
    const result = await action.run(choice);
    if (result) {
      toast.show(result.message ?? result.notice);
      onDecided?.();
    }
  };

  return (
    <div className="turn-card accent">
      <div className="row tight">
        <Badge tone="warn">待复核</Badge>
        <span className="small muted">创建于 {prompt.created_at.slice(0, 16).replace("T", " ")}</span>
      </div>
      <p style={{ marginTop: 6 }}>{prompt.question}</p>
      <input
        type="text"
        placeholder="补充说明（可选）"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        style={{ marginBottom: 6 }}
      />
      <div className="row tight">
        {(prompt.options.length > 0 ? prompt.options : ["pause", "keep", "adjust"]).map((option) => (
          <button
            key={option}
            type="button"
            data-testid={REVIEW_OPTION_TEST_IDS[option]}
            className={option === "pause" ? "primary" : ""}
            disabled={action.running}
            onClick={() => void run(option as "pause" | "keep" | "adjust")}
          >
            {reviewOptionLabel(option)}
          </button>
        ))}
      </div>
      {action.running && <p className="small muted">提交中…</p>}
      <ActionFeedback error={action.error} />
      {action.result?.questions && action.result.questions.length > 0 && (
        <ul className="small">
          {action.result.questions.map((question) => (
            <li key={question.key}>
              {question.question}
              {question.why ? `（${question.why}）` : ""}
            </li>
          ))}
        </ul>
      )}
      {action.error === null && action.result !== null && (
        <p className="small muted">
          {action.result.plan_changed
            ? "已生成新草稿，请到计划页显式接受。"
            : "计划未发生变化。"}
        </p>
      )}
    </div>
  );
}
