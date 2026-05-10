import { coerceGraphLinkEndpoint } from "./memoryGraphForceGraphProjection";
import type { MemoryGraphData, MemoryGraphNode } from "./memoryGraphState";

/** Рёбра, у которых `source` или `target` отсутствует среди `data.nodes` (UC-04 / рассинхрон id). */
export function countOrphanLinks(data: MemoryGraphData): number {
  const ids: Set<string> = new Set(data.nodes.map((n) => n.id));
  let n: number = 0;
  for (const L of data.links) {
    const s: string = coerceGraphLinkEndpoint(L.source);
    const t: string = coerceGraphLinkEndpoint(L.target);
    if (!ids.has(s) || !ids.has(t)) {
      n += 1;
    }
  }
  return n;
}

export function countNodesByLevel(data: MemoryGraphData): Readonly<Record<string, number>> {
  const m: Record<string, number> = { A: 0, B: 0, C: 0, D: 0, other: 0 };
  for (const node of data.nodes) {
    const lv: MemoryGraphNode["level"] = node.level;
    if (lv === "A" || lv === "B" || lv === "C" || lv === "D") {
      m[lv] = (m[lv] ?? 0) + 1;
    } else {
      m["other"] = (m["other"] ?? 0) + 1;
    }
  }
  return m;
}

/**
 * Non-A узлы из входа проекции, отсутствующие в выходе (ожидается ~0: 3D-проекция не режет узлы;
 * ненулевое значение — рассинхрон вход/выход или устаревший путь).
 */
export function countNonARemovedByProjection(input: MemoryGraphData, projected: MemoryGraphData): number {
  const outIds: Set<string> = new Set(projected.nodes.map((n) => n.id));
  let c: number = 0;
  for (const n of input.nodes) {
    if (n.level === "A") {
      continue;
    }
    if (!outIds.has(n.id)) {
      c += 1;
    }
  }
  return c;
}

export type Mem3dGraphHealthPanelRow = {
  readonly panel_id: string;
  readonly input_node_count: number;
  readonly input_link_count: number;
  readonly input_orphan_links: number;
  readonly input_non_a_count: number;
  readonly projected_node_count: number;
  readonly projected_link_count: number;
  readonly non_a_removed_by_projection: number;
};

export type Mem3dGraphHealthPayload = {
  readonly chat_id: string;
  readonly active_session_id: string;
  readonly graph_data_key: string;
  readonly layout_kind: string;
  readonly page_view: string;
  readonly last_applied_trace_index: number;
  readonly pag_database_present: boolean;
  readonly merged_node_count: number;
  readonly merged_link_count: number;
  readonly merged_level_counts: Readonly<Record<string, number>>;
  readonly merged_orphan_links: number;
  readonly panels: readonly Mem3dGraphHealthPanelRow[];
  readonly projected_node_total: number;
};

export function buildMem3dGraphHealthPayload(params: {
  readonly chatId: string;
  readonly activeSessionId: string;
  readonly graphDataKey: string;
  readonly layoutKind: string;
  readonly pageView: string;
  readonly lastAppliedTraceIndex: number;
  readonly pagDatabasePresent: boolean;
  readonly merged: MemoryGraphData;
  readonly panels: readonly {
    readonly panelId: string;
    readonly inputGraphData: MemoryGraphData;
    readonly graphData: MemoryGraphData;
  }[];
}): Mem3dGraphHealthPayload {
  const mergedLevel: Readonly<Record<string, number>> = countNodesByLevel(params.merged);
  const panelRows: Mem3dGraphHealthPanelRow[] = params.panels.map(
    (p): Mem3dGraphHealthPanelRow => ({
      panel_id: p.panelId,
      input_node_count: p.inputGraphData.nodes.length,
      input_link_count: p.inputGraphData.links.length,
      input_orphan_links: countOrphanLinks(p.inputGraphData),
      input_non_a_count: p.inputGraphData.nodes.filter((n) => n.level !== "A").length,
      projected_node_count: p.graphData.nodes.length,
      projected_link_count: p.graphData.links.length,
      non_a_removed_by_projection: countNonARemovedByProjection(p.inputGraphData, p.graphData)
    })
  );
  const projectedNodeTotal: number = panelRows.reduce((s, r) => s + r.projected_node_count, 0);
  return {
    chat_id: params.chatId,
    active_session_id: params.activeSessionId,
    graph_data_key: params.graphDataKey,
    layout_kind: params.layoutKind,
    page_view: params.pageView,
    last_applied_trace_index: params.lastAppliedTraceIndex,
    pag_database_present: params.pagDatabasePresent,
    merged_node_count: params.merged.nodes.length,
    merged_link_count: params.merged.links.length,
    merged_level_counts: mergedLevel,
    merged_orphan_links: countOrphanLinks(params.merged),
    panels: panelRows,
    projected_node_total: projectedNodeTotal
  };
}

export function mem3dGraphHealthSignature(payload: Mem3dGraphHealthPayload): string {
  const panelSig: string = payload.panels
    .map(
      (r) =>
        `${r.panel_id}:${String(r.input_node_count)}:${String(r.projected_node_count)}:${String(r.non_a_removed_by_projection)}:${String(r.input_orphan_links)}`
    )
    .join("|");
  return [
    String(payload.merged_node_count),
    String(payload.merged_link_count),
    String(payload.merged_orphan_links),
    String(payload.last_applied_trace_index),
    payload.layout_kind,
    payload.page_view,
    String(payload.projected_node_total),
    panelSig
  ].join("\u001f");
}
