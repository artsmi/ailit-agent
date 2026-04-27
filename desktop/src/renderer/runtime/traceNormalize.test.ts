import { describe, expect, it } from "vitest";

import { dedupKeyForRow, RuntimeTraceNormalizer } from "./traceNormalize";

describe("RuntimeTraceNormalizer", () => {
  it("classifies response vs request for action.start", () => {
    const n: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();
    const req: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      runtime_id: "r1",
      chat_id: "c1",
      broker_id: "b1",
      trace_id: "t1",
      message_id: "m-req",
      parent_message_id: null,
      goal_id: "g1",
      namespace: "ns",
      from_agent: "User:desktop",
      to_agent: null,
      created_at: "2026-01-01T00:00:00Z",
      type: "action.start",
      payload: { action: "work.handle_user_prompt", prompt: "hi" }
    };
    const res: Record<string, unknown> = {
      ...req,
      ok: true,
      payload: { action: "work.handle_user_prompt", action_id: "a1" },
      error: null
    };
    expect(n.normalizeLine(req).kind).toBe("user_prompt");
    expect(n.normalizeLine(res).kind).toBe("assistant_response");
  });

  it("redacts sensitive keys in raw copy", () => {
    const n: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      runtime_id: "r1",
      chat_id: "c1",
      broker_id: "b1",
      trace_id: "t1",
      message_id: "m1",
      parent_message_id: null,
      goal_id: "g1",
      namespace: "ns",
      from_agent: "x",
      to_agent: null,
      created_at: "2026-01-01T00:00:00Z",
      type: "action.start",
      ok: true,
      payload: { token: "secret" }
    };
    const out = n.normalizeLine(row);
    expect((out.raw["payload"] as { token: string }).token).toBe("[REDACTED]");
  });
});

describe("dedupKeyForRow", () => {
  it("uses message_id when present", () => {
    expect(dedupKeyForRow({ message_id: "a" })).toBe("id:a");
  });
});

describe("text_mode in topic.publish", () => {
  it("reads text_mode incremental for assistant.thinking", () => {
    const n: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      type: "topic.publish",
      message_id: "env-1",
      chat_id: "c1",
      namespace: "ns",
      from_agent: "a",
      to_agent: null,
      created_at: "2026-01-01T00:00:00Z",
      payload: {
        type: "topic.publish",
        topic: "chat",
        event_name: "assistant.thinking",
        payload: {
          message_id: "asst-1",
          text: "x",
          text_mode: "incremental"
        }
      }
    };
    const out: ReturnType<RuntimeTraceNormalizer["normalizeLine"]> = n.normalizeLine(row);
    expect(out.kind).toBe("assistant_thinking_delta");
    expect(out.textMode).toBe("incremental");
  });
});

describe("action.completed / action.failed topic.publish", () => {
  it("maps action.completed to turn_completed", () => {
    const n: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      type: "topic.publish",
      message_id: "evt-ac",
      chat_id: "c1",
      namespace: "ns",
      from_agent: "AgentWork:c1",
      to_agent: null,
      created_at: "2026-01-01T00:00:01Z",
      payload: {
        type: "topic.publish",
        topic: "chat",
        event_name: "action.completed",
        payload: {
          action: "work.handle_user_prompt",
          action_id: "a1",
          result: { ok: true }
        }
      }
    };
    const out = n.normalizeLine(row);
    expect(out.kind).toBe("turn_completed");
  });

  it("maps action.failed to turn_failed with error text", () => {
    const n: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      type: "topic.publish",
      message_id: "evt-af",
      chat_id: "c1",
      namespace: "ns",
      from_agent: "AgentWork:c1",
      to_agent: null,
      created_at: "2026-01-01T00:00:02Z",
      payload: {
        type: "topic.publish",
        topic: "chat",
        event_name: "action.failed",
        payload: {
          action: "work.handle_user_prompt",
          action_id: "a1",
          error: "boom"
        }
      }
    };
    const out = n.normalizeLine(row);
    expect(out.kind).toBe("turn_failed");
    expect(out.humanLine).toBe("boom");
  });
});

describe("G9.9.2 degradation: unknown events do not throw", () => {
  it("maps unknown type to kind unknown with human line", () => {
    const n: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();
    const row: Record<string, unknown> = {
      type: "totally.unknown.v99",
      message_id: "m1",
      chat_id: "c1",
      namespace: "ns",
      created_at: "2026-01-01T00:00:00Z",
      from_agent: "X",
      to_agent: "Y"
    };
    const out = n.normalizeLine(row);
    expect(out.kind).toBe("unknown");
    expect(out.humanLine).toContain("unknown");
  });

  it("handles nearly empty row without throwing", () => {
    const n: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();
    const out = n.normalizeLine({});
    expect(out.kind).toBe("unknown");
  });
});
