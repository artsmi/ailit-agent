/**
 * `ailit_desktop_pag_highlight_v1` — UI highlight from Context Ledger trace.
 */

export type PagSearchHighlightV1 = {
  readonly kind: "pag.search.highlight";
  readonly namespace: string;
  readonly nodeIds: readonly string[];
  readonly edgeIds: readonly string[];
  readonly reason: string;
  readonly ttlMs: number;
  readonly intensity: "strong" | "normal";
};

const TTL_MS: number = 3000;

/** D16.1 — must match `tools/agent_core/runtime/pag_graph_trace.py` */
export const MEMORY_W14_GRAPH_HIGHLIGHT_EVENT: string = "memory.w14.graph_highlight";
const MEMORY_W14_GRAPH_HIGHLIGHT_SCHEMA: string = "ailit_memory_w14_graph_highlight_v1";

function str(x: unknown): string {
  if (typeof x === "string") {
    return x;
  }
  return x == null ? "" : String(x);
}

function asDict(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function strList(v: unknown): readonly string[] {
  if (!Array.isArray(v)) {
    return [];
  }
  return v.map((x) => str(x)).filter((x) => x.length > 0);
}

function refsFromV2(v: unknown): {
  readonly nodeIds: readonly string[];
  readonly edgeIds: readonly string[];
  readonly namespaces: readonly string[];
} {
  if (!Array.isArray(v)) {
    return { nodeIds: [], edgeIds: [], namespaces: [] };
  }
  const nodeIds: string[] = [];
  const edgeIds: string[] = [];
  const namespaces: string[] = [];
  for (const raw of v) {
    const ref: Record<string, unknown> = asDict(raw);
    const ns: string = str(ref["namespace"]);
    if (ns.length > 0) {
      namespaces.push(ns);
    }
    nodeIds.push(...strList(ref["node_ids"]));
    edgeIds.push(...strList(ref["edge_ids"]));
  }
  return { nodeIds, edgeIds, namespaces };
}

/** Нормализуем rel path к id узла PAG: `B:path/to.py`. */
export function bNodeIdFromPath(rel: string): string {
  let s: string = rel.replace(/\\/g, "/").replace(/^\//, "");
  s = s.replace(/^\.\//, "");
  return `B:${s}`;
}

export function highlightFromTraceRow(
  row: Record<string, unknown>,
  defaultNamespace: string
): PagSearchHighlightV1 | null {
  const typ: string = str(row["type"]);
  const pl: unknown = row["payload"];
  const p: Record<string, unknown> = asDict(pl);
  if (typ === "topic.publish") {
    const eventName: string = str(p["event_name"]);
    const inner: Record<string, unknown> = asDict(p["payload"]);
    if (eventName === MEMORY_W14_GRAPH_HIGHLIGHT_EVENT) {
      if (str(inner["schema"]) !== MEMORY_W14_GRAPH_HIGHLIGHT_SCHEMA) {
        return null;
      }
      const ns: string = str(inner["namespace"] || defaultNamespace) || defaultNamespace;
      if (defaultNamespace.length > 0 && ns.length > 0 && ns !== defaultNamespace) {
        return null;
      }
      const nodeIds: readonly string[] = strList(inner["node_ids"]);
      const edgeIds: readonly string[] = strList(inner["edge_ids"]);
      if (nodeIds.length === 0 && edgeIds.length === 0) {
        return null;
      }
      const ttlRaw: unknown = inner["ttl_ms"];
      const ttlMs: number =
        typeof ttlRaw === "number" && Number.isFinite(ttlRaw) && ttlRaw > 0
          ? Math.min(60000, Math.floor(ttlRaw))
          : TTL_MS;
      return {
        kind: "pag.search.highlight",
        namespace: ns,
        nodeIds,
        edgeIds,
        reason: str(inner["reason"] ?? MEMORY_W14_GRAPH_HIGHLIGHT_EVENT),
        ttlMs,
        intensity: "strong"
      };
    }
    if (eventName === "context.memory_injected") {
      const refs = refsFromV2(inner["project_refs"]);
      const nodeIds = refs.nodeIds.length > 0 ? refs.nodeIds : strList(inner["node_ids"]);
      if (!nodeIds.length) {
        return null;
      }
      return {
        kind: "pag.search.highlight",
        namespace:
          refs.namespaces[0] ??
          (str(row["namespace"] ?? defaultNamespace) || defaultNamespace),
        nodeIds,
        edgeIds: refs.edgeIds.length > 0 ? refs.edgeIds : strList(inner["edge_ids"]),
        reason: str(
          inner["decision_summary"] ?? inner["reason"] ?? "context.memory_injected"
        ),
        ttlMs: TTL_MS,
        intensity: "strong"
      };
    }
    if (eventName === "context.compacted" || eventName === "context.restored") {
      const dNode = str(inner["d_node_id"]);
      const nodeIds = [dNode, ...strList(inner["linked_node_ids"])].filter((x) => x.length > 0);
      if (!nodeIds.length) {
        return null;
      }
      return {
        kind: "pag.search.highlight",
        namespace: str(row["namespace"] ?? defaultNamespace) || defaultNamespace,
        nodeIds,
        edgeIds: [],
        reason: eventName,
        ttlMs: TTL_MS,
        intensity: "strong"
      };
    }
  }
  return null;
}
