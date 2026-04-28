export type MemoryGraphLevel = "A" | "B" | "C" | "D";

export type MemoryGraphNode = {
  id: string;
  label: string;
  level: MemoryGraphLevel;
  namespace?: string;
  /** PAG `staleness_state` при наличии (2D, unified store). */
  staleness?: string;
  x?: number;
  y?: number;
  z?: number;
  fx?: number;
  fy?: number;
  fz?: number;
};

export type MemoryGraphLink = {
  id: string;
  source: string;
  target: string;
  edgeType?: string;
  edgeClass?: string;
};

export type MemoryGraphData = {
  readonly nodes: MemoryGraphNode[];
  readonly links: MemoryGraphLink[];
};

function str(x: unknown): string {
  return typeof x === "string" ? x : x == null ? "" : String(x);
}

export function levelFromNodeId(id: string): MemoryGraphLevel {
  if (id.startsWith("A:")) {
    return "A";
  }
  if (id.startsWith("C:")) {
    return "C";
  }
  if (id.startsWith("D:")) {
    return "D";
  }
  return "B";
}

export function nodeFromPag(raw: Record<string, unknown>): MemoryGraphNode | null {
  const id: string = str(raw["node_id"]);
  if (!id) {
    return null;
  }
  const rawLevel: string = str(raw["level"]);
  const level: MemoryGraphLevel =
    rawLevel === "A" || rawLevel === "B" || rawLevel === "C" || rawLevel === "D"
      ? rawLevel
      : levelFromNodeId(id);
  return {
    id,
    label: str(raw["title"] ?? raw["path"] ?? raw["node_id"]) || id,
    level,
    namespace: str(raw["namespace"] ?? ""),
    staleness: (() => {
      const st: string = str(raw["staleness_state"] ?? raw["staleness"] ?? "");
      return st.length > 0 ? st : undefined;
    })()
  };
}

export function linkFromPag(raw: Record<string, unknown>): MemoryGraphLink | null {
  const id: string = str(raw["edge_id"]);
  const source: string = str(raw["from_node_id"]);
  const target: string = str(raw["to_node_id"]);
  if (!id || !source || !target) {
    return null;
  }
  return {
    id,
    source,
    target,
    edgeType: str(raw["edge_type"] ?? raw["edgeType"] ?? "") || undefined,
    edgeClass: str(raw["edge_class"] ?? raw["edgeClass"] ?? "") || undefined
  };
}

export function mergeMemoryGraph(
  current: MemoryGraphData,
  next: MemoryGraphData
): MemoryGraphData {
  const nodes: Map<string, MemoryGraphNode> = new Map();
  const links: Map<string, MemoryGraphLink> = new Map();
  for (const node of current.nodes) {
    nodes.set(node.id, node);
  }
  for (const node of next.nodes) {
    nodes.set(node.id, { ...nodes.get(node.id), ...node });
  }
  for (const link of current.links) {
    links.set(link.id, link);
  }
  for (const link of next.links) {
    links.set(link.id, link);
  }
  return {
    nodes: [...nodes.values()],
    links: [...links.values()]
  };
}

export function ensureHighlightNodes(
  data: MemoryGraphData,
  nodeIds: readonly string[],
  namespace: string
): MemoryGraphData {
  const existing: Set<string> = new Set(data.nodes.map((node) => node.id));
  const additions: MemoryGraphNode[] = [];
  for (const id of nodeIds) {
    if (!id || existing.has(id)) {
      continue;
    }
    additions.push({
      id,
      label: id,
      level: levelFromNodeId(id),
      namespace
    });
  }
  if (additions.length === 0) {
    return data;
  }
  return {
    nodes: [...data.nodes, ...additions],
    links: data.links
  };
}
