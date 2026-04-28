import { describe, expect, it, vi } from "vitest";

import type { PagGraphSliceResult } from "@shared/ipc";

import { loadPagGraphMerged } from "./loadPagGraphMerged";

describe("loadPagGraphMerged", () => {
  it("пагинирует ноды и рёбра отдельными фазами и объединяет уникальные id", async () => {
    const slice = vi.fn(
      async (params: {
        readonly namespace: string;
        readonly nodeLimit: number;
        readonly nodeOffset: number;
        readonly edgeLimit: number;
        readonly edgeOffset: number;
      }): Promise<PagGraphSliceResult> => {
        if (params.nodeOffset === 0 && params.edgeLimit === 1) {
          return {
            ok: true,
            kind: "ailit_pag_graph_slice_v1",
            namespace: "ns",
            db_path: "/x.db",
            graph_rev: 3,
            pag_state: "ok",
            level_filter: null,
            nodes: [
              { node_id: "A:1", level: "A", path: ".", title: "p", kind: "project" }
            ],
            edges: [],
            limits: {
              node_limit: params.nodeLimit,
              node_offset: params.nodeOffset,
              edge_limit: params.edgeLimit,
              edge_offset: params.edgeOffset
            },
            has_more: { nodes: true, edges: false }
          };
        }
        if (params.nodeOffset > 0 && params.edgeLimit === 1) {
          return {
            ok: true,
            kind: "ailit_pag_graph_slice_v1",
            namespace: "ns",
            db_path: "/x.db",
            graph_rev: 3,
            pag_state: "ok",
            level_filter: null,
            nodes: [{ node_id: "B:2", level: "B", path: "a", title: "a", kind: "file" }],
            edges: [],
            limits: {
              node_limit: params.nodeLimit,
              node_offset: params.nodeOffset,
              edge_limit: params.edgeLimit,
              edge_offset: params.edgeOffset
            },
            has_more: { nodes: false, edges: false }
          };
        }
        if (params.edgeOffset === 0 && params.nodeLimit === 1) {
          return {
            ok: true,
            kind: "ailit_pag_graph_slice_v1",
            namespace: "ns",
            db_path: "/x.db",
            graph_rev: 3,
            pag_state: "ok",
            level_filter: null,
            nodes: [],
            edges: [
              {
                edge_id: "e1",
                from_node_id: "A:1",
                to_node_id: "B:2",
                edge_class: "c",
                edge_type: "t"
              }
            ],
            limits: {
              node_limit: params.nodeLimit,
              node_offset: params.nodeOffset,
              edge_limit: params.edgeLimit,
              edge_offset: params.edgeOffset
            },
            has_more: { nodes: false, edges: false }
          };
        }
        throw new Error("unexpected params");
      }
    );

    const r = await loadPagGraphMerged(slice, { namespace: "ns", level: null });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      return;
    }
    expect(r.graphRev).toBe(3);
    expect(r.nodes.map((n) => n["node_id"])).toEqual(["A:1", "B:2"]);
    expect(r.edges).toHaveLength(1);
    expect(slice).toHaveBeenCalledTimes(3);
  });
});
