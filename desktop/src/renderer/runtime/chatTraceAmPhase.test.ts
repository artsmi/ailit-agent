import { describe, expect, it } from "vitest";

import {
  isMemoryQueryContextResponseToWorkForUi,
  projectBrokerMemoryRecallActive
} from "./chatTraceAmPhase";
import {
  BROKER_MEMORY_RECALL_STYLE_TOKEN,
  buildBrokerMemoryRecallUiPhase,
  projectBrokerMemoryRecallPhase,
  RECALL_PHRASE_ROTATION_MS,
  RECALL_UI_PHRASE_WHITELIST
} from "./memoryRecallUiPhaseProjection";
import { buildMemoryRecallUiPhaseTraceRow } from "./memoryRecallUiObservability";

const CHAT: string = "chat-a";

function topicFromWork(eventName: string, inner: Record<string, unknown>): Record<string, unknown> {
  return {
    type: "topic.publish",
    chat_id: CHAT,
    from_agent: `AgentWork:${CHAT}`,
    message_id: `m-${eventName}-${Math.random().toString(36).slice(2, 8)}`,
    created_at: new Date().toISOString(),
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: eventName,
      payload: inner
    }
  };
}

function memoryQueryStart(): Record<string, unknown> {
  return {
    type: "service.request",
    chat_id: CHAT,
    from_agent: `AgentWork:${CHAT}`,
    to_agent: "AgentMemory:global",
    message_id: "mq-start",
    created_at: new Date().toISOString(),
    payload: { service: "memory.query_context", query_id: "q1" }
  };
}

function memoryResponse(ok: boolean, memorySlice: Record<string, unknown> | null): Record<string, unknown> {
  return {
    type: "service.request",
    chat_id: CHAT,
    from_agent: "AgentMemory:global",
    to_agent: `AgentWork:${CHAT}`,
    ok,
    message_id: "mq-resp",
    created_at: new Date().toISOString(),
    payload: {
      service: "memory.query_context",
      memory_slice: memorySlice
    }
  };
}

/** Прод-форма broker: ответ без `payload.service`, только `memory_slice` (C1). */
function memoryResponseProdShape(ok: boolean): Record<string, unknown> {
  return {
    type: "service.request",
    chat_id: CHAT,
    from_agent: "AgentMemory:global",
    to_agent: `AgentWork:${CHAT}`,
    ok,
    message_id: "mq-resp-prod",
    created_at: new Date().toISOString(),
    payload: {
      memory_slice: { kind: "memory_slice", schema: "memory.slice.v1", level: "B", node_ids: [] }
    }
  };
}

function userPromptRow(): Record<string, unknown> {
  return {
    type: "action.start",
    chat_id: CHAT,
    from_agent: "User:desktop",
    to_agent: `AgentWork:${CHAT}`,
    message_id: "u1",
    created_at: new Date().toISOString(),
    payload: { action: "work.handle_user_prompt", prompt: "hi" }
  };
}

