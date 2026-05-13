import { describe, expect, it } from "vitest";

import {
  computeTraceIngressMergeBatches,
  DESKTOP_TRACE_COALESCE_MAX_BUFFER_ROWS,
  simulateBatchedMerges,
  simulateSequentialSingleRowMerges
} from "./traceIngressCoalesce";
import { isTerminalTraceRowForAgentTurn } from "./traceTerminalKinds";

function topicPublishRow(
  eventName: string,
  inner: Record<string, unknown>,
  messageId: string
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
    created_at: "2026-04-27T05:00:00Z",
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: eventName,
      payload: inner
    }
  };
}

describe("trace ingress coalesce (G19.4)", () => {
  it("flushCoalesceBufferAppliesEquivalentRawTraceRowsVersusSequentialSingleRowMerges", () => {
    const rows: Record<string, unknown>[] = [
      topicPublishRow(
        "assistant.delta",
        { text: "a", text_mode: "incremental", message_id: "m1" },
        "row-1"
      ),
      topicPublishRow(
        "assistant.delta",
        { text: "b", text_mode: "incremental", message_id: "m1" },
        "row-2"
      ),
      topicPublishRow("assistant.final", { text: "done", message_id: "m1" }, "row-3"),
      topicPublishRow(
        "assistant.delta",
        { text: "x", text_mode: "incremental", message_id: "m2" },
        "row-4"
      ),
      topicPublishRow("session.cancelled", { reason: "user_stop" }, "row-5")
    ];
    const seq: Record<string, unknown>[] = simulateSequentialSingleRowMerges(rows);
    const bat: Record<string, unknown>[] = simulateBatchedMerges(
      rows,
      DESKTOP_TRACE_COALESCE_MAX_BUFFER_ROWS,
      isTerminalTraceRowForAgentTurn
    );
    expect(bat).toEqual(seq);
  });

  it("terminalTraceRowFlushesBufferedRowsBeforeApplyingTerminalMerge", () => {
    const d1: Record<string, unknown> = topicPublishRow(
      "assistant.delta",
      { text: "a", text_mode: "incremental", message_id: "m1" },
      "d1"
    );
    const d2: Record<string, unknown> = topicPublishRow(
      "assistant.delta",
      { text: "b", text_mode: "incremental", message_id: "m1" },
      "d2"
    );
    const fin: Record<string, unknown> = topicPublishRow(
      "assistant.final",
      { text: "fin", message_id: "m1" },
      "fin"
    );
    const batches = computeTraceIngressMergeBatches(
      [d1, d2, fin],
      256,
      isTerminalTraceRowForAgentTurn
    );
    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(2);
    expect(batches[1]).toHaveLength(1);
    expect(batches[1]![0]).toBe(fin);
  });

  it("coalesceHonorsBurstBackpressureWithoutUnboundedBuffer", () => {
    const burst: Record<string, unknown>[] = [];
    for (let i: number = 0; i < 25; i += 1) {
      burst.push(
        topicPublishRow(
          "assistant.delta",
          { text: `x${String(i)}`, text_mode: "incremental", message_id: "m1" },
          `id-${String(i)}`
        )
      );
    }
    const maxBuf: number = 10;
    const batches = computeTraceIngressMergeBatches(burst, maxBuf, isTerminalTraceRowForAgentTurn);
    for (const b of batches) {
      expect(b.length).toBeLessThanOrEqual(maxBuf);
    }
    expect(batches.reduce((s, b) => s + b.length, 0)).toBe(25);
    expect(batches.length).toBe(3);
    expect(batches[0]!.length).toBe(10);
    expect(batches[1]!.length).toBe(10);
    expect(batches[2]!.length).toBe(5);
  });
});
