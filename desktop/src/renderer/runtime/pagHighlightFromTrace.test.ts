import { describe, expect, it } from "vitest";

import {
  bNodeIdFromPath,
  highlightFromTraceRow,
  lastPagSearchHighlightFromTrace,
  lastPagSearchHighlightFromTraceAfterMerge
} from "./pagHighlightFromTrace";

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
  it("maps memory.w14.graph_highlight (D16.1)", () => {
    const row: Record<string, unknown> = {
      ...topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "ns",
        query_id: "q1",
        w14_command: "plan_traversal",
        w14_command_id: "q1:pt",
        node_ids: ["A:ns", "B:x.py"],
        edge_ids: ["e:1"],
        reason: "step",
        ttl_ms: 4500
      })
    };
    const h = highlightFromTraceRow(row, "ns");
    expect(h).not.toBeNull();
    if (!h) {
      return;
    }
    expect(h.nodeIds).toEqual(["A:ns", "B:x.py"]);
    expect(h.edgeIds).toEqual(["e:1"]);
    expect(h.ttlMs).toBe(4500);
    expect(h.reason).toBe("step");
    expect(h.queryId).toBe("q1");
  });

  it("skips w14 graph_highlight on namespace mismatch", () => {
    const row: Record<string, unknown> = {
      ...topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "other",
        node_ids: ["A:other"],
        edge_ids: []
      })
    };
    expect(highlightFromTraceRow(row, "ns")).toBeNull();
  });

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

  it("maps context.memory_injected v2 project refs", () => {
    const row: Record<string, unknown> = {
      ...topic("context.memory_injected", {
        schema: "context.memory_injected.v2",
        project_refs: [
          {
            project_id: "proj-a",
            namespace: "ns-a",
            node_ids: ["A:ns-a", "B:a.py"],
            edge_ids: ["edge-a"]
          },
          {
            project_id: "proj-b",
            namespace: "ns-b",
            node_ids: ["A:ns-b"],
            edge_ids: []
          }
        ],
        decision_summary: "selected relevant nodes"
      })
    };

    const hA = highlightFromTraceRow(row, "ns-a");
    expect(hA?.namespace).toBe("ns-a");
    expect(hA?.nodeIds).toEqual(["A:ns-a", "B:a.py"]);
    expect(hA?.edgeIds).toEqual(["edge-a"]);
    expect(hA?.reason).toBe("selected relevant nodes");
    const hB = highlightFromTraceRow(row, "ns-b");
    expect(hB?.namespace).toBe("ns-b");
    expect(hB?.nodeIds).toEqual(["A:ns-b"]);
    expect(highlightFromTraceRow(row, "fallback")).toBeNull();
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

  it("lastPagSearchHighlightFromTrace picks last valid highlight in order", () => {
    const rows: Record<string, unknown>[] = [
      topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "ns",
        node_ids: ["B:old.py"],
        edge_ids: [],
        reason: "a",
        ttl_ms: 3000
      }),
      topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "ns",
        node_ids: ["B:new.py"],
        edge_ids: [],
        reason: "b",
        ttl_ms: 4000
      })
    ];
    const h = lastPagSearchHighlightFromTrace(rows, "ns");
    expect(h?.nodeIds).toEqual(["B:new.py"]);
    expect(h?.reason).toBe("b");
    expect(h?.ttlMs).toBe(4000);
  });

  it("lastPagSearchHighlightFromTrace ignores tail rows without highlight", () => {
    const rows: Record<string, unknown>[] = [
      topic("context.memory_injected", {
        schema: "context.memory_injected.v1",
        node_ids: ["B:keep.py"],
        edge_ids: [],
        reason: "inj"
      }),
      {
        type: "service.request",
        to_agent: "AgentMemory:chat-a",
        namespace: "ns",
        payload: { service: "memory.query_context", path: "x" }
      }
    ];
    const h = lastPagSearchHighlightFromTrace(rows, "ns");
    expect(h?.nodeIds).toContain("B:keep.py");
  });

  it("lastPagSearchHighlightFromTrace returns null when no row yields highlight", () => {
    expect(
      lastPagSearchHighlightFromTrace(
        [
          {
            type: "service.request",
            namespace: "ns",
            payload: {}
          }
        ],
        "ns"
      )
    ).toBeNull();
  });

  it("lastPagSearchHighlightFromTraceAfterMerge keeps previous when trace tail has no new rows", () => {
    const rows: Record<string, unknown>[] = [
      topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "ns",
        node_ids: ["B:stable.py"],
        edge_ids: [],
        reason: "w14",
        ttl_ms: 3000
      }),
      {
        type: "service.request",
        to_agent: "AgentMemory:chat-a",
        namespace: "ns",
        payload: { service: "memory.query_context", path: "x" }
      }
    ];
    const prev = lastPagSearchHighlightFromTrace(rows, "ns");
    expect(prev?.nodeIds).toContain("B:stable.py");
    const lastConsumed: number = rows.length - 1;
    const again = lastPagSearchHighlightFromTraceAfterMerge(rows, "ns", prev, lastConsumed);
    expect(again?.nodeIds).toEqual(prev?.nodeIds);
  });

  it("lastPagSearchHighlightFromTraceAfterMerge falls back to full trace when previous is null", () => {
    const rows: Record<string, unknown>[] = [
      topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "ns",
        node_ids: ["B:fallback.py"],
        edge_ids: [],
        reason: "w14",
        ttl_ms: 3000
      })
    ];
    const h = lastPagSearchHighlightFromTraceAfterMerge(rows, "ns", null, rows.length - 1);
    expect(h?.nodeIds).toEqual(["B:fallback.py"]);
  });

  it("lastPagSearchHighlightFromTraceAfterMerge uses full trace when new rows were appended", () => {
    const rows: Record<string, unknown>[] = [
      topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "ns",
        node_ids: ["B:first.py"],
        edge_ids: [],
        reason: "a",
        ttl_ms: 3000
      }),
      topic("memory.w14.graph_highlight", {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace: "ns",
        node_ids: ["B:second.py"],
        edge_ids: [],
        reason: "b",
        ttl_ms: 4000
      })
    ];
    const prev = lastPagSearchHighlightFromTrace(rows.slice(0, 1), "ns");
    expect(prev?.nodeIds).toEqual(["B:first.py"]);
    const h = lastPagSearchHighlightFromTraceAfterMerge(rows, "ns", prev, 0);
    expect(h?.nodeIds).toEqual(["B:second.py"]);
  });
});
