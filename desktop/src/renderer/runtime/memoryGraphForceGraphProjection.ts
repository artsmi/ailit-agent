import type { MemoryGraphData, MemoryGraphLink, MemoryGraphNode } from "./memoryGraphState";

/** Карта id узла → namespace (пустая строка если не задано). */
export function buildNodeIdToNamespaceMap(
  nodes: readonly MemoryGraphNode[]
): ReadonlyMap<string, string> {
  const m: Map<string, string> = new Map();
  for (const n of nodes) {
    m.set(n.id, n.namespace ?? "");
  }
  return m;
}

/**
 * Рёбра, соединяющие два разных namespace из выбранного набора (оба конца в wanted и ns различаются).
 */
export function findCrossNamespaceEdgesAmong(
  data: MemoryGraphData,
  selectedNamespaces: readonly string[]
): readonly MemoryGraphLink[] {
  const wanted: Set<string> = new Set(selectedNamespaces.filter((x: string) => x.length > 0));
  if (wanted.size < 2) {
    return [];
  }
  const idToNs: ReadonlyMap<string, string> = buildNodeIdToNamespaceMap(data.nodes);
  const out: MemoryGraphLink[] = [];
  for (const L of data.links) {
    const nsS: string = idToNs.get(L.source) ?? "";
    const nsT: string = idToNs.get(L.target) ?? "";
    if (!wanted.has(nsS) || !wanted.has(nsT)) {
      continue;
    }
    if (nsS.length > 0 && nsT.length > 0 && nsS !== nsT) {
      out.push(L);
    }
  }
  return out;
}

/** Узлы и рёбра только указанного namespace. */
export function sliceMemoryGraphToNamespace(
  data: MemoryGraphData,
  namespace: string
): MemoryGraphData {
  if (namespace.length === 0) {
    return { nodes: [], links: [] };
  }
  const nodes: MemoryGraphNode[] = data.nodes.filter((n) => (n.namespace ?? "") === namespace);
  const ids: Set<string> = new Set(nodes.map((n) => n.id));
  const links: MemoryGraphLink[] = data.links.filter(
    (L) => ids.has(L.source) && ids.has(L.target)
  );
  return { nodes, links };
}

/** Подграф по объединению выбранных namespace (включая меж-namespace рёбра внутри union). */
export function filterMemoryGraphToNamespacesUnion(
  data: MemoryGraphData,
  selectedNamespaces: readonly string[]
): MemoryGraphData {
  const wanted: Set<string> = new Set(selectedNamespaces.filter((x: string) => x.length > 0));
  const nodes: MemoryGraphNode[] = data.nodes.filter((n) => wanted.has(n.namespace ?? ""));
  const ids: Set<string> = new Set(nodes.map((n) => n.id));
  const links: MemoryGraphLink[] = data.links.filter(
    (L) => ids.has(L.source) && ids.has(L.target)
  );
  return { nodes, links };
}

/**
 * D-EDGE-GATE-1: оставить только узлы, у которых есть путь рёбер до **любой** A-ноды
 * (BFS неориентированно). A-узлы остаются всегда. Если A нет — пустой граф.
 *
 * Запрещено: вводить синтетические узлы/рёбра, которых нет в `data` (см. canon
 * `context/arch/desktop-pag-graph-snapshot.md` — D-EDGE-GATE-1).
 */
export function keepNodesReachableToAnyA(data: MemoryGraphData): MemoryGraphData {
  const aIds: string[] = [];
  for (const n of data.nodes) {
    if (n.level === "A") {
      aIds.push(n.id);
    }
  }
  if (aIds.length === 0) {
    return { nodes: [], links: [] };
  }
  const idSet: Set<string> = new Set(data.nodes.map((n) => n.id));
  const adj: Map<string, string[]> = new Map();
  for (const id of idSet) {
    adj.set(id, []);
  }
  for (const L of data.links) {
    if (!idSet.has(L.source) || !idSet.has(L.target)) {
      continue;
    }
    adj.get(L.source)!.push(L.target);
    adj.get(L.target)!.push(L.source);
  }
  const reachable: Set<string> = new Set();
  const queue: string[] = [];
  for (const a of aIds) {
    if (!reachable.has(a)) {
      reachable.add(a);
      queue.push(a);
    }
  }
  while (queue.length > 0) {
    const cur: string = queue.shift()!;
    const neighbours: string[] | undefined = adj.get(cur);
    if (neighbours === undefined) {
      continue;
    }
    for (const nb of neighbours) {
      if (!reachable.has(nb)) {
        reachable.add(nb);
        queue.push(nb);
      }
    }
  }
  const nodes: MemoryGraphNode[] = data.nodes.filter((n) => reachable.has(n.id));
  const links: MemoryGraphLink[] = data.links.filter(
    (L) => reachable.has(L.source) && reachable.has(L.target)
  );
  return { nodes, links };
}

export class MemoryGraphForceGraphProjector {
  /**
   * UC-04 ветка A: рёбра без обоих концов во множестве id узлов текущей проекции не попадают в выдачу ForceGraph.
   */
  static filterEdgesUc04BranchA(data: MemoryGraphData): MemoryGraphData {
    const ids: Set<string> = new Set(data.nodes.map((n) => n.id));
    const links: MemoryGraphLink[] = data.links.filter(
      (L) => ids.has(L.source) && ids.has(L.target)
    );
    return { nodes: data.nodes, links };
  }

  /**
   * Проекция merged → graphData для `ForceGraph3D` (D-EDGE-GATE-1):
   * `filterEdgesUc04BranchA` → `keepNodesReachableToAnyA`.
   */
  static project(data: MemoryGraphData): MemoryGraphData {
    const step1: MemoryGraphData = MemoryGraphForceGraphProjector.filterEdgesUc04BranchA(data);
    return keepNodesReachableToAnyA(step1);
  }
}
