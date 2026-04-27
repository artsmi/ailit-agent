import { describe, expect, it } from "vitest";

import { bNodeIdFromPath, highlightFromTraceRow } from "./pagHighlightFromTrace";

function topic(eventName: string, payload: Record<string, unknown>): Record<string, unknown> {
  return {
    type: "topic.publish",
    namespace: "ns",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: eventName,
      payload
    }
  };
}

describe("pagHighlightFromTrace", () => {
  it("maps context.memory_injected node ids", () => {
    const row: Record<string, unknown> = {
      ...topic("context.memory_injected", {
        schema: "context.memory_injected.v1",
        node_ids: ["B:tools/ailit/cli.py", "C:tools/ailit/cli.py:1-20"],
        edge_ids: ["edge-1"],
        reason: "matched current user goal"
      })
    };
    const h: ReturnType<typeof highlightFromTraceRow> = highlightFromTraceRow(row, "ns");
    expect(h).not.toBeNull();
    if (!h) {
      return;
    }
    expect(h.nodeIds).toContain("B:tools/ailit/cli.py");
    expect(h.edgeIds).toContain("edge-1");
    expect(h.ttlMs).toBe(3000);
  });

  it("maps compacted D node and linked nodes", () => {
    const row: Record<string, unknown> = topic("context.compacted", {
      schema: "context.compacted.v1",
      d_node_id: "D:compact-summary:abc",
      linked_node_ids: ["A:ns", "B:a/b.py"]
    });
    const h: ReturnType<typeof highlightFromTraceRow> = highlightFromTraceRow(row, "ns");
    expect(h).not.toBeNull();
    if (!h) {
      return;
    }
    expect(h.nodeIds).toEqual(["D:compact-summary:abc", "A:ns", "B:a/b.py"]);
  });

  it("bNodeIdFromPath normalizes leading slash", () => {
    expect(bNodeIdFromPath("/x/y.z")).toBe("B:x/y.z");
  });

  it("does not highlight memory query candidates", () => {
    const h = highlightFromTraceRow(
      {
        type: "service.request",
        to_agent: "AgentMemory:chat-a",
        namespace: "ns",
        payload: { service: "memory.query_context", path: "tools/ailit/cli.py" }
      },
      "ns"
    );
    expect(h).toBeNull();
  });
});
