import { describe, expect, it } from "vitest";

import {
  MemoryGraphForceGraphProjector,
  findCrossNamespaceEdgesAmong,
  filterMemoryGraphToNamespacesUnion,
  sliceMemoryGraphToNamespace,
  traceConnRootNodeId
} from "./memoryGraphForceGraphProjection";
import { mergeMemoryGraph, type MemoryGraphData } from "./memoryGraphState";

describe("memoryGraphForceGraphProjection (UC-04 A, D-TRACE-CONN-1)", () => {
  it("UC-04 A: ребро с отсутствующим концом не в финальном списке", () => {
    const data: MemoryGraphData = {
      nodes: [{ id: "A:1", label: "a", level: "A" }],
      links: [{ id: "e1", source: "A:1", target: "MISSING" }]
    };
    const out: MemoryGraphData = MemoryGraphForceGraphProjector.filterEdgesUc04BranchA(data);
    expect(out.links).toHaveLength(0);
    expect(out.nodes).toHaveLength(1);
  });

  it("UC-05: каждое ребро проекции ⊆ id узлов", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "x", label: "x", level: "B" },
        { id: "y", label: "y", level: "B" }
      ],
      links: [{ id: "e", source: "x", target: "y" }]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data, "ns");
    const ids: Set<string> = new Set(p.nodes.map((n) => n.id));
    for (const L of p.links) {
      expect(ids.has(L.source)).toBe(true);
      expect(ids.has(L.target)).toBe(true);
    }
  });

  it("D-TRACE-CONN-1: при >1 компоненте — корень в nodes и рёбра от корня к min-id представителю", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "z2", label: "z2", level: "B" },
        { id: "z1", label: "z1", level: "B" },
        { id: "orphan", label: "o", level: "B" }
      ],
      links: [{ id: "e1", source: "z1", target: "z2" }]
    };
    const ns: string = "my-ns";
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data, ns);
    const rootId: string = traceConnRootNodeId(ns);
    expect(p.nodes.map((n) => n.id)).toContain(rootId);
    const fromRoot: MemoryGraphData["links"] = p.links.filter((L) => L.source === rootId);
    expect(fromRoot.length).toBe(2);
    const targets: string[] = fromRoot.map((L) => L.target).sort();
    expect(targets).toEqual(["orphan", "z1"]);
  });

  it("D-TRACE-CONN-1: onTraceConnSynthetic при вставке синтетического корня", () => {
    const lines: string[] = [];
    const data: MemoryGraphData = {
      nodes: [
        { id: "z2", label: "z2", level: "B" },
        { id: "z1", label: "z1", level: "B" },
        { id: "orphan", label: "o", level: "B" }
      ],
      links: [{ id: "e1", source: "z1", target: "z2" }]
    };
    const ns: string = "my-ns";
    MemoryGraphForceGraphProjector.project(data, ns, {
      onTraceConnSynthetic: (payload): void => {
        lines.push(payload.line);
      }
    });
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain("event=memory.graph.trace_conn_node");
    expect(lines[0]).toContain(`namespace=${ns}`);
    expect(lines[0]).toContain("component_count=2");
  });

  it("D-TRACE-CONN-1: одна компонента — без синтетического корня", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "a", label: "a", level: "B" },
        { id: "b", label: "b", level: "B" }
      ],
      links: [{ id: "e", source: "a", target: "b" }]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data, "ns");
    expect(p.nodes.some((n) => n.id.startsWith("ailit:trace-conn-root:"))).toBe(false);
  });

  it("пачка 6 нод за один согласованный merge: рёбра ⊆ nodes после проекции", () => {
    let g: MemoryGraphData = { nodes: [], links: [] };
    for (let i: number = 0; i < 6; i += 1) {
      const chunk: MemoryGraphData = {
        nodes: [{ id: `N:${String(i)}`, label: `n${String(i)}`, level: "B" }],
        links:
          i === 0
            ? []
            : [{ id: `e:${String(i)}`, source: `N:${String(i - 1)}`, target: `N:${String(i)}` }]
      };
      g = mergeMemoryGraph(g, chunk);
    }
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(g, "ns");
    const ids: Set<string> = new Set(p.nodes.map((n) => n.id));
    expect(ids.size).toBe(6);
    for (const L of p.links) {
      expect(ids.has(L.source)).toBe(true);
      expect(ids.has(L.target)).toBe(true);
    }
  });
});

describe("memoryGraphForceGraphProjection (multi-namespace)", () => {
  it("findCrossNamespaceEdgesAmong: одно ребро между ns-a и ns-b", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "a1", label: "a1", level: "B", namespace: "ns-a" },
        { id: "b1", label: "b1", level: "B", namespace: "ns-b" }
      ],
      links: [{ id: "cross", source: "a1", target: "b1" }]
    };
    const cross: readonly unknown[] = findCrossNamespaceEdgesAmong(data, ["ns-a", "ns-b"]);
    expect(cross).toHaveLength(1);
  });

  it("sliceMemoryGraphToNamespace: только узлы своего namespace", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "a1", label: "a1", level: "B", namespace: "ns-a" },
        { id: "b1", label: "b1", level: "B", namespace: "ns-b" }
      ],
      links: [{ id: "cross", source: "a1", target: "b1" }]
    };
    const a: MemoryGraphData = sliceMemoryGraphToNamespace(data, "ns-a");
    expect(a.nodes).toHaveLength(1);
    expect(a.links).toHaveLength(0);
  });

  it("filterMemoryGraphToNamespacesUnion: сохраняет cross-edge", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "a1", label: "a1", level: "B", namespace: "ns-a" },
        { id: "b1", label: "b1", level: "B", namespace: "ns-b" }
      ],
      links: [{ id: "cross", source: "a1", target: "b1" }]
    };
    const u: MemoryGraphData = filterMemoryGraphToNamespacesUnion(data, ["ns-a", "ns-b"]);
    expect(u.nodes).toHaveLength(2);
    expect(u.links).toHaveLength(1);
  });
});
