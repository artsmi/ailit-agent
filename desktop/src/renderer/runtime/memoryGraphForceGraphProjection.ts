import { formatTraceConnNodeInsertedDiagnosticLine } from "./desktopSessionDiagnosticLog";
import type { MemoryGraphData, MemoryGraphLink, MemoryGraphNode } from "./memoryGraphState";

export type TraceConnSyntheticPayload = {
  readonly line: string;
  readonly dedupeKey: string;
  readonly namespace: string;
};

export type MemoryGraphProjectOptions = {
  readonly onTraceConnSynthetic?: (payload: TraceConnSyntheticPayload) => void;
};

const TRACE_CONN_ROOT_PREFIX: string = "ailit:trace-conn-root:";

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

export function traceConnRootNodeId(namespace: string): string {
  return `${TRACE_CONN_ROOT_PREFIX}${encodeURIComponent(namespace)}`;
}

function syntheticTraceConnEdgeId(namespace: string, repNodeId: string): string {
  return `ailit:trace-conn-edge:${encodeURIComponent(namespace)}\u001f${repNodeId}`;
}

function minLexId(ids: readonly string[]): string {
  let m: string = ids[0]!;
  for (let i: number = 1; i < ids.length; i += 1) {
    const x: string = ids[i]!;
    if (x < m) {
      m = x;
    }
  }
  return m;
}

function connectedComponents(
  nodes: readonly MemoryGraphNode[],
  links: readonly MemoryGraphLink[]
): string[][] {
  const idList: string[] = nodes.map((n) => n.id);
  const adj: Map<string, Set<string>> = new Map();
  for (const id of idList) {
    adj.set(id, new Set());
  }
  for (const L of links) {
    const a: Set<string> | undefined = adj.get(L.source);
    const b: Set<string> | undefined = adj.get(L.target);
    if (a === undefined || b === undefined) {
      continue;
    }
    a.add(L.target);
    b.add(L.source);
  }
  const visited: Set<string> = new Set();
  const comps: string[][] = [];
  const starts: string[] = [...idList].sort();
  for (const start of starts) {
    if (visited.has(start)) {
      continue;
    }
    const comp: string[] = [];
    const stack: string[] = [start];
    visited.add(start);
    while (stack.length > 0) {
      const u: string = stack.pop()!;
      comp.push(u);
      const nb: Set<string> | undefined = adj.get(u);
      if (nb === undefined) {
        continue;
      }
      for (const v of nb) {
        if (!visited.has(v)) {
          visited.add(v);
          stack.push(v);
        }
      }
    }
    comp.sort();
    comps.push(comp);
  }
  comps.sort((ca, cb) => {
    const ma: string = minLexId(ca);
    const mb: string = minLexId(cb);
    return ma < mb ? -1 : ma > mb ? 1 : 0;
  });
  return comps;
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
   * D-TRACE-CONN-1: при >1 связной компоненте после фильтра A — один узел `ailit:trace-conn-root:{namespace}`
   * и рёбра к минимальному id в каждой компоненте (детерминированно).
   */
  static ensureTraceConnectivity(
    data: MemoryGraphData,
    displayNamespace: string,
    opts?: MemoryGraphProjectOptions
  ): MemoryGraphData {
    const rootId: string = traceConnRootNodeId(displayNamespace);
    if (data.nodes.some((n) => n.id === rootId)) {
      return data;
    }
    const comps: string[][] = connectedComponents(data.nodes, data.links);
    if (comps.length <= 1) {
      return data;
    }
    const reps: string[] = comps.map((c) => minLexId(c)).sort();
    const dedupeKey: string = `${String(comps.length)}:${reps.join(",")}`;
    if (opts?.onTraceConnSynthetic) {
      const line: string = formatTraceConnNodeInsertedDiagnosticLine({
        isoTimestamp: new Date().toISOString(),
        namespace: displayNamespace,
        componentCount: comps.length,
        representativeNodeIds: reps
      });
      opts.onTraceConnSynthetic({ line, dedupeKey, namespace: displayNamespace });
    }
    const rootNode: MemoryGraphNode = {
      id: rootId,
      label: "trace-conn",
      level: "C",
      namespace: displayNamespace
    };
    const newLinks: MemoryGraphLink[] = [...data.links];
    for (const comp of comps) {
      const rep: string = minLexId(comp);
      newLinks.push({
        id: syntheticTraceConnEdgeId(displayNamespace, rep),
        source: rootId,
        target: rep,
        edgeType: "ailit.trace_conn"
      });
    }
    return {
      nodes: [...data.nodes, rootNode],
      links: newLinks
    };
  }

  static project(
    data: MemoryGraphData,
    displayNamespace: string,
    opts?: MemoryGraphProjectOptions
  ): MemoryGraphData {
    const step1: MemoryGraphData = MemoryGraphForceGraphProjector.filterEdgesUc04BranchA(data);
    return MemoryGraphForceGraphProjector.ensureTraceConnectivity(step1, displayNamespace, opts);
  }
}
