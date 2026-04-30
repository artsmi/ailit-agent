import { describe, expect, it } from "vitest";

import {
  MemoryGraphForceGraphProjector,
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
