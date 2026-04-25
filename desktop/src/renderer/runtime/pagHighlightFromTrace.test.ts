import { describe, expect, it } from "vitest";

import { bNodeIdFromPath, highlightFromTraceRow } from "./pagHighlightFromTrace";

describe("pagHighlightFromTrace (G9.8.2)", () => {
  it("maps request path to B: node id", () => {
    const row: Record<string, unknown> = {
      type: "service.request",
      to_agent: "AgentMemory:chat-a",
      namespace: "ns",
      payload: { service: "memory.query_context", path: "tools/ailit/cli.py" }
    };
    const h: ReturnType<typeof highlightFromTraceRow> = highlightFromTraceRow(row, "ns");
    expect(h).not.toBeNull();
    if (!h) {
      return;
    }
    expect(h.nodeIds).toContain("B:tools/ailit/cli.py");
    expect(h.ttlMs).toBe(3000);
  });

  it("maps grant paths from response", () => {
    const row: Record<string, unknown> = {
      type: "service.request",
      ok: true,
      namespace: "ns",
      payload: {
        grants: [{ path: "a/b.py" }]
      }
    };
    const h: ReturnType<typeof highlightFromTraceRow> = highlightFromTraceRow(row, "ns");
    expect(h).not.toBeNull();
    if (!h) {
      return;
    }
    expect(h?.nodeIds[0]).toBe("B:a/b.py");
  });

  it("bNodeIdFromPath normalizes leading slash", () => {
    expect(bNodeIdFromPath("/x/y.z")).toBe("B:x/y.z");
  });
});
