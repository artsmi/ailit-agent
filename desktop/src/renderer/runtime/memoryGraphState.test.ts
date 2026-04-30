import { describe, expect, it } from "vitest";

import { applyPagGraphTraceDelta, parsePagGraphTraceDelta } from "./pagGraphTraceDeltas";

import {
  ensureHighlightNodes,
  levelFromNodeId,
  mergeMemoryGraph,
  nodeFromPag
} from "./memoryGraphState";

describe("memoryGraphState", () => {
  it("maps PAG nodes and D-level ids", () => {
    const node = nodeFromPag({
      namespace: "ns",
      node_id: "D:compact-summary:1",
      title: "Summary",
      level: "D"
    });

    expect(node?.level).toBe("D");
    expect(node?.namespace).toBe("ns");
    expect(levelFromNodeId("C:file.py#x")).toBe("C");
  });

  it("merges real graph data without mock fallback", () => {
    const out = mergeMemoryGraph(
      { nodes: [{ id: "A:old", label: "old", level: "A" }], links: [] },
      { nodes: [{ id: "A:new", label: "new", level: "A" }], links: [] }
    );

    expect(out.nodes.map((node) => node.id).sort()).toEqual(["A:new", "A:old"]);
  });

  it("merge: для совпадающих id координаты (x/y/z/fx/fy/fz) не сбрасываются при входе ноды без полей", () => {
    const withPos: ReturnType<typeof mergeMemoryGraph> = mergeMemoryGraph(
      {
        nodes: [
          {
            id: "B:1",
            label: "a",
            level: "B",
            x: 1,
            y: 2,
            z: 3,
            fx: 0.1,
            fy: 0.2,
            fz: 0.3
          }
        ],
        links: []
      },
      { nodes: [{ id: "B:1", label: "a", level: "B" }], links: [] }
    );
    const o = withPos.nodes.find((node) => node.id === "B:1");
    expect(o?.x).toBe(1);
    expect(o?.y).toBe(2);
    expect(o?.z).toBe(3);
    expect(o?.fx).toBe(0.1);
    expect(o?.fy).toBe(0.2);
    expect(o?.fz).toBe(0.3);
  });

  it("applyPagGraphTraceDelta + merge: upsert PAG-ноды без координат не стирает уже выставленные x/y/z", () => {
    const row: Record<string, unknown> = {
      type: "topic.publish",
      payload: {
        type: "topic.publish",
        topic: "chat",
        event_name: "pag.node.upsert",
        payload: {
          kind: "pag.node.upsert",
          namespace: "ns",
          rev: 1,
          node: { node_id: "B:1", level: "B", path: "p", title: "t" }
        }
      }
    };
    const d: ReturnType<typeof parsePagGraphTraceDelta> = parsePagGraphTraceDelta(row);
    expect(d).not.toBeNull();
    if (d == null) {
      return;
    }
    const revsOut: Record<string, number> = {};
    const r: ReturnType<typeof applyPagGraphTraceDelta> = applyPagGraphTraceDelta(
      { nodes: [{ id: "B:1", label: "p", level: "B", x: 5, y: 6, z: 7 }], links: [] },
      d,
      {},
      revsOut
    );
    expect(r.data.nodes[0]?.x).toBe(5);
  });

  it("adds missing highlighted nodes for live graph growth", () => {
    const out = ensureHighlightNodes(
      { nodes: [], links: [] },
      ["A:ns", "B:file.py", "D:summary"],
      "ns"
    );

    expect(out.nodes.map((node) => node.level)).toEqual(["A", "B", "D"]);
  });
});
