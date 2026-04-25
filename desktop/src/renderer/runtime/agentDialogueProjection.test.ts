import { describe, expect, it } from "vitest";

import { DEFAULT_AGENT_MANIFEST_V1 } from "../state/agentManifest";
import {
  buildAgentDialogueMessages,
  deriveAgentLinkKeysFromTrace,
  pairCoversMessage,
  rowToDialogueMessage
} from "./agentDialogueProjection";

describe("agentDialogueProjection (G9.7.2)", () => {
  it("projectes memory.query_context service.request as human line", () => {
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      runtime_id: "r1",
      chat_id: "chat-a",
      broker_id: "b1",
      trace_id: "t1",
      message_id: "m1",
      parent_message_id: null,
      goal_id: "g1",
      namespace: "ns1",
      from_agent: "client:test",
      to_agent: "AgentMemory:chat-a",
      created_at: "2026-04-25T12:00:00Z",
      type: "service.request",
      payload: { service: "memory.query_context", path: "tools/ailit/cli.py", top_k: "12", level: "B" }
    };
    const m: ReturnType<typeof rowToDialogueMessage> = rowToDialogueMessage(row, DEFAULT_AGENT_MANIFEST_V1, [
      "p1"
    ]);
    expect(m).not.toBeNull();
    if (!m) {
      return;
    }
    expect(m.humanText).toContain("PAG");
    expect(m.humanText).toContain("tools/ailit/cli.py");
    expect(m.technicalSummary).toContain("memory.query_context");
    expect(m.toDisplay).toBe("Memory");
  });

  it("projectes MemoryGrant response (snapshot)", () => {
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      runtime_id: "r1",
      chat_id: "chat-a",
      broker_id: "b1",
      trace_id: "t1",
      message_id: "m2",
      parent_message_id: null,
      goal_id: "g1",
      namespace: "ns1",
      from_agent: "AgentMemory:chat-a",
      to_agent: "AgentWork:chat-a",
      created_at: "2026-04-25T12:00:01Z",
      type: "service.request",
      ok: true,
      error: null,
      payload: {
        grants: [
          {
            grant_id: "g-1",
            path: "tools/ailit/cli.py",
            namespace: "ns1",
            issued_by: "AgentMemory:chat-a",
            issued_to: "AgentWork:chat-a"
          }
        ]
      }
    };
    const m: ReturnType<typeof rowToDialogueMessage> = rowToDialogueMessage(row, DEFAULT_AGENT_MANIFEST_V1, []);
    expect(m).not.toBeNull();
    if (!m) {
      return;
    }
    expect(m.humanText).toMatch(/grant/iu);
    expect(m.humanText).toContain("tools/ailit/cli.py");
  });

  it("work.handle_user_prompt action.start from client is visible as handoff line", () => {
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      runtime_id: "r1",
      chat_id: "chat-a",
      broker_id: "b1",
      trace_id: "t1",
      message_id: "m3",
      parent_message_id: null,
      goal_id: "g1",
      namespace: "ns1",
      from_agent: "client:test",
      to_agent: "AgentWork:chat-a",
      created_at: "2026-04-25T12:00:02Z",
      type: "action.start",
      payload: { action: "work.handle_user_prompt", prompt: "hi" }
    };
    const m: ReturnType<typeof rowToDialogueMessage> = rowToDialogueMessage(row, DEFAULT_AGENT_MANIFEST_V1, []);
    expect(m).not.toBeNull();
  });

  it("runtime_timeout-style error in response (snapshot)", () => {
    const row: Record<string, unknown> = {
      contract_version: "ailit_agent_runtime_v1",
      runtime_id: "r1",
      chat_id: "chat-a",
      broker_id: "b1",
      trace_id: "t1",
      message_id: "m4",
      parent_message_id: null,
      goal_id: "g1",
      namespace: "ns1",
      from_agent: "AgentWork:chat-a",
      to_agent: "AgentMemory:chat-a",
      created_at: "2026-04-25T12:00:03Z",
      type: "service.request",
      ok: false,
      error: { code: "timeout", message: "upstream timeout" },
      payload: {}
    };
    const m: ReturnType<typeof rowToDialogueMessage> = rowToDialogueMessage(row, DEFAULT_AGENT_MANIFEST_V1, []);
    expect(m).not.toBeNull();
    if (!m) {
      return;
    }
    expect(m.humanText.toLowerCase()).toContain("тайм-аут");
  });

  it("deriveAgentLinkKeysFromTrace picks Broker->Agent from client rows", () => {
    const keys: ReturnType<typeof deriveAgentLinkKeysFromTrace> = deriveAgentLinkKeysFromTrace([
      {
        from_agent: "client:test",
        to_agent: "AgentMemory:chat-a",
        type: "x"
      } as Record<string, unknown>
    ]);
    expect(keys.some((k) => k.fromType === "Broker" && k.toType === "AgentMemory")).toBe(true);
  });

  it("pairCoversMessage matches Work/Memory in both directions", () => {
    const rows: ReturnType<typeof buildAgentDialogueMessages> = buildAgentDialogueMessages(
      [
        {
          from_agent: "AgentMemory:chat-a",
          to_agent: "AgentWork:chat-a",
          created_at: "2026-01-01T00:00:00Z",
          type: "service.request",
          ok: true,
          error: null,
          payload: {
            grants: [
              { path: "a.py" }
            ]
          },
          message_id: "x1",
          trace_id: "t1",
          chat_id: "c1",
          namespace: "n"
        } as Record<string, unknown>
      ],
      DEFAULT_AGENT_MANIFEST_V1,
      []
    );
    expect(rows.length).toBe(1);
    const a: (typeof rows)[0] = rows[0]!;
    expect(
      pairCoversMessage("AgentWork", "AgentMemory", a)
    ).toBe(true);
  });
});
