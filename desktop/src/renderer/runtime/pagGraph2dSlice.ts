import type { MemoryGraphData, MemoryGraphNode } from "./memoryGraphState";
import { MEM3D_PAG_MAX_NODES, PAG_2D_PAGE_EDGE, PAG_2D_PAGE_NODE } from "./pagGraphLimits";

export type LevelFilter2d = "all" | "A" | "B" | "C";

/**
 * Paging для 2D-списка на основе единого merged-графа (G13.6; без отдельного
 * pagGraphSlice на каждую trace-строку).
 */
export class PagGraph2dListBuilder {
  static build(
    merged: MemoryGraphData,
    namespace: string,
    level: LevelFilter2d,
    nodeOff: number,
    edgeOff: number
  ): {
    readonly nodes: readonly MemoryGraphNode[];
    readonly edges: { readonly id: string; readonly from: string; readonly to: string; readonly et: string }[];
    readonly hasMore: { readonly nodes: boolean; readonly edges: boolean };
    readonly atNamespaceNodeCap: boolean;
  } {
    const nspace: string = namespace;
    const allN: MemoryGraphNode[] = merged.nodes.filter(
      (n) => n.namespace === nspace && (level === "all" || n.level === level)
    );
    const atNamespaceNodeCap: boolean = allN.length >= MEM3D_PAG_MAX_NODES;
    const byId: Set<string> = new Set(allN.map((n) => n.id));
    const allE: { readonly id: string; readonly from: string; readonly to: string; readonly et: string }[] = [];
    for (const l of merged.links) {
      if (byId.has(l.source) && byId.has(l.target)) {
        allE.push({
          id: l.id,
          from: l.source,
          to: l.target,
          et: l.edgeType ?? ""
        });
      }
    }
    const pagedNodes: MemoryGraphNode[] = allN.slice(nodeOff, nodeOff + PAG_2D_PAGE_NODE);
    const pagedEdges: { readonly id: string; readonly from: string; readonly to: string; readonly et: string }[] = allE.slice(
      edgeOff,
      edgeOff + PAG_2D_PAGE_EDGE
    );
    return {
      nodes: pagedNodes,
      edges: pagedEdges,
      hasMore: {
        nodes: nodeOff + PAG_2D_PAGE_NODE < allN.length,
        edges: edgeOff + PAG_2D_PAGE_EDGE < allE.length
      },
      atNamespaceNodeCap
    };
  }
}
