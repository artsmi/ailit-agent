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
    const nsS: string = idToNs.get(coerceGraphLinkEndpoint(L.source)) ?? "";
    const nsT: string = idToNs.get(coerceGraphLinkEndpoint(L.target)) ?? "";
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
    (L) => ids.has(coerceGraphLinkEndpoint(L.source)) && ids.has(coerceGraphLinkEndpoint(L.target))
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
    (L) => ids.has(coerceGraphLinkEndpoint(L.source)) && ids.has(coerceGraphLinkEndpoint(L.target))
  );
  return { nodes, links };
}

/**
 * Привести конец ребра к строковому id (d3 / react-force-graph могут заменить на объект узла).
 */
export function coerceGraphLinkEndpoint(endpoint: unknown): string {
  if (typeof endpoint === "string") {
    return endpoint;
  }
  if (endpoint !== null && typeof endpoint === "object" && "id" in endpoint) {
    const id: unknown = (endpoint as { readonly id: unknown }).id;
    if (typeof id === "string") {
      return id;
    }
    if (typeof id === "number" && Number.isFinite(id)) {
      return String(Math.trunc(id));
    }
  }
  return "";
}

/**
 * Нормализовать `source`/`target` у рёбер без мутации узлов; нужно до UC-04A и для slice/cross-edge.
 */
export function normalizeMemoryGraphLinkEndpoints(data: MemoryGraphData): MemoryGraphData {
  const links: MemoryGraphLink[] = data.links.map((L: MemoryGraphLink): MemoryGraphLink => {
    const s: string = coerceGraphLinkEndpoint(L.source);
    const t: string = coerceGraphLinkEndpoint(L.target);
    if (s === L.source && t === L.target) {
      return L;
    }
    return { ...L, source: s, target: t };
  });
  return { nodes: data.nodes, links };
}

/**
 * Копия графа для `ForceGraph3D`: движок мутирует объекты; store (`merged`) не должен делиться ссылками.
 */
export function cloneMemoryGraphForForceGraphRender(data: MemoryGraphData): MemoryGraphData {
  return {
    nodes: data.nodes.map((n: MemoryGraphNode): MemoryGraphNode => ({ ...n })),
    links: data.links.map(
      (L: MemoryGraphLink): MemoryGraphLink => ({
        ...L,
        source: coerceGraphLinkEndpoint(L.source),
        target: coerceGraphLinkEndpoint(L.target)
      })
    )
  };
}

/**
 * D-EDGE-GATE-1 (legacy): оставить только узлы, у которых есть путь рёбер до **любой** A-ноды
 * (BFS неориентированно). A-узлы остаются всегда. Если A нет — пустой граф.
 *
 * Экспортируется для тестов и опциональных сценариев; **3D `project` больше не вызывает** эту функцию.
 *
 * Запрещено: вводить синтетические узлы/рёбра, которых нет в `data` (см. canon
 * `context/arch/desktop-pag-graph-snapshot.md` — исторический D-EDGE-GATE-1).
 */
export function keepNodesReachableToAnyA(data: MemoryGraphData): MemoryGraphData {
  const normalized: MemoryGraphData = normalizeMemoryGraphLinkEndpoints(data);
  const aIds: string[] = [];
  for (const n of normalized.nodes) {
    if (n.level === "A") {
      aIds.push(n.id);
    }
  }
  if (aIds.length === 0) {
    return { nodes: [], links: [] };
  }
  const idSet: Set<string> = new Set(normalized.nodes.map((n) => n.id));
  const adj: Map<string, string[]> = new Map();
  for (const id of idSet) {
    adj.set(id, []);
  }
  for (const L of normalized.links) {
    const s: string = coerceGraphLinkEndpoint(L.source);
    const t: string = coerceGraphLinkEndpoint(L.target);
    if (!idSet.has(s) || !idSet.has(t)) {
      continue;
    }
    adj.get(s)!.push(t);
    adj.get(t)!.push(s);
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
  const nodes: MemoryGraphNode[] = normalized.nodes.filter((n) => reachable.has(n.id));
  const links: MemoryGraphLink[] = normalized.links.filter((L) => {
    const s: string = coerceGraphLinkEndpoint(L.source);
    const t: string = coerceGraphLinkEndpoint(L.target);
    return reachable.has(s) && reachable.has(t);
  });
  return { nodes, links };
}

export class MemoryGraphForceGraphProjector {
  /**
   * UC-04 ветка A: рёбра без обоих концов во множестве id узлов текущей проекции не попадают в выдачу ForceGraph.
   */
  static filterEdgesUc04BranchA(data: MemoryGraphData): MemoryGraphData {
    const ids: Set<string> = new Set(data.nodes.map((n) => n.id));
    const links: MemoryGraphLink[] = data.links.filter((L) => {
      const s: string = coerceGraphLinkEndpoint(L.source);
      const t: string = coerceGraphLinkEndpoint(L.target);
      return ids.has(s) && ids.has(t);
    });
    return { nodes: data.nodes, links };
  }

  /**
   * Проекция merged → graphData для `ForceGraph3D`: нормализация концов рёбер → **только** UC-04A.
   * Полный граф по узлам; фокус агента — подсветка (без reachability-gate).
   */
  static project(data: MemoryGraphData): MemoryGraphData {
    const step0: MemoryGraphData = normalizeMemoryGraphLinkEndpoints(data);
    return MemoryGraphForceGraphProjector.filterEdgesUc04BranchA(step0);
  }
}
