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
