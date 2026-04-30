import {
  linkFromPag,
  mergeMemoryGraph,
  nodeFromPag,
  type MemoryGraphData,
  type MemoryGraphLink,
  type MemoryGraphNode
} from "./memoryGraphState";
import { formatPagGraphRevMismatchWarning } from "./pagGraphRevWarningFormat";

function str(x: unknown): string {
  return typeof x === "string" ? x : x == null ? "" : String(x);
}

function asDict(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asNonNegInt(x: unknown): number | null {
  if (typeof x === "number" && Number.isInteger(x) && x >= 0) {
    return x;
  }
  return null;
}

export type PagNodeUpsertTrace = {
  readonly kind: "pag.node.upsert";
  readonly namespace: string;
  readonly rev: number;
  readonly node: Record<string, unknown>;
};

export type PagEdgeUpsertTrace = {
  readonly kind: "pag.edge.upsert";
  readonly namespace: string;
  readonly rev: number;
  readonly edges: readonly Record<string, unknown>[];
};

export type PagGraphTraceDelta = PagNodeUpsertTrace | PagEdgeUpsertTrace;

/** Разобрать envelope trace (topic.publish) в дельту PAG, если применимо. */
export function parsePagGraphTraceDelta(
  row: Readonly<Record<string, unknown>>
): PagGraphTraceDelta | null {
  if (str(row["type"]) !== "topic.publish") {
    return null;
  }
  const p: Record<string, unknown> = asDict(row["payload"]);
  const en: string = str(p["event_name"]);
  const inner: Record<string, unknown> = asDict(p["payload"]);
  const k: string = str(inner["kind"]);
  const namespace: string = str(inner["namespace"]);
  if (!namespace) {
    return null;
  }
  const r: number | null = asNonNegInt(inner["rev"]);
  if (r === null) {
    return null;
  }
  if (en === "pag.node.upsert" && k === "pag.node.upsert") {
    const n: Record<string, unknown> = { ...asDict(inner["node"]), namespace };
    return { kind: "pag.node.upsert", namespace, rev: r, node: n };
  }
  if (en === "pag.edge.upsert" && k === "pag.edge.upsert") {
    const raw: unknown = inner["edges"];
    if (!Array.isArray(raw) || raw.length === 0) {
      return null;
    }
    const edges: Record<string, unknown>[] = raw.map((x) =>
      asDict(x)
    ) as Record<string, unknown>[];
    return { kind: "pag.edge.upsert", namespace, rev: r, edges };
  }
  return null;
}

/**
 * Смержить дельту в нативный Memory 3D graph.
 * @param lastRevs state rev по namespace; обновлённые ключи пишет в newRevsOut.
 * @returns сообщение о рассинхроне rev либо null
 */
export function applyPagGraphTraceDelta(
  current: MemoryGraphData,
  delta: PagGraphTraceDelta,
  lastRevs: Readonly<Record<string, number>>,
  newRevsOut: Record<string, number>
): { readonly data: MemoryGraphData; readonly revWarning: string | null } {
  for (const [k, v] of Object.entries(lastRevs)) {
    newRevsOut[k] = v;
  }
  const last: number = newRevsOut[delta.namespace] ?? 0;
  let revWarning: string | null = null;
  if (last > 0 && delta.rev !== last + 1) {
    revWarning = formatPagGraphRevMismatchWarning(delta.namespace, last + 1, delta.rev);
  }
  newRevsOut[delta.namespace] = delta.rev;
  if (delta.kind === "pag.node.upsert") {
    const m: MemoryGraphNode | null = nodeFromPag(delta.node);
    const nxt: MemoryGraphData =
      m === null
        ? current
        : mergeMemoryGraph(current, { nodes: [m], links: [] });
    return { data: nxt, revWarning };
  }
  const links: MemoryGraphLink[] = [];
  for (const e of delta.edges) {
    const L: MemoryGraphLink | null = linkFromPag(e);
    if (L !== null) {
      links.push(L);
    }
  }
  const nxt: MemoryGraphData = mergeMemoryGraph(current, { nodes: [], links: links });
  return { data: nxt, revWarning };
}
