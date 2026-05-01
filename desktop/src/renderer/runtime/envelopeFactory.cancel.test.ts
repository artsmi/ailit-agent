import { describe, expect, it } from "vitest";

import { buildRuntimeCancelActiveTurnRequest } from "./envelopeFactory";

describe("buildRuntimeCancelActiveTurnRequest", () => {
  it("matches plan.md frozen UC-05 broker envelope (service.request + payload)", () => {
    const chatId: string = "chat-test";
    const built: ReturnType<typeof buildRuntimeCancelActiveTurnRequest> = buildRuntimeCancelActiveTurnRequest({
      chatId,
      brokerId: `broker-${chatId}`,
      namespace: "ns1",
      goalId: "g-desktop",
      traceId: "tr-1",
      userTurnId: "ut-abc"
    });
    const { envelope } = built;
    expect(envelope.type).toBe("service.request");
    expect(envelope.to_agent).toBe(`AgentWork:${chatId}`);
    expect(envelope.chat_id).toBe(chatId);
    const pl: Record<string, unknown> = envelope.payload as Record<string, unknown>;
    expect(pl["action"]).toBe("runtime.cancel_active_turn");
    expect(pl["chat_id"]).toBe(chatId);
    expect(pl["user_turn_id"]).toBe("ut-abc");
  });

  it("allows empty user_turn_id string per proto before memory.query_context", () => {
    const chatId: string = "c2";
    const built: ReturnType<typeof buildRuntimeCancelActiveTurnRequest> = buildRuntimeCancelActiveTurnRequest({
      chatId,
      brokerId: `broker-${chatId}`,
      namespace: "ns",
      goalId: "g",
      traceId: "t",
      userTurnId: ""
    });
    expect((built.envelope.payload as { user_turn_id: string }).user_turn_id).toBe("");
  });
});
