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
    if (eventName === "context.memory_injected") {
      const nodeIds = strList(inner["node_ids"]);
      if (!nodeIds.length) {
        return null;
      }
      return {
        kind: "pag.search.highlight",
        namespace: str(row["namespace"] ?? defaultNamespace) || defaultNamespace,
        nodeIds,
        edgeIds: strList(inner["edge_ids"]),
        reason: str(inner["reason"] ?? "context.memory_injected"),
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
