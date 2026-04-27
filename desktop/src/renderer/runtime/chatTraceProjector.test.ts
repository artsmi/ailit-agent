import { describe, expect, it } from "vitest";

import { projectChatTraceRows } from "./chatTraceProjector";

function topic(
  eventName: string,
  payload: Record<string, unknown>,
  seq: number,
  messageId: string = `evt-${String(seq)}`
): Record<string, unknown> {
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: "c1",
    broker_id: "b1",
    trace_id: "t1",
    message_id: messageId,
    parent_message_id: null,
    goal_id: "g-desktop",
    namespace: "ns",
    from_agent: "AgentWork:c1",
    to_agent: null,
    created_at: `2026-04-27T05:00:${String(seq).padStart(2, "0")}Z`,
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: eventName,
      payload
    }
  };
}

function userPrompt(seq: number): Record<string, unknown> {
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: "c1",
    broker_id: "b1",
    trace_id: "t1",
    message_id: "user-1",
    parent_message_id: null,
    goal_id: "g-desktop",
    namespace: "ns",
    from_agent: "User:desktop",
    to_agent: "AgentWork:c1",
    created_at: `2026-04-27T05:00:${String(seq).padStart(2, "0")}Z`,
    type: "action.start",
    payload: { action: "work.handle_user_prompt", prompt: "проверь тесты" }
  };
}

