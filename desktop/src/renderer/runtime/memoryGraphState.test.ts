import { describe, expect, it } from "vitest";

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

  it("adds missing highlighted nodes for live graph growth", () => {
    const out = ensureHighlightNodes(
      { nodes: [], links: [] },
      ["A:ns", "B:file.py", "D:summary"],
      "ns"
    );

    expect(out.nodes.map((node) => node.level)).toEqual(["A", "B", "D"]);
  });
});
