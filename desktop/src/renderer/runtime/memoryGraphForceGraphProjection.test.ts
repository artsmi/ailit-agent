import { describe, expect, it } from "vitest";

import {
  MemoryGraphForceGraphProjector,
  filterMemoryGraphToNamespacesUnion,
  findCrossNamespaceEdgesAmong,
  keepNodesReachableToAnyA,
  sliceMemoryGraphToNamespace
} from "./memoryGraphForceGraphProjection";
import {
  ensureHighlightNodes,
  mergeMemoryGraph,
  type MemoryGraphData
} from "./memoryGraphState";

describe("memoryGraphForceGraphProjection (UC-04 A)", () => {
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
        { id: "A:1", label: "a", level: "A" },
        { id: "x", label: "x", level: "B" },
        { id: "y", label: "y", level: "B" }
      ],
      links: [
        { id: "e0", source: "A:1", target: "x" },
        { id: "e", source: "x", target: "y" }
      ]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    const ids: Set<string> = new Set(p.nodes.map((n) => n.id));
    for (const L of p.links) {
      expect(ids.has(L.source)).toBe(true);
      expect(ids.has(L.target)).toBe(true);
    }
  });
});

describe("memoryGraphForceGraphProjection (D-EDGE-GATE-1 reachability)", () => {
  it("A без рёбер видна всегда", () => {
    const data: MemoryGraphData = {
      nodes: [{ id: "A:proj", label: "p", level: "A" }],
      links: []
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes.map((n) => n.id)).toEqual(["A:proj"]);
    expect(p.links).toHaveLength(0);
  });

  it("A + B со связью A→B видна вся пара", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "A:proj", label: "p", level: "A" },
        { id: "B:b", label: "b", level: "B" }
      ],
      links: [{ id: "e", source: "A:proj", target: "B:b" }]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes.map((n) => n.id).sort()).toEqual(["A:proj", "B:b"]);
    expect(p.links.map((L) => L.id)).toEqual(["e"]);
  });

  it("цепочка A→B→C — все три видны", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "A:proj", label: "p", level: "A" },
        { id: "B:b", label: "b", level: "B" },
        { id: "C:c", label: "c", level: "C" }
      ],
      links: [
        { id: "e1", source: "A:proj", target: "B:b" },
        { id: "e2", source: "B:b", target: "C:c" }
      ]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes.map((n) => n.id).sort()).toEqual(["A:proj", "B:b", "C:c"]);
    expect(p.links.map((L) => L.id).sort()).toEqual(["e1", "e2"]);
  });

  it("orphan B без рёбер скрыта; A видна", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "A:proj", label: "p", level: "A" },
        { id: "B:lonely", label: "x", level: "B" }
      ],
      links: []
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes.map((n) => n.id)).toEqual(["A:proj"]);
    expect(p.links).toHaveLength(0);
  });

  it("ребро B→C без A — обе скрыты (нет корня)", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "B:x", label: "x", level: "B" },
        { id: "C:y", label: "y", level: "C" }
      ],
      links: [{ id: "e", source: "B:x", target: "C:y" }]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes).toHaveLength(0);
    expect(p.links).toHaveLength(0);
  });

  it("несколько A — каждая корень своей подкомпоненты", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "A:1", label: "p1", level: "A" },
        { id: "A:2", label: "p2", level: "A" },
        { id: "B:b1", label: "b1", level: "B" },
        { id: "B:b2", label: "b2", level: "B" }
      ],
      links: [
        { id: "e1", source: "A:1", target: "B:b1" },
        { id: "e2", source: "A:2", target: "B:b2" }
      ]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes.map((n) => n.id).sort()).toEqual(["A:1", "A:2", "B:b1", "B:b2"]);
    expect(p.links.map((L) => L.id).sort()).toEqual(["e1", "e2"]);
  });

  it("highlight placeholder без рёбер скрыт в проекции 3D", () => {
    const base: MemoryGraphData = {
      nodes: [{ id: "A:proj", label: "p", level: "A" }],
      links: []
    };
    const withHl: MemoryGraphData = ensureHighlightNodes(base, ["X:hot"], "ns");
    expect(withHl.nodes.map((n) => n.id).sort()).toEqual(["A:proj", "X:hot"]);
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(withHl);
    expect(p.nodes.map((n) => n.id)).toEqual(["A:proj"]);
  });

  it("направление ребра не важно: ребро B→A → B видна", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "A:proj", label: "p", level: "A" },
        { id: "B:b", label: "b", level: "B" }
      ],
      links: [{ id: "e", source: "B:b", target: "A:proj" }]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes.map((n) => n.id).sort()).toEqual(["A:proj", "B:b"]);
    expect(p.links.map((L) => L.id)).toEqual(["e"]);
  });

  it("UC-04A до reachability: висячее ребро не делает ноду достижимой", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "A:proj", label: "p", level: "A" },
        { id: "B:lonely", label: "x", level: "B" }
      ],
      links: [{ id: "phantom", source: "A:proj", target: "MISSING" }]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    expect(p.nodes.map((n) => n.id)).toEqual(["A:proj"]);
    expect(p.links).toHaveLength(0);
  });

  it("D-EDGE-GATE-1: синтетический корень `ailit:trace-conn-root:` не появляется", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "A:proj", label: "p", level: "A" },
        { id: "B:b", label: "b", level: "B" },
        { id: "B:lonely", label: "x", level: "B" }
      ],
      links: [{ id: "e", source: "A:proj", target: "B:b" }]
    };
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(data);
    for (const n of p.nodes) {
      expect(n.id.startsWith("ailit:trace-conn-root:")).toBe(false);
    }
    for (const L of p.links) {
      expect(L.id.startsWith("ailit:trace-conn-edge:")).toBe(false);
    }
  });

  it("`keepNodesReachableToAnyA` без A → пустой граф", () => {
    const data: MemoryGraphData = {
      nodes: [
        { id: "B:b1", label: "b1", level: "B" },
        { id: "B:b2", label: "b2", level: "B" }
      ],
      links: [{ id: "e", source: "B:b1", target: "B:b2" }]
    };
    const out: MemoryGraphData = keepNodesReachableToAnyA(data);
    expect(out.nodes).toHaveLength(0);
    expect(out.links).toHaveLength(0);
  });

  it("пачка 6 нод (B без A) за один merge: проекция пуста (нет корней)", () => {
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
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(g);
    expect(p.nodes).toHaveLength(0);
    expect(p.links).toHaveLength(0);
  });

  it("multi_unified union: A в одном NS — корень для B из другого NS, если их связывает cross-edge", () => {
    const merged: MemoryGraphData = {
      nodes: [
        { id: "A:1", label: "p1", level: "A", namespace: "ns-a" },
        { id: "B:b1", label: "b1", level: "B", namespace: "ns-a" },
        { id: "B:b2", label: "b2", level: "B", namespace: "ns-b" }
      ],
      links: [
        { id: "e1", source: "A:1", target: "B:b1" },
        { id: "cross", source: "B:b1", target: "B:b2" }
      ]
    };
    const union: MemoryGraphData = filterMemoryGraphToNamespacesUnion(merged, ["ns-a", "ns-b"]);
    const p: MemoryGraphData = MemoryGraphForceGraphProjector.project(union);
    expect(p.nodes.map((n) => n.id).sort()).toEqual(["A:1", "B:b1", "B:b2"]);
    expect(p.links.map((L) => L.id).sort()).toEqual(["cross", "e1"]);
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
