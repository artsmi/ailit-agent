import { describe, expect, it, vi } from "vitest";
import type { PagGraphSliceResult } from "@shared/ipc";

import { loadPagGraphMerged } from "./loadPagGraphMerged";

import { nodeFromPag, type MemoryGraphData } from "./memoryGraphState";
import {
  createEmptyPagGraphSessionSnapshot,
  PagGraphBySessionMap,
  PagGraphSessionFullLoad,
  PagGraphSessionTraceMerge
} from "./pagGraphSessionStore";

function rowPagNodeUpsert(
  namespace: string,
  rev: number,
  node: Record<string, unknown>
): Record<string, unknown> {
  return {
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "pag.node.upsert",
      payload: {
        kind: "pag.node.upsert",
        namespace,
        rev,
        node: { ...node, namespace }
      }
    }
  };
}

describe("pagGraphSessionStore", () => {
  it("keepsStateAcrossUnmount", () => {
    const a: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: {
        nodes: [nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: "ns" })!],
        links: []
      },
      lastAppliedTraceIndex: 0
    };
    const b: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: {
        nodes: [nodeFromPag({ node_id: "A:2", level: "A", path: ".", title: "p2", namespace: "ns" })!],
        links: []
      },
      lastAppliedTraceIndex: 0
    };
    const m: PagGraphBySessionMap = new PagGraphBySessionMap();
    m.set("session-a", a);
    m.set("session-b", b);
    expect(m.get("session-a")?.merged.nodes).toHaveLength(1);
    // «Переключение вкладки» не очищает store другой сессии: оба снимка в map.
    expect(m.get("session-b")?.merged.nodes[0]!.id).toBe("A:2");
    m.remove("session-b");
    expect(m.get("session-b")).toBeUndefined();
    expect(m.get("session-a")?.merged.nodes[0]!.id).toBe("A:1");
  });

  it("appliesDeltaTo2dAnd3d", () => {
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { "ns-a": 0 },
      lastAppliedTraceIndex: -1
    };
    const row: Record<string, unknown> = rowPagNodeUpsert("ns-a", 1, {
      node_id: "B:file.py",
      level: "B",
      path: "file.py",
      title: "f",
      kind: "file"
    });
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(base, [row], ["ns-a"], "ns-a");
    expect(nxt.merged.nodes.map((n) => n.id)).toContain("B:file.py");
    expect(nxt.lastAppliedTraceIndex).toBe(0);
    // 2D и 3D читают один `merged` из session store (см. MemoryGraphPage / MemoryGraph3DPage).
    const g2: MemoryGraphData = nxt.merged;
    const g3: MemoryGraphData = nxt.merged;
    expect(g2.nodes.length).toBe(g3.nodes.length);
  });

  it("activeSessionChangeLoadsFullGraph", async () => {
    const okSlice = (namespace: string): PagGraphSliceResult => ({
      ok: true,
      kind: "ailit_pag_graph_slice_v1",
      namespace,
      db_path: "/x.db",
      graph_rev: 1,
      pag_state: "ok",
      level_filter: null,
      nodes: [
        { node_id: "A:1", level: "A", path: ".", title: "p", kind: "project", namespace }
      ],
      edges: [],
      limits: { node_limit: 10000, node_offset: 0, edge_limit: 1, edge_offset: 0 },
      has_more: { nodes: false, edges: false }
    });
    const slice: ReturnType<typeof vi.fn> = vi.fn(
      async (p: { readonly namespace: string }): Promise<PagGraphSliceResult> => okSlice(p.namespace)
    );
    const c0: number = slice.mock.calls.length;
    const r1: Awaited<ReturnType<typeof PagGraphSessionFullLoad.run>> = await PagGraphSessionFullLoad.run(
      slice,
      ["ns1"]
    );
    expect(r1.ok).toBe(true);
    expect(slice.mock.calls.length).toBeGreaterThan(c0);
    const c1: number = slice.mock.calls.length;
    const r2: Awaited<ReturnType<typeof PagGraphSessionFullLoad.run>> = await PagGraphSessionFullLoad.run(
      slice,
      ["ns1"]
    );
    expect(r2.ok).toBe(true);
    // Повторный full load (как при смене active session / refresh) снова ходит в БД-slice, не в trace-only.
    expect(slice.mock.calls.length).toBeGreaterThan(c1);
  });

  it("manyTraceRowsWithDeltasDoNotTriggerPagGraphSlice", () => {
    const slice: ReturnType<typeof vi.fn> = vi.fn();
    const ns: string = "ns-noslice";
    const rows: Record<string, unknown>[] = [];
    for (let i: number = 0; i < 12; i += 1) {
      rows.push(
        rowPagNodeUpsert(ns, i + 1, {
          node_id: `B:n${String(i)}.py`,
          level: "B",
          path: `n${String(i)}.py`,
          title: "f",
          kind: "file"
        })
      );
    }
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { [ns]: 0 },
      lastAppliedTraceIndex: -1
    };
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(base, rows, [ns], ns);
    expect(slice).not.toHaveBeenCalled();
    expect(nxt.merged.nodes).toHaveLength(12);
    expect(nxt.lastAppliedTraceIndex).toBe(11);
  });

  it("revMismatchOnDeltaProducesWarning", () => {
    const ns: string = "ns-miss";
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { [ns]: 1 },
      lastAppliedTraceIndex: -1
    };
    const badRow: Record<string, unknown> = rowPagNodeUpsert(ns, 3, {
      node_id: "B:bad.py",
      level: "B",
      path: "bad.py",
      title: "f",
      kind: "file"
    });
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(base, [badRow], [ns], ns);
    const hasW: boolean = nxt.warnings.some((s: string) => s.includes("graph rev") || s.includes("несоответств"));
    expect(hasW).toBe(true);
  });

  it("initialTraceCatchupWhenGraphRevFromSliceExceedsFirstTraceRev1", () => {
    const ns: string = "ns-catchup-116";
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: {
        nodes: [
          nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: ns })!
        ],
        links: []
      },
      graphRevByNamespace: { [ns]: 116 },
      lastAppliedTraceIndex: -1
    };
    const rows: Record<string, unknown>[] = [];
    for (let r: number = 1; r <= 3; r += 1) {
      rows.push(
        rowPagNodeUpsert(ns, r, {
          node_id: `B:n${String(r)}.py`,
          level: "B",
          path: `n${String(r)}.py`,
          title: "f",
          kind: "file"
        })
      );
    }
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(base, rows, [ns], ns);
    const hasRevWarn: boolean = nxt.warnings.some(
      (s: string) => s.includes("graph rev") || s.includes("несоответств")
    );
    expect(hasRevWarn).toBe(false);
    expect(nxt.graphRevByNamespace[ns]).toBe(3);
  });

  it("multiNamespacePreservesSliceGraphRevForNamespaceWithoutDeltas", () => {
    const n1: string = "ns-a-slice";
    const n2: string = "ns-b-slice";
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { [n1]: 2, [n2]: 50 },
      lastAppliedTraceIndex: -1
    };
    const rows: Record<string, unknown>[] = [
      rowPagNodeUpsert(n1, 1, {
        node_id: "B:a.py",
        level: "B",
        path: "a.py",
        title: "a",
        kind: "file"
      }),
      rowPagNodeUpsert(n1, 2, {
        node_id: "B:b.py",
        level: "B",
        path: "b.py",
        title: "b",
        kind: "file"
      })
    ];
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> = PagGraphSessionTraceMerge.applyIncremental(
      base,
      rows,
      [n1, n2],
      n1
    );
    expect(nxt.graphRevByNamespace[n1]).toBe(2);
    expect(nxt.graphRevByNamespace[n2]).toBe(50);
  });

  it("afterFullLoadUsesInitialTraceCatchupWhenFirstDeltaRev1AndSliceGraphRev", () => {
    const ns: string = "ns-afl";
    const rows: Record<string, unknown>[] = [];
    for (let r: number = 1; r <= 3; r += 1) {
      rows.push(
        rowPagNodeUpsert(ns, r, {
          node_id: `B:n${String(r)}.py`,
          level: "B",
          path: `n${String(r)}.py`,
          title: "f",
          kind: "file"
        })
      );
    }
    const merged: MemoryGraphData = {
      nodes: [nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: ns })!],
      links: []
    };
    const snap: ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad> = PagGraphSessionTraceMerge.afterFullLoad(
      merged,
      { [ns]: 3 },
      rows,
      [ns],
      ns
    );
    const hasRevWarn: boolean = snap.warnings.some(
      (s: string) => s.includes("graph rev") || s.includes("несоответств")
    );
    expect(hasRevWarn).toBe(false);
    expect(snap.graphRevByNamespace[ns]).toBe(3);
  });

  it("runReturnsPagSqliteMissingWhenAllNamespacesReturnMissingDb", async () => {
    const missing: PagGraphSliceResult = {
      ok: false,
      kind: "ailit_pag_graph_slice_v1",
      error: "sqlite not found: /tmp/x.db",
      code: "missing_db"
    };
    const slice: ReturnType<typeof vi.fn> = vi.fn(
      async (): Promise<PagGraphSliceResult> => missing
    );
    const r: Awaited<ReturnType<typeof PagGraphSessionFullLoad.run>> = await PagGraphSessionFullLoad.run(
      slice,
      ["ns-a", "ns-b"]
    );
    expect(r.ok).toBe(true);
    if (!r.ok) {
      return;
    }
    expect(r.pagSqliteMissing).toBe(true);
    expect(r.merged.nodes).toHaveLength(0);
    expect(Object.keys(r.graphRevByNamespace)).toHaveLength(0);
  });

  it("loadPagGraphMergedPropagatesSliceErrorCode", async () => {
    const rSlice: PagGraphSliceResult = {
      ok: false,
      kind: "ailit_pag_graph_slice_v1",
      error: "no file",
      code: "missing_db"
    };
    const slice: ReturnType<typeof vi.fn> = vi.fn(async (): Promise<PagGraphSliceResult> => rSlice);
    const r = await loadPagGraphMerged(slice, { namespace: "n", level: null });
    expect(r.ok).toBe(false);
    if (r.ok) {
      return;
    }
    expect(r.errorCode).toBe("missing_db");
  });
});
