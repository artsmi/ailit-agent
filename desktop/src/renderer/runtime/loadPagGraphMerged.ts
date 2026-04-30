import type { PagGraphSliceResult } from "@shared/ipc";

import { MEM3D_PAG_MAX_EDGES, MEM3D_PAG_MAX_NODES } from "./pagGraphLimits";

function errorFromFailedSlice(
  r: Extract<PagGraphSliceResult, { readonly ok: false }>
): { readonly error: string; readonly errorCode: string | undefined } {
  return { error: r.error, errorCode: r.code };
}

const MAX_NODE: number = MEM3D_PAG_MAX_NODES;
const MAX_EDGE: number = MEM3D_PAG_MAX_EDGES;

export type PagGraphSliceFn = (params: {
  readonly namespace: string;
  readonly dbPath?: string;
  readonly level: string | null;
  readonly nodeLimit: number;
  readonly nodeOffset: number;
  readonly edgeLimit: number;
  readonly edgeOffset: number;
}) => Promise<PagGraphSliceResult>;

/**
 * Загрузить полный срез PAG с пагинацией до лимитов MEM3D_PAG_MAX_* (G12.2, D-SCL-1).
 * Сначала собираем все ноды (min edge-страница), затем рёбра.
 */
export async function loadPagGraphMerged(
  slice: PagGraphSliceFn,
  params: { readonly namespace: string; readonly level: string | null; readonly dbPath?: string }
): Promise<
  | {
      readonly ok: true;
      readonly graphRev: number;
      readonly pag_state: string;
      readonly nodes: readonly Record<string, unknown>[];
      readonly edges: readonly Record<string, unknown>[];
    }
  | { readonly ok: false; readonly error: string; readonly errorCode: string | undefined }
> {
  const byNode: Map<string, Record<string, unknown>> = new Map();
  const byEdge: Map<string, Record<string, unknown>> = new Map();
  let graphRev: number = 0;
  let pag_state: string = "ok";

  let nodeOff: number = 0;
  for (;;) {
    const r: PagGraphSliceResult = await slice({
      namespace: params.namespace,
      dbPath: params.dbPath,
      level: params.level,
      nodeLimit: MAX_NODE,
      nodeOffset: nodeOff,
      edgeLimit: 1,
      edgeOffset: 0
    });
    if (!r.ok) {
      const ex: { readonly error: string; readonly errorCode: string | undefined } = errorFromFailedSlice(r);
      return { ok: false, error: ex.error, errorCode: ex.errorCode };
    }
    if (typeof r.graph_rev === "number") {
      graphRev = r.graph_rev;
    }
    pag_state = r.pag_state;
    for (const n of r.nodes) {
      const rec: Record<string, unknown> = n as Record<string, unknown>;
      const id: string = String(rec["node_id"] ?? "");
      if (id.length > 0) {
        byNode.set(id, rec);
      }
    }
    if (!r.has_more.nodes) {
      break;
    }
    nodeOff += MAX_NODE;
  }

  let edgeOff: number = 0;
  for (;;) {
    const r: PagGraphSliceResult = await slice({
      namespace: params.namespace,
      dbPath: params.dbPath,
      level: params.level,
      nodeLimit: 1,
      nodeOffset: 0,
      edgeLimit: MAX_EDGE,
      edgeOffset: edgeOff
    });
    if (!r.ok) {
      const ex: { readonly error: string; readonly errorCode: string | undefined } = errorFromFailedSlice(r);
      return { ok: false, error: ex.error, errorCode: ex.errorCode };
    }
    if (typeof r.graph_rev === "number") {
      graphRev = r.graph_rev;
    }
    pag_state = r.pag_state;
    for (const e of r.edges) {
      const rec: Record<string, unknown> = e as Record<string, unknown>;
      const id: string = String(rec["edge_id"] ?? "");
      if (id.length > 0) {
        byEdge.set(id, rec);
      }
    }
    if (!r.has_more.edges) {
      break;
    }
    edgeOff += MAX_EDGE;
  }

  return {
    ok: true,
    graphRev,
    pag_state,
    nodes: [...byNode.values()],
    edges: [...byEdge.values()]
  };
}