describe("projectBrokerMemoryRecallActive", () => {
  it("fixture memoryQueryStart matches start-row predicate", () => {
    const row: Record<string, unknown> = memoryQueryStart();
    expect(row["chat_id"]).toBe(CHAT);
    expect(row["type"]).toBe("service.request");
    expect(row["from_agent"]).toBe(`AgentWork:${CHAT}`);
    expect(String((row["payload"] as Record<string, unknown>)["service"])).toBe("memory.query_context");
  });

  it("is false for empty trace", () => {
    expect(projectBrokerMemoryRecallActive([], CHAT)).toBe(false);
  });

  it("is false when AM was never queried", () => {
    const rows: Record<string, unknown>[] = [
      userPromptRow(),
      topicFromWork("assistant.thinking_delta", { schema: "x", text_mode: "incremental", delta: "…" })
    ];
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });

  it("is true after memory.query_context until Memory→Work response (not until inject)", () => {
    const rows: Record<string, unknown>[] = [
      userPromptRow(),
      memoryQueryStart(),
      memoryResponse(true, { injected_text: "ctx", level: "B" }),
      topicFromWork("context.memory_injected", {
        schema: "context.memory_injected.v2",
        usage_state: "estimated",
        project_refs: []
      })
    ];
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 2), CHAT)).toBe(true);
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 3), CHAT)).toBe(false);
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });

  it("clears after memory.actor_slice_skipped only if still awaiting (response already closed recall)", () => {
    const rows: Record<string, unknown>[] = [
      memoryQueryStart(),
      memoryResponse(true, { injected_text: "x", level: "B" }),
      topicFromWork("memory.actor_slice_skipped", { reason: "empty", staleness: "" })
    ];
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 2), CHAT)).toBe(false);
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });

  it("clears on failed memory response without inject", () => {
    const rows: Record<string, unknown>[] = [
      memoryQueryStart(),
      memoryResponse(false, { injected_text: "x" })
    ];
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 1), CHAT)).toBe(true);
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });

  it("clears on memory.actor_unavailable while awaiting response", () => {
    const rows: Record<string, unknown>[] = [
      memoryQueryStart(),
      topicFromWork("memory.actor_unavailable", { reason: "broker_request_failed", fallback: "none" })
    ];
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 1), CHAT)).toBe(true);
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });

  it("ignores rows for other chat_id", () => {
    const otherStart: Record<string, unknown> = {
      ...memoryQueryStart(),
      chat_id: "other"
    };
    expect(projectBrokerMemoryRecallActive([otherStart], CHAT)).toBe(false);
  });

  it("resets stuck phase on new user_prompt", () => {
    const rows: Record<string, unknown>[] = [
      memoryQueryStart(),
      memoryResponse(true, { injected_text: "x", level: "B" }),
      userPromptRow()
    ];
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });

  it("detects audit-shaped memory.response to_agent_work for UI close", () => {
    const row: Record<string, unknown> = {
      chat_id: CHAT,
      event: "memory.response",
      topic: "to_agent_work",
      service: "memory.query_context",
      request_id: "r1"
    };
    expect(isMemoryQueryContextResponseToWorkForUi(row, CHAT)).toBe(true);
  });

  it("clears recall when Memory→Work payload has memory_slice but no service (prod broker)", () => {
    const rows: Record<string, unknown>[] = [
      userPromptRow(),
      memoryQueryStart(),
      memoryResponseProdShape(true),
      topicFromWork("context.memory_injected", {
        schema: "context.memory_injected.v2",
        usage_state: "estimated",
        project_refs: []
      })
    ];
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 2), CHAT)).toBe(true);
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 3), CHAT)).toBe(false);
    expect(isMemoryQueryContextResponseToWorkForUi(rows[2]!, CHAT)).toBe(true);
  });

  it("clears recall on prod-shaped response with agent_memory_result only", () => {
    const row: Record<string, unknown> = {
      type: "service.request",
      chat_id: CHAT,
      from_agent: "AgentMemory:global",
      to_agent: `AgentWork:${CHAT}`,
      ok: true,
      message_id: "mq-amr-only",
      created_at: new Date().toISOString(),
      payload: {
        agent_memory_result: { schema_version: "agent_memory_result.v1", status: "complete", results: [] }
      }
    };
    const rows: Record<string, unknown>[] = [memoryQueryStart(), row];
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 1), CHAT)).toBe(true);
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });
});

describe("projectBrokerMemoryRecallPhase / recall ui projection", () => {
  it("whitelist has 40 recall phrases", () => {
    expect(RECALL_UI_PHRASE_WHITELIST.length).toBe(40);
  });

  it("uses candy-code style token for status projection", () => {
    const p = buildBrokerMemoryRecallUiPhase(true, 0);
    expect(p.styleToken).toBe(BROKER_MEMORY_RECALL_STYLE_TOKEN);
    expect(BROKER_MEMORY_RECALL_STYLE_TOKEN).toBe("--candy-code");
  });

  it("phrase index wraps modulo whitelist length", () => {
    const n = RECALL_UI_PHRASE_WHITELIST.length;
    const p = buildBrokerMemoryRecallUiPhase(true, n + 1);
    expect(p.phraseIndex).toBe(1 % n);
  });

  it("RECALL_PHRASE_ROTATION_MS aliases min rotation interval (2s)", () => {
    expect(RECALL_PHRASE_ROTATION_MS).toBe(2000);
  });

  it("projectBrokerMemoryRecallPhase combines trace active with phrase slot", () => {
    const rows: Record<string, unknown>[] = [memoryQueryStart()];
    const off = projectBrokerMemoryRecallPhase([], CHAT, 3);
    expect(off.active).toBe(false);
    expect(off.phraseIndex).toBe(0);
    const on = projectBrokerMemoryRecallPhase(rows, CHAT, 3);
    expect(on.active).toBe(true);
    expect(on.phraseIndex).toBe(3 % RECALL_UI_PHRASE_WHITELIST.length);
  });

  it("buildMemoryRecallUiPhaseTraceRow publishes memory_recall_ui_phase topic payload", () => {
    const row: Record<string, unknown> = buildMemoryRecallUiPhaseTraceRow({
      chatId: CHAT,
      sessionId: "sess-1",
      phase_code: "recall_active",
      phrase_id: "recall_remembers_v1"
    });
    const pl: Record<string, unknown> = row["payload"] as Record<string, unknown>;
    expect(pl["event_name"]).toBe("memory_recall_ui_phase");
    const inner: Record<string, unknown> = pl["payload"] as Record<string, unknown>;
    expect(inner["session_id"]).toBe("sess-1");
    expect(inner["phase_code"]).toBe("recall_active");
    expect(inner["phrase_id"]).toBe("recall_remembers_v1");
    expect(inner).not.toHaveProperty("rotation_index");
  });
});
