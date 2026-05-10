import { describe, expect, it } from "vitest";

import { applyPagGraphTraceDelta, parsePagGraphTraceDelta } from "./pagGraphTraceDeltas";

import {
  ensureHighlightNodes,
  levelFromNodeId,
  linkFromPag,
  mergeMemoryGraph,
  nodeFromPag
} from "./memoryGraphState";

describe("memoryGraphState", () => {
  it("linkFromPag: source_node_id/target_node_id и id вместо edge_id (G4)", () => {
    const L = linkFromPag({
      id: "e-alt",
      source_node_id: "A:1",
      target_node_id: "B:2"
    });
    expect(L).not.toBeNull();
    expect(L?.source).toBe("A:1");
    expect(L?.target).toBe("B:2");
    expect(L?.id).toBe("e-alt");
  });

  it("linkFromPag: короткие ключи from/to", () => {
    const L = linkFromPag({
      edge_id: "e1",
      from: "A:proj",
      to: "B:x"
    });
    expect(L?.source).toBe("A:proj");
    expect(L?.target).toBe("B:x");
  });

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

  it("merge: NaN во входящих координатах не затирает конечные прежние значения", () => {
    const withPos: ReturnType<typeof mergeMemoryGraph> = mergeMemoryGraph(
      {
        nodes: [
          {
            id: "B:2",
            label: "a",
            level: "B",
            x: 10,
            y: 20,
            z: 30
          }
        ],
        links: []
      },
      {
        nodes: [{ id: "B:2", label: "a", level: "B", x: Number.NaN, y: Number.POSITIVE_INFINITY }],
        links: []
      }
    );
    const o = withPos.nodes.find((node) => node.id === "B:2");
    expect(o?.x).toBe(10);
    expect(o?.y).toBe(20);
    expect(o?.z).toBe(30);
  });

  it("applyPagGraphTraceDelta: pag.edge.upsert с source_node_id сохраняет связность A→B (G4)", () => {
    const row: Record<string, unknown> = {
      type: "topic.publish",
      payload: {
        type: "topic.publish",
        topic: "chat",
        event_name: "pag.edge.upsert",
        payload: {
          kind: "pag.edge.upsert",
          namespace: "ns",
          rev: 1,
          edges: [
            {
              edge_id: "e-g4",
              source_node_id: "A:1",
              target_node_id: "B:2"
            }
          ]
        }
      }
    };
    const d: ReturnType<typeof parsePagGraphTraceDelta> = parsePagGraphTraceDelta(row);
    expect(d).not.toBeNull();
    if (d == null || d.kind !== "pag.edge.upsert") {
      return;
    }
    const revsOut: Record<string, number> = {};
    const base: ReturnType<typeof mergeMemoryGraph> = mergeMemoryGraph(
      {
        nodes: [
          { id: "A:1", label: "a", level: "A", namespace: "ns" },
          { id: "B:2", label: "b", level: "B", namespace: "ns" }
        ],
        links: []
      },
      { nodes: [], links: [] }
    );
    const r: ReturnType<typeof applyPagGraphTraceDelta> = applyPagGraphTraceDelta(base, d, {}, revsOut);
    expect(r.data.links).toHaveLength(1);
    expect(r.data.links[0]?.source).toBe("A:1");
    expect(r.data.links[0]?.target).toBe("B:2");
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
