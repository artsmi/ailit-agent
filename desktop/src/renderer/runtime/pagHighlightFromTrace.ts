/**
 * `ailit_desktop_pag_highlight_v1` — только UI, из trace (G9.8.2).
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

/** Нормализуем rel path к id узла PAG: `B:path/to.py`. */
export function bNodeIdFromPath(rel: string): string {
  let s: string = rel.replace(/\\/g, "/").replace(/^\//, "");
  s = s.replace(/^\.\//, "");
  return `B:${s}`;
}

/**
 * Подсветка по событиям memory query / grant в trace. Edge ids не стабильны в runtime — пусто.
 */
export function highlightFromTraceRow(
  row: Record<string, unknown>,
  defaultNamespace: string
): PagSearchHighlightV1 | null {
  const typ: string = str(row["type"]);
  const to: string = str(row["to_agent"]);
  const pl: unknown = row["payload"];
  const p: Record<string, unknown> =
    pl && typeof pl === "object" && !Array.isArray(pl) ? (pl as Record<string, unknown>) : {};
  const service: string = str(p["service"] ?? "");
  if (typ === "service.request" && to.startsWith("AgentMemory") && service === "memory.query_context") {
    const path0: string = str(p["path"] ?? p["hint_path"] ?? "");
    if (!path0) {
      return null;
    }
    return {
      kind: "pag.search.highlight",
      namespace: str(row["namespace"] ?? defaultNamespace) || defaultNamespace,
      nodeIds: [bNodeIdFromPath(path0)],
      edgeIds: [],
      reason: "AgentMemory search (request)",
      ttlMs: TTL_MS,
      intensity: "strong"
    };
  }
  if (row["ok"] === true && p["grants"] && Array.isArray(p["grants"])) {
    const ids: string[] = [];
    for (const g of p["grants"] as readonly unknown[]) {
      if (g && typeof g === "object" && g !== null) {
        const pth: string = str((g as { path?: string }).path ?? "");
        if (pth) {
          ids.push(bNodeIdFromPath(pth));
        }
      }
    }
    if (!ids.length) {
      return null;
    }
    return {
      kind: "pag.search.highlight",
      namespace: str(row["namespace"] ?? defaultNamespace) || defaultNamespace,
      nodeIds: ids,
      edgeIds: [],
      reason: "AgentMemory (grant)",
      ttlMs: TTL_MS,
      intensity: "normal"
    };
  }
  return null;
}