describe("projectChatTraceRows", () => {
  it("keeps ASK turn active and suppresses approved modal until tool finishes", () => {
    const rows: Record<string, unknown>[] = [
      userPrompt(1),
      topic("assistant.delta", { text: "Теперь запущу тесты.", text_mode: "incremental", message_id: "asst-1" }, 2),
      topic(
        "tool.call_started",
        {
          tool: "run_shell",
          call_id: "call-shell-1",
          arguments_json: "{\"command\":\"pytest\"}",
          message_id: "asst-1"
        },
        3
      ),
      topic("session.waiting_approval", { call_id: "call-shell-1", tool: "run_shell" }, 4)
    ];

    const pending = projectChatTraceRows(rows);
    expect(pending.agentTurnInProgress).toBe(true);
    expect(pending.toolApproval).toEqual({ callId: "call-shell-1", tool: "run_shell" });

    const suppressed = projectChatTraceRows(rows, { suppressedToolApprovalCallId: "call-shell-1" });
    expect(suppressed.agentTurnInProgress).toBe(true);
    expect(suppressed.toolApproval).toBeNull();
  });

  it("anchors bash output at original run_shell call and does not duplicate repeated call_started", () => {
    const rows: Record<string, unknown>[] = [
      userPrompt(1),
      topic("assistant.delta", { text: "Перед shell.", text_mode: "incremental", message_id: "asst-1" }, 2),
      topic(
        "tool.call_started",
        { tool: "run_shell", call_id: "call-shell-1", arguments_json: "{\"command\":\"pytest\"}", message_id: "asst-1" },
        3
      ),
      topic("session.waiting_approval", { call_id: "call-shell-1", tool: "run_shell" }, 4),
      topic(
        "tool.call_started",
        { tool: "run_shell", call_id: "call-shell-1", arguments_json: "{\"command\":\"pytest\"}", message_id: "asst-1" },
        5
      ),
      topic("bash.output_delta", { call_id: "call-shell-1", chunk: "OK\n", message_id: "asst-1" }, 6),
      topic("bash.finished", { call_id: "call-shell-1", ok: true, message_id: "asst-1" }, 7),
      topic("tool.call_finished", { tool: "run_shell", call_id: "call-shell-1", ok: true, message_id: "asst-1" }, 8),
      topic("assistant.delta", { text: "После shell.", text_mode: "incremental", message_id: "asst-1" }, 9)
    ];

    const out = projectChatTraceRows(rows);
    const ids = out.chatLines.map((line) => line.id);
    expect(ids).toEqual([
      "user:user-1",
      "assistant:asst-1",
      "console:bash:call:call-shell-1",
      "asst-frag:asst-1:p1"
    ]);
    expect(out.chatLines[2]?.text).toContain("OK");
    expect(out.chatLines[3]?.text).toBe("После shell.");
    expect(out.toolApproval).toBeNull();
    expect(out.agentTurnInProgress).toBe(true);
  });

  it("keeps user prompt when request and response share message_id", () => {
    const req = userPrompt(1);
    const res: Record<string, unknown> = {
      ...req,
      from_agent: "AgentWork:c1",
      to_agent: "User:desktop",
      ok: true,
      payload: { action: "work.handle_user_prompt", action_id: "a1" }
    };

    const out = projectChatTraceRows([req, res]);
    expect(out.chatLines.map((line) => [line.id, line.from, line.text])).toEqual([
      ["user:user-1", "user", "проверь тесты"]
    ]);
  });

  it("clears stale approval when broker reports bad_call for approval_resolve", () => {
    const rows: Record<string, unknown>[] = [
      userPrompt(1),
      topic(
        "tool.call_started",
        { tool: "run_shell", call_id: "stale-call", arguments_json: "{\"command\":\"pytest\"}", message_id: "asst-1" },
        2
      ),
      topic("session.waiting_approval", { call_id: "stale-call", tool: "run_shell" }, 3),
      {
        contract_version: "ailit_agent_runtime_v1",
        runtime_id: "ailit-desktop",
        chat_id: "c1",
        broker_id: "b1",
        trace_id: "t-resolve",
        message_id: "resolve-1",
        parent_message_id: null,
        goal_id: "g-desktop",
        namespace: "ns",
        from_agent: "AgentWork:c1",
        to_agent: "User:desktop",
        created_at: "2026-04-27T05:00:04Z",
        type: "service.request",
        ok: false,
        payload: { action: "work.approval_resolve", call_id: "stale-call", approved: false },
        error: { code: "bad_call", message: "stale-call" }
      }
    ];

    const out = projectChatTraceRows(rows);
    expect(out.toolApproval).toBeNull();
    expect(out.agentTurnInProgress).toBe(false);
  });

  it("stops active turn after session.cancelled terminal event", () => {
    const rows: Record<string, unknown>[] = [
      userPrompt(1),
      topic("model.request", { context_messages: 3 }, 2),
      topic("assistant.delta", { text: "Пишу", text_mode: "incremental", message_id: "asst-1" }, 3),
      topic("session.cancelled", { reason: "user_stop", source: "desktop" }, 4)
    ];

    const out = projectChatTraceRows(rows);
    expect(out.agentTurnInProgress).toBe(false);
  });

  it("projects context fill estimated snapshot and confirmed usage", () => {
    const rows: Record<string, unknown>[] = [
      userPrompt(1),
      topic(
        "context.snapshot",
        {
          schema: "context.snapshot.v1",
          turn_id: "turn-0",
          model: "mock",
          model_context_limit: 200000,
          effective_context_limit: 180000,
          reserved_output_tokens: 20000,
          estimated_context_tokens: 90000,
          context_usage_percent: 50,
          warning_state: "normal",
          usage_state: "estimated",
          breakdown: {
            system: 1000,
            tools: 2000,
            messages: 3000,
            memory_abc: 4000,
            memory_d: 0,
            tool_results: 5000,
            free: 165000
          }
        },
        2
      ),
      topic(
        "context.provider_usage_confirmed",
        {
          schema: "context.provider_usage_confirmed.v1",
          turn_id: "turn-0",
          input_tokens: 10000,
          output_tokens: 500,
          cache_read_tokens: 1000,
          cache_write_tokens: 0,
          confirmed_context_tokens: 11500,
          usage_state: "confirmed"
        },
        3
      )
    ];

    const out = projectChatTraceRows(rows);
    expect(out.contextFill?.usageState).toBe("confirmed");
    expect(out.contextFill?.estimatedContextTokens).toBe(90000);
    expect(out.contextFill?.confirmedContextTokens).toBe(11500);
    expect(out.contextFill?.breakdown["memory_abc"]).toBe(4000);
    expect(out.contextFill?.contextUsagePercent).toBe(6.39);
  });
});
