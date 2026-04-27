import { describe, expect, it } from "vitest";

import { ensureHighlightNodes, mergeMemoryGraph } from "./memoryGraphState";
import { projectChatTraceRows } from "./chatTraceProjector";
import { projectMemoryJournalRows } from "./memoryJournalProjection";
import { highlightFromTraceRow } from "./pagHighlightFromTrace";

function topic(
  eventName: string,
  payload: Record<string, unknown>,
  seq: number
): Record<string, unknown> {
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: "chat-g10",
    broker_id: "broker-chat-g10",
    trace_id: "trace-g10",
    message_id: `evt-${String(seq)}`,
    parent_message_id: null,
    goal_id: "g-desktop",
    namespace: "ns",
    from_agent: "AgentWork:chat-g10",
    to_agent: null,
    created_at: `2026-04-27T06:00:${String(seq).padStart(2, "0")}Z`,
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: eventName,
      payload
    }
  };
}

describe("Workflow 10 readiness projections", () => {
  it("projects context fill, D artifacts, restore line, and 3D highlights", () => {
    const rows: Record<string, unknown>[] = [
      topic(
        "context.memory_injected",
        {
          schema: "context.memory_injected.v1",
          usage_state: "estimated",
          node_ids: ["A:ns", "B:tools/app.py", "C:tools/app.py:1-20"],
          edge_ids: ["edge-runtime"],
          estimated_tokens: 120,
          prompt_section: "memory",
          reason: "matched current user goal"
        },
        1
      ),
      topic(
        "context.snapshot",
        {
          schema: "context.snapshot.v1",
          turn_id: "turn-0",
          model: "mock",
          model_context_limit: 200000,
          effective_context_limit: 180000,
          reserved_output_tokens: 20000,
          estimated_context_tokens: 3600,
          context_usage_percent: 2,
          warning_state: "normal",
          usage_state: "estimated",
          breakdown: {
            system: 400,
            tools: 800,
            messages: 1000,
            memory_abc: 120,
            memory_d: 600,
            tool_results: 680,
            free: 176400
          }
        },
        2
      ),
      topic(
        "context.compacted",
        {
          schema: "context.compacted.v1",
          d_node_id: "D:compact-summary:abc",
          linked_node_ids: ["A:ns", "B:tools/app.py"],
          freed_tokens_estimated: 9000
        },
        3
      ),
      topic(
        "context.restored",
        {
          schema: "context.restored.v1",
          d_node_id: "D:compact-summary:abc",
          linked_node_ids: ["A:ns", "B:tools/app.py"]
        },
        4
      )
    ];

    const projection = projectChatTraceRows(rows);
    expect(projection.contextFill?.breakdown["memory_abc"]).toBe(120);
    expect(projection.contextFill?.breakdown["memory_d"]).toBe(600);
    expect(projection.chatLines.some((line) => line.text.includes("D:compact-summary:abc"))).toBe(true);

    const injected = highlightFromTraceRow(rows[0]!, "ns");
    expect(injected?.nodeIds).toContain("B:tools/app.py");
    expect(injected?.edgeIds).toContain("edge-runtime");

    const compacted = highlightFromTraceRow(rows[2]!, "ns");
    expect(compacted?.nodeIds).toEqual(["D:compact-summary:abc", "A:ns", "B:tools/app.py"]);

    const restored = highlightFromTraceRow(rows[3]!, "ns");
    expect(restored?.nodeIds).toEqual(["D:compact-summary:abc", "A:ns", "B:tools/app.py"]);
  });
});

describe("Workflow 11 readiness projections", () => {
  it("connects journal rows, namespace-aware highlights, and graph growth", () => {
    const rows: Record<string, unknown>[] = [
      topic(
        "context.memory_injected",
        {
          schema: "context.memory_injected.v2",
          usage_state: "estimated",
          project_refs: [
            {
              project_id: "proj-a",
              namespace: "ns-a",
              node_ids: ["A:ns-a", "B:tools/app.py"],
              edge_ids: ["edge-a"]
            },
            {
              project_id: "proj-b",
              namespace: "ns-b",
              node_ids: ["A:ns-b"],
              edge_ids: []
            }
          ],
          estimated_tokens: 120,
          prompt_section: "memory",
          decision_summary: "selected multi-project memory"
        },
        1
      )
    ];
    const injected = highlightFromTraceRow(rows[0]!, "fallback");
    expect(injected?.namespace).toBe("ns-a");
    expect(injected?.nodeIds).toEqual(["A:ns-a", "B:tools/app.py", "A:ns-b"]);

    const graph = ensureHighlightNodes(
      mergeMemoryGraph({ nodes: [], links: [] }, { nodes: [], links: [] }),
      injected?.nodeIds ?? [],
      injected?.namespace ?? "ns-a"
    );
    expect(graph.nodes.map((node) => node.id)).toContain("A:ns-b");

    const journal = projectMemoryJournalRows(
      [
        {
          schema: "ailit_memory_journal_v1",
          created_at: "2026-04-27T00:00:00Z",
          chat_id: "chat-g10",
          request_id: "req-1",
          namespace: "ns-a",
          event_name: "memory.explore.C.finished",
          summary: "selected ranges",
          node_ids: ["C:tools/app.py:1-20"],
          edge_ids: [],
          payload: { next_action: "return slice", partial: false }
        }
      ],
      "chat-g10"
    );
    expect(journal[0]?.eventName).toBe("memory.explore.C.finished");
    expect(journal[0]?.nodeIds).toEqual(["C:tools/app.py:1-20"]);
  });
});
