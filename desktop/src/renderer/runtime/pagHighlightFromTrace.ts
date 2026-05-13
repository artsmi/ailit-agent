import { isUc03HighlightAllowedAtRowIndex } from "./chatTraceAmPhase";

/**
 * `ailit_desktop_pag_highlight_v1` — UI highlight from Context Ledger trace.
 *
 * D-HI-1: один канал `PagSearchHighlightV1`; порядок по trace, побеждает **последнее**
 * ненулевое событие после фильтра namespace (`highlightFromTraceRow` на каждой строке).
 *
 * Multi-namespace: вызывающий задаёт `targetNamespace` (или цикл по workspace в
 * `PagGraphSessionTraceMerge.applyHighlightFromTraceRows`); W14 / ledger события с чужим `namespace`
 * отбрасываются для данного среза.
 */

export type PagSearchHighlightV1 = {
  readonly kind: "pag.search.highlight";
  readonly namespace: string;
  readonly nodeIds: readonly string[];
  readonly edgeIds: readonly string[];
  readonly reason: string;
  readonly ttlMs: number;
  readonly intensity: "strong" | "normal";
  /** Корреляция с `memory.query_context` / W14 payload; default null если trace не несёт id. */
  readonly queryId: string | null;
};

const TTL_MS: number = 3000;

/** D16.1 — must match `ailit/agent_memory/pag_graph_trace.py` */
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

function refsFromV2ForNamespace(
  v: unknown,
  targetNamespace: string
): { readonly nodeIds: readonly string[]; readonly edgeIds: readonly string[] } {
  if (!Array.isArray(v)) {
    return { nodeIds: [], edgeIds: [] };
  }
  const nodeIds: string[] = [];
  const edgeIds: string[] = [];
  for (const raw of v) {
    const ref: Record<string, unknown> = asDict(raw);
    if (str(ref["namespace"]) !== targetNamespace) {
      continue;
    }
    nodeIds.push(...strList(ref["node_ids"]));
    edgeIds.push(...strList(ref["edge_ids"]));
  }
  return { nodeIds, edgeIds };
}

/** Нормализуем rel path к id узла PAG: `B:path/to.py`. */
export function bNodeIdFromPath(rel: string): string {
  let s: string = rel.replace(/\\/g, "/").replace(/^\//, "");
  s = s.replace(/^\.\//, "");
  return `B:${s}`;
}

export function highlightFromTraceRow(
  row: Record<string, unknown>,
  targetNamespace: string
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
      const ns: string = str(inner["namespace"] || targetNamespace) || targetNamespace;
      if (targetNamespace.length > 0 && ns.length > 0 && ns !== targetNamespace) {
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
      const qidRaw: string = str(inner["query_id"] ?? "").trim();
      const queryId: string | null = qidRaw.length > 0 ? qidRaw : null;
      return {
        kind: "pag.search.highlight",
        namespace: ns,
        nodeIds,
        edgeIds,
        reason: str(inner["reason"] ?? MEMORY_W14_GRAPH_HIGHLIGHT_EVENT),
        ttlMs,
        intensity: "strong",
        queryId
      };
    }
    if (eventName === "context.memory_injected") {
      const refsRaw: unknown = inner["project_refs"];
      if (Array.isArray(refsRaw) && refsRaw.length > 0) {
        const picked: { readonly nodeIds: readonly string[]; readonly edgeIds: readonly string[] } =
          refsFromV2ForNamespace(refsRaw, targetNamespace);
        if (picked.nodeIds.length === 0) {
          return null;
        }
        const edgeIds: readonly string[] =
          picked.edgeIds.length > 0 ? picked.edgeIds : strList(inner["edge_ids"]);
        return {
          kind: "pag.search.highlight",
          namespace: targetNamespace,
          nodeIds: picked.nodeIds,
          edgeIds,
          reason: str(
            inner["decision_summary"] ?? inner["reason"] ?? "context.memory_injected"
          ),
          ttlMs: TTL_MS,
          intensity: "strong",
          queryId: null
        };
      }
      const nodeIds: readonly string[] = strList(inner["node_ids"]);
      if (!nodeIds.length) {
        return null;
      }
      const resolvedNs: string = str(row["namespace"] ?? targetNamespace) || targetNamespace;
      if (resolvedNs !== targetNamespace) {
        return null;
      }
      return {
        kind: "pag.search.highlight",
        namespace: resolvedNs,
        nodeIds,
        edgeIds: strList(inner["edge_ids"]),
        reason: str(
          inner["decision_summary"] ?? inner["reason"] ?? "context.memory_injected"
        ),
        ttlMs: TTL_MS,
        intensity: "strong",
        queryId: null
      };
    }
    if (eventName === "context.compacted" || eventName === "context.restored") {
      const dNode = str(inner["d_node_id"]);
      const nodeIds = [dNode, ...strList(inner["linked_node_ids"])].filter((x) => x.length > 0);
      if (!nodeIds.length) {
        return null;
      }
      const rowNs: string = str(row["namespace"] ?? targetNamespace) || targetNamespace;
      if (rowNs !== targetNamespace) {
        return null;
      }
      return {
        kind: "pag.search.highlight",
        namespace: rowNs,
        nodeIds,
        edgeIds: [],
        reason: eventName,
        ttlMs: TTL_MS,
        intensity: "strong",
        queryId: null
      };
    }
  }
  return null;
}

/**
 * Последняя применимая подсветка по всему trace (не только по `rows[rows.length - 1]`).
 */
export function lastPagSearchHighlightFromTrace(
  rows: readonly Record<string, unknown>[],
  targetNamespace: string,
  gatingChatId?: string
): PagSearchHighlightV1 | null {
  let last: PagSearchHighlightV1 | null = null;
  for (let i: number = 0; i < rows.length; i += 1) {
    if (gatingChatId != null && gatingChatId.length > 0) {
      if (!isUc03HighlightAllowedAtRowIndex(rows, gatingChatId, i)) {
        continue;
      }
    }
    const h: PagSearchHighlightV1 | null = highlightFromTraceRow(rows[i]!, targetNamespace);
    if (h !== null) {
      last = h;
    }
  }
  return last;
}

/**
 * UC-02 A2 + D-HI-1: если индекс последней trace-строки не вырос относительно
 * `lastConsumedRowIndex`, не пересчитываем подсветку в «пустое» — удерживаем `previous`.
 * При росте trace — последнее ненулевое по полному trace (как `lastPagSearchHighlightFromTrace`).
 */
export function lastPagSearchHighlightFromTraceAfterMerge(
  rows: readonly Record<string, unknown>[],
  targetNamespace: string,
  previous: PagSearchHighlightV1 | null,
  lastConsumedRowIndex: number,
  gatingChatId?: string
): PagSearchHighlightV1 | null {
  const lastIndex: number = rows.length - 1;
  if (lastIndex < 0) {
    return previous;
  }
  if (lastIndex <= lastConsumedRowIndex) {
    return previous ?? lastPagSearchHighlightFromTrace(rows, targetNamespace, gatingChatId);
  }
  return lastPagSearchHighlightFromTrace(rows, targetNamespace, gatingChatId);
}
