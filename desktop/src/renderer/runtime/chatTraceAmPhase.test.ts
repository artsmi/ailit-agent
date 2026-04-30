import { describe, expect, it } from "vitest";

import { BROKER_MEMORY_RECALL_UI_LABEL, projectBrokerMemoryRecallActive } from "./chatTraceAmPhase";

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

  it("is true after memory.query_context until context.memory_injected", () => {
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
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 3), CHAT)).toBe(true);
    expect(projectBrokerMemoryRecallActive(rows, CHAT)).toBe(false);
  });

  it("clears after memory.actor_slice_skipped (no inject)", () => {
    const rows: Record<string, unknown>[] = [
      memoryQueryStart(),
      memoryResponse(true, { injected_text: "x", level: "B" }),
      topicFromWork("memory.actor_slice_skipped", { reason: "empty", staleness: "" })
    ];
    expect(projectBrokerMemoryRecallActive(rows.slice(0, 2), CHAT)).toBe(true);
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

  it("exports exact overlay copy", () => {
    expect(BROKER_MEMORY_RECALL_UI_LABEL).toBe("Ailit вспоминает");
  });
});
