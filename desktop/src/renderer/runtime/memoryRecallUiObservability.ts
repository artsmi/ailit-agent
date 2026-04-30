import { newMessageId } from "./uuid";

const DESKTOP_GOAL_ID: string = "g-desktop";

export type MemoryRecallUiPhaseCode = "recall_active" | "idle";

export function buildMemoryRecallUiPhaseTraceRow(p: {
  readonly chatId: string;
  readonly sessionId: string;
  readonly phase_code: MemoryRecallUiPhaseCode;
  readonly phrase_id?: string;
  readonly rotation_index?: number;
  readonly namespace?: string;
}): Record<string, unknown> {
  const inner: Record<string, unknown> = {
    session_id: p.sessionId,
    phase_code: p.phase_code
  };
  if (p.phase_code === "recall_active") {
    if (typeof p.phrase_id === "string" && p.phrase_id.length > 0) {
      inner["phrase_id"] = p.phrase_id;
    } else if (typeof p.rotation_index === "number" && Number.isFinite(p.rotation_index)) {
      inner["rotation_index"] = Math.floor(p.rotation_index);
    }
  }
  if (typeof p.namespace === "string" && p.namespace.length > 0) {
    inner["namespace"] = p.namespace;
  }
  const traceId: string = newMessageId();
  const messageId: string = newMessageId();
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: p.chatId,
    broker_id: `broker-${p.chatId}`,
    trace_id: traceId,
    message_id: messageId,
    parent_message_id: null,
    goal_id: DESKTOP_GOAL_ID,
    namespace: typeof p.namespace === "string" && p.namespace.length > 0 ? p.namespace : "",
    from_agent: "User:desktop",
    to_agent: `AgentWork:${p.chatId}`,
    created_at: new Date().toISOString(),
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "memory_recall_ui_phase",
      payload: inner
    }
  };
}
