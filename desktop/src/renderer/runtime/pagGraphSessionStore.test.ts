import { describe, expect, it, vi } from "vitest";
import type { PagGraphSliceResult } from "@shared/ipc";

import { loadPagGraphMerged } from "./loadPagGraphMerged";

import { nodeFromPag, type MemoryGraphData } from "./memoryGraphState";
import {
  buildPagGraphRevReconciledTraceRow,
  buildPagSnapshotRefreshedTraceRow,
  DESKTOP_TRACE_REPLAY_END_EVENT,
  DESKTOP_TRACE_REPLAY_START_EVENT,
  extractCompactPagEventPayload
} from "./pagGraphObservabilityCompact";
import {
  collapsePagGraphRevMismatchWarningsToLatestPerNamespace,
  dedupePagGraphSnapshotWarnings,
  formatPagGraphRevMismatchWarning,
  reconcileStalePagGraphRevMismatchWarnings,
  tryParsePagGraphRevMismatchDedupeKey
} from "./pagGraphRevWarningFormat";
import {
  applyDeltasInRange,
  buildSnapshotFromReconcile,
  createEmptyPagGraphSessionSnapshot,
  PagGraphBySessionMap,
  PagGraphSessionFullLoad,
  PagGraphSessionTraceMerge,
  type PagGraphTraceMergeEmitHooks,
  type PagGraphSessionSnapshot
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

function rowW14GraphHighlight(namespace: string, nodeIds: readonly string[]): Record<string, unknown> {
  return {
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "memory.w14.graph_highlight",
      payload: {
        schema: "ailit_memory_w14_graph_highlight_v1",
        namespace,
        node_ids: [...nodeIds],
        edge_ids: [],
        reason: "t",
        ttl_ms: 3000
      }
    }
  };
}

function rowMemoryQueryStart(chatId: string): Record<string, unknown> {
  return {
    chat_id: chatId,
    type: "service.request",
    from_agent: `AgentWork:${chatId}`,
    to_agent: "AgentMemory:mem",
    payload: { service: "memory.query_context", query_id: "q-hl" }
  };
}

/** Одна строка trace — два namespace в `project_refs` (G3 / unified multi highlight). */
function rowContextMemoryInjectedV2DualNamespace(): Record<string, unknown> {
  return {
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "context.memory_injected",
      payload: {
        schema: "context.memory_injected.v2",
        project_refs: [
          {
            project_id: "p-a",
            namespace: "ns-g3-a",
            node_ids: ["B:g3-a.py"],
            edge_ids: ["e-a"]
          },
          {
            project_id: "p-b",
            namespace: "ns-g3-b",
            node_ids: ["B:g3-b.py"],
            edge_ids: []
          }
        ],
        decision_summary: "dual ref"
      }
    }
  };
}

/** Триггер B: `user_prompt` в нормализации trace (`traceNormalize`) перед новым циклом AM. */
function rowUserPrompt(chatId: string): Record<string, unknown> {
  return {
    chat_id: chatId,
    type: "action.start",
    message_id: `msg-user-${chatId}`,
    created_at: "2026-05-05T00:00:00Z",
    from_agent: "User:desktop",
    to_agent: `AgentWork:${chatId}`,
    payload: {
      action: "work.handle_user_prompt",
      prompt: "stub"
    }
  };
}

function mergeHooksForHighlightGating(chatId: string, defaultNs: string): PagGraphTraceMergeEmitHooks {
  return {
    chatId,
    sessionId: "sess-hl",
    graphRevBeforeByNamespace: {},
    defaultNamespace: defaultNs
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
      limits: { node_limit: 20000, node_offset: 0, edge_limit: 1, edge_offset: 0 },
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
    expect(nxt.warnings.some((s: string) => s.includes(`для «${ns}»`))).toBe(true);
  });

  it("dedupesDuplicateRevMismatchWarningsByNamespaceTriple", () => {
    const ns: string = "ns-dup";
    const a: string = formatPagGraphRevMismatchWarning(ns, 2, 3);
    const b: string = formatPagGraphRevMismatchWarning(ns, 2, 3);
    expect(dedupePagGraphSnapshotWarnings([a, b])).toEqual([a]);
  });

  it("afterFullLoadWithAlignedSliceClearsRevMismatchFromMisalignedIncremental", async () => {
    const ns: string = "ns-refresh-align";
    const badRow: Record<string, unknown> = rowPagNodeUpsert(ns, 5, {
      node_id: "B:only.py",
      level: "B",
      path: "only.py",
      title: "f",
      kind: "file"
    });
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { [ns]: 1 },
      lastAppliedTraceIndex: -1
    };
    const mis: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(base, [badRow], [ns], ns);
    expect(mis.warnings.length).toBeGreaterThan(0);
    const merged: MemoryGraphData = {
      nodes: [
        nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: ns })!,
        nodeFromPag({
          node_id: "B:only.py",
          level: "B",
          path: "only.py",
          title: "f",
          namespace: ns
        })!
      ],
      links: []
    };
    const healed: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad(merged, { [ns]: 4 }, [badRow], [ns], ns, true);
    const revWarns: number = healed.warnings.filter(
      (s: string) => s.includes("graph rev") || s.includes("несоответств")
    ).length;
    expect(revWarns).toBe(0);
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

  it("afterFullLoadUsesInitialTraceCatchupWhenFirstDeltaRev1AndSliceGraphRev", async () => {
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
    const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad(merged, { [ns]: 3 }, rows, [ns], ns);
    const hasRevWarn: boolean = snap.warnings.some(
      (s: string) => s.includes("graph rev") || s.includes("несоответств")
    );
    expect(hasRevWarn).toBe(false);
    expect(snap.graphRevByNamespace[ns]).toBe(3);
  });

  it("createEmptyDefaultsPagDatabasePresentTrue", () => {
    const e: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = createEmptyPagGraphSessionSnapshot();
    expect(e.pagDatabasePresent).toBe(true);
  });

  it("afterFullLoadAllMissingYieldsReadyAndPagDatabasePresentFalse", async () => {
    const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad({ nodes: [], links: [] }, {}, [], ["ns1"], "ns1", false);
    expect(snap.loadState).toBe("ready");
    expect(snap.loadError).toBeNull();
    expect(snap.pagDatabasePresent).toBe(false);
  });

  it("applyIncrementalPreservesPagDatabasePresent", () => {
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      pagDatabasePresent: false,
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
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> = PagGraphSessionTraceMerge.applyIncremental(
      base,
      [row],
      ["ns-a"],
      "ns-a"
    );
    expect(nxt.merged.nodes.length).toBeGreaterThan(0);
    expect(nxt.pagDatabasePresent).toBe(false);
  });

  it("afterFullLoadTogglesPagDatabasePresentWhenDatabaseAppears", async () => {
    const ns: string = "ns-flip";
    const n0: ReturnType<typeof nodeFromPag> = nodeFromPag({
      node_id: "A:1",
      level: "A",
      path: ".",
      title: "p",
      namespace: ns
    })!;
    const snap0: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad({ nodes: [], links: [] }, {}, [], [ns], ns, false);
    expect(snap0.pagDatabasePresent).toBe(false);
    const snap1: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad(
        { nodes: [n0], links: [] },
        { [ns]: 1 },
        [],
        [ns],
        ns,
        true
      );
    expect(snap1.pagDatabasePresent).toBe(true);
    expect(snap1.loadState).toBe("ready");
  });

  it("runPartialOneMissingOneOkHasPagDatabasePresentImplied", async () => {
    const okNsB: PagGraphSliceResult = {
      ok: true,
      kind: "ailit_pag_graph_slice_v1",
      namespace: "ns-b",
      db_path: "/b.db",
      graph_rev: 1,
      pag_state: "ok",
      level_filter: null,
      nodes: [
        { node_id: "A:1", level: "A", path: ".", title: "p", kind: "project", namespace: "ns-b" }
      ],
      edges: [],
      limits: { node_limit: 20000, node_offset: 0, edge_limit: 1, edge_offset: 0 },
      has_more: { nodes: false, edges: false }
    };
    const missing: PagGraphSliceResult = {
      ok: false,
      kind: "ailit_pag_graph_slice_v1",
      error: "sqlite not found",
      code: "missing_db"
    };
    const slice: ReturnType<typeof vi.fn> = vi.fn(
      async (p: { readonly namespace: string }): Promise<PagGraphSliceResult> => {
        if (p.namespace === "ns-a") {
          return missing;
        }
        if (p.namespace === "ns-b") {
          return okNsB;
        }
        return missing;
      }
    );
    const r: Awaited<ReturnType<typeof PagGraphSessionFullLoad.run>> = await PagGraphSessionFullLoad.run(
      slice,
      ["ns-a", "ns-b"]
    );
    expect(r.ok).toBe(true);
    if (!r.ok) {
      return;
    }
    expect(r.pagSqliteMissing).toBeFalsy();
    const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad(
        r.merged,
        r.graphRevByNamespace,
        [],
        ["ns-a", "ns-b"],
        "ns-b",
        true
      );
    expect(snap.pagDatabasePresent).toBe(true);
    expect(snap.merged.nodes.length).toBeGreaterThan(0);
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

  it("runReturnsPagSqliteMissingWhenSqliteNotFoundTextWithoutErrorCode", async () => {
    const missing: PagGraphSliceResult = {
      ok: false,
      kind: "ailit_pag_graph_slice_v1",
      error: "sqlite not found: /home/x/.ailit/pag/store.sqlite3"
    };
    const slice: ReturnType<typeof vi.fn> = vi.fn(
      async (): Promise<PagGraphSliceResult> => missing
    );
    const r: Awaited<ReturnType<typeof PagGraphSessionFullLoad.run>> = await PagGraphSessionFullLoad.run(
      slice,
      ["_home_x_repo"]
    );
    expect(r.ok).toBe(true);
    if (!r.ok) {
      return;
    }
    expect(r.pagSqliteMissing).toBe(true);
  });

  describe("TC-VITEST-STORE-HL-01", () => {
    it("applies W14 in snapshot after memory.query_context when gating on", async () => {
      const chatId: string = "chat-hl-01";
      const ns: string = "ns-hl-01";
      const rows: Record<string, unknown>[] = [rowMemoryQueryStart(chatId), rowW14GraphHighlight(ns, ["B:gated.py"])];
      const hooks: PagGraphTraceMergeEmitHooks = mergeHooksForHighlightGating(chatId, ns);
      const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad({ nodes: [], links: [] }, { [ns]: 1 }, rows, [ns], ns, true, hooks);
      expect(snap.merged.nodes.map((n) => n.id)).toContain("B:gated.py");
      expect(snap.searchHighlightsByNamespace[ns]?.nodeIds).toContain("B:gated.py");
    });

    it("skips W14 before trigger A/B when gating on", async () => {
      const chatId: string = "chat-hl-02";
      const ns: string = "ns-hl-02";
      const rows: Record<string, unknown>[] = [
        rowW14GraphHighlight(ns, ["B:before-trigger.py"]),
        rowMemoryQueryStart(chatId)
      ];
      const hooks: PagGraphTraceMergeEmitHooks = mergeHooksForHighlightGating(chatId, ns);
      const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad({ nodes: [], links: [] }, { [ns]: 1 }, rows, [ns], ns, true, hooks);
      expect(snap.merged.nodes.map((n) => n.id)).not.toContain("B:before-trigger.py");
      expect(snap.searchHighlightsByNamespace[ns]).toBeNull();
    });

    it("allows highlight after trigger B (user_prompt then memory.query_context then W14)", async () => {
      const chatId: string = "chat-hl-b";
      const ns: string = "ns-hl-b";
      const rows: Record<string, unknown>[] = [
        rowUserPrompt(chatId),
        rowMemoryQueryStart(chatId),
        rowW14GraphHighlight(ns, ["B:trigger-b.py"])
      ];
      const hooks: PagGraphTraceMergeEmitHooks = mergeHooksForHighlightGating(chatId, ns);
      const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad({ nodes: [], links: [] }, { [ns]: 1 }, rows, [ns], ns, true, hooks);
      expect(snap.searchHighlightsByNamespace[ns]?.nodeIds).toContain("B:trigger-b.py");
      expect(snap.merged.nodes.map((n) => n.id)).toContain("B:trigger-b.py");
    });

    it("uses highlightGatingChatId when compact observability hooks are absent", async () => {
      const chatId: string = "chat-hl-no-hooks";
      const ns: string = "ns-hl-no-hooks";
      const rows: Record<string, unknown>[] = [rowMemoryQueryStart(chatId), rowW14GraphHighlight(ns, ["B:no-emit.py"])];
      const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad(
          { nodes: [], links: [] },
          { [ns]: 1 },
          rows,
          [ns],
          ns,
          true,
          undefined,
          chatId
        );
      expect(snap.searchHighlightsByNamespace[ns]?.nodeIds).toContain("B:no-emit.py");
    });
  });

  describe("TC-VITEST-NS-01", () => {
    it("stores W14 for second namespace only in searchHighlightsByNamespace after full load", async () => {
      const chatId: string = "chat-ns-01";
      const n1: string = "ns-a-hl";
      const n2: string = "ns-b-hl";
      const rows: Record<string, unknown>[] = [
        rowMemoryQueryStart(chatId),
        rowW14GraphHighlight(n2, ["B:second-only.py"])
      ];
      const hooks: PagGraphTraceMergeEmitHooks = mergeHooksForHighlightGating(chatId, n1);
      const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad(
          { nodes: [], links: [] },
          { [n1]: 1, [n2]: 1 },
          rows,
          [n1, n2],
          n1,
          true,
          hooks
        );
      expect(snap.searchHighlightsByNamespace[n1]).toBeNull();
      expect(snap.searchHighlightsByNamespace[n2]?.nodeIds).toContain("B:second-only.py");
      expect(snap.merged.nodes.map((n) => n.id)).toContain("B:second-only.py");
    });

    it("G3: single context.memory_injected v2 fills searchHighlightsByNamespace for both workspace namespaces", async () => {
      const n1: string = "ns-g3-a";
      const n2: string = "ns-g3-b";
      const rows: Record<string, unknown>[] = [rowContextMemoryInjectedV2DualNamespace()];
      const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad(
          { nodes: [], links: [] },
          { [n1]: 1, [n2]: 1 },
          rows,
          [n1, n2],
          n1,
          true
        );
      expect(snap.searchHighlightsByNamespace[n1]?.nodeIds).toEqual(expect.arrayContaining(["B:g3-a.py"]));
      expect(snap.searchHighlightsByNamespace[n1]?.edgeIds).toEqual(expect.arrayContaining(["e-a"]));
      expect(snap.searchHighlightsByNamespace[n2]?.nodeIds).toEqual(expect.arrayContaining(["B:g3-b.py"]));
      expect(snap.merged.nodes.map((n) => n.id)).toEqual(
        expect.arrayContaining(["B:g3-a.py", "B:g3-b.py"])
      );
    });

    it("splits per-namespace W14 on incremental merge", async () => {
      const chatId: string = "chat-ns-inc";
      const n1: string = "ns-inc-a";
      const n2: string = "ns-inc-b";
      const baseRows: Record<string, unknown>[] = [rowMemoryQueryStart(chatId)];
      const hooks: PagGraphTraceMergeEmitHooks = mergeHooksForHighlightGating(chatId, n1);
      const snap0: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad(
          { nodes: [], links: [] },
          { [n1]: 1, [n2]: 1 },
          baseRows,
          [n1, n2],
          n1,
          true,
          hooks
        );
      const rowsAll: Record<string, unknown>[] = [
        ...baseRows,
        rowW14GraphHighlight(n1, ["B:inc-a.py"]),
        rowW14GraphHighlight(n2, ["B:inc-b.py"])
      ];
      const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
        PagGraphSessionTraceMerge.applyIncremental(snap0, rowsAll, [n1, n2], n1, hooks);
      expect(nxt.searchHighlightsByNamespace[n1]?.nodeIds).toContain("B:inc-a.py");
      expect(nxt.searchHighlightsByNamespace[n2]?.nodeIds).toContain("B:inc-b.py");
      expect(nxt.merged.nodes.map((n) => n.id)).toEqual(
        expect.arrayContaining(["B:inc-a.py", "B:inc-b.py"])
      );
    });
  });

  it("afterFullLoadUsesLastApplicableHighlightWhenTailIsPagDeltaOnly", async () => {
    const ns: string = "ns-htail";
    const rows: Record<string, unknown>[] = [
      rowW14GraphHighlight(ns, ["B:hl.py"]),
      rowPagNodeUpsert(ns, 1, {
        node_id: "B:other.py",
        level: "B",
        path: "other.py",
        title: "o",
        kind: "file"
      })
    ];
    const merged0: MemoryGraphData = { nodes: [], links: [] };
    const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad(merged0, { [ns]: 1 }, rows, [ns], ns);
    const ids: string[] = snap.merged.nodes.map((n) => n.id);
    expect(ids).toContain("B:hl.py");
    expect(ids).toContain("B:other.py");
  });

  it("incrementalWithoutNewTraceRowsPreservesMergedHighlightNodes", async () => {
    const ns: string = "ns-hi-preserve";
    const rows: Record<string, unknown>[] = [
      rowW14GraphHighlight(ns, ["B:hl.py"]),
      rowPagNodeUpsert(ns, 1, {
        node_id: "B:a.py",
        level: "B",
        path: "a.py",
        title: "a",
        kind: "file"
      })
    ];
    const merged0: MemoryGraphData = { nodes: [], links: [] };
    const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad(merged0, { [ns]: 1 }, rows, [ns], ns);
    expect(snap.merged.nodes.map((n) => n.id)).toContain("B:hl.py");
    expect(snap.lastAppliedTraceIndex).toBe(1);
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(snap, rows, [ns], ns);
    expect(nxt).toBe(snap);
    expect(nxt.merged.nodes.map((n) => n.id)).toContain("B:hl.py");
  });

  it("incrementalWithoutNewTraceRowsReturnsCurWithoutRecompute", () => {
    const ns: string = "ns-noinc";
    const rows: Record<string, unknown>[] = [
      rowPagNodeUpsert(ns, 1, {
        node_id: "B:a.py",
        level: "B",
        path: "a.py",
        title: "a",
        kind: "file"
      }),
      rowPagNodeUpsert(ns, 2, {
        node_id: "B:b.py",
        level: "B",
        path: "b.py",
        title: "b",
        kind: "file"
      }),
      rowPagNodeUpsert(ns, 3, {
        node_id: "B:c.py",
        level: "B",
        path: "c.py",
        title: "c",
        kind: "file"
      })
    ];
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { [ns]: 0 },
      lastAppliedTraceIndex: 2
    };
    const nxt: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(base, rows, [ns], ns);
    expect(nxt).toBe(base);
  });

  it("uc03RefreshClearsStickyRevMismatchInSnapshotModel", async () => {
    const ns: string = "ns-uc03-sticky";
    const badRow: Record<string, unknown> = rowPagNodeUpsert(ns, 9, {
      node_id: "B:x.py",
      level: "B",
      path: "x.py",
      title: "x",
      kind: "file"
    });
    const base: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { [ns]: 1 },
      lastAppliedTraceIndex: -1
    };
    const withWarn: ReturnType<typeof PagGraphSessionTraceMerge.applyIncremental> =
      PagGraphSessionTraceMerge.applyIncremental(base, [badRow], [ns], ns);
    expect(
      withWarn.warnings.some((s: string) => s.includes("graph rev") || s.includes("несоответств"))
    ).toBe(true);
    const mergedDb: MemoryGraphData = {
      nodes: [
        nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: ns })!,
        nodeFromPag({
          node_id: "B:x.py",
          level: "B",
          path: "x.py",
          title: "x",
          namespace: ns
        })!
      ],
      links: []
    };
    const refreshed: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
      await PagGraphSessionTraceMerge.afterFullLoad(mergedDb, { [ns]: 8 }, [badRow], [ns], ns, true);
    expect(
      refreshed.warnings.some((s: string) => s.includes("graph rev") || s.includes("несоответств"))
    ).toBe(false);
  });

  it("h1RepeatedReplayAfterFullLoadDoesNotAccumulateRevMismatchWarnings", async () => {
    const ns: string = "ns-h1-replay";
    const rows: Record<string, unknown>[] = [
      rowPagNodeUpsert(ns, 1, {
        node_id: "B:a.py",
        level: "B",
        path: "a.py",
        title: "a",
        kind: "file"
      }),
      rowPagNodeUpsert(ns, 2, {
        node_id: "B:b.py",
        level: "B",
        path: "b.py",
        title: "b",
        kind: "file"
      })
    ];
    const merged: MemoryGraphData = {
      nodes: [nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: ns })!],
      links: []
    };
    for (let cycle: number = 0; cycle < 4; cycle += 1) {
      const snap: Awaited<ReturnType<typeof PagGraphSessionTraceMerge.afterFullLoad>> =
        await PagGraphSessionTraceMerge.afterFullLoad(merged, { [ns]: 2 }, rows, [ns], ns, true);
      const nRev: number = snap.warnings.filter(
        (s: string) => tryParsePagGraphRevMismatchDedupeKey(s) !== null
      ).length;
      expect(nRev).toBe(0);
    }
  });

  it("h2TwentyAlignedIncrementsYieldAtMostOneRevMismatchWarning", () => {
    const ns: string = "ns-h2-align";
    let snap: ReturnType<typeof createEmptyPagGraphSessionSnapshot> = {
      ...createEmptyPagGraphSessionSnapshot({ loadState: "ready" }),
      merged: { nodes: [], links: [] },
      graphRevByNamespace: { [ns]: 0 },
      lastAppliedTraceIndex: -1
    };
    for (let i: number = 0; i < 20; i += 1) {
      const row: Record<string, unknown> = rowPagNodeUpsert(ns, i + 1, {
        node_id: `B:n${String(i)}.py`,
        level: "B",
        path: `n${String(i)}.py`,
        title: "f",
        kind: "file"
      });
      snap = PagGraphSessionTraceMerge.applyIncremental(snap, [row], [ns], ns);
    }
    const revMismatch: number = snap.warnings.filter(
      (s: string) => tryParsePagGraphRevMismatchDedupeKey(s) !== null
    ).length;
    expect(revMismatch).toBeLessThanOrEqual(1);
  });

  it("h2CollapsesMultipleDistinctRevMismatchWarningsPerNamespaceToLatest", () => {
    const ns: string = "ns-h2-collapse";
    const w1: string = formatPagGraphRevMismatchWarning(ns, 2, 5);
    const w2: string = formatPagGraphRevMismatchWarning(ns, 6, 9);
    const collapsed: readonly string[] = collapsePagGraphRevMismatchWarningsToLatestPerNamespace([w1, w2]);
    expect(collapsed).toHaveLength(1);
    expect(collapsed[0]).toBe(w2);
  });

  it("reconcileStaleRemovesRevMismatchWhenGraphRevAbsorbedTraceRev", () => {
    const ns: string = "ns-reconcile-stale";
    const w: string = formatPagGraphRevMismatchWarning(ns, 2, 5);
    const cleaned: readonly string[] = reconcileStalePagGraphRevMismatchWarnings(
      [w],
      { [ns]: 5 },
      new Set([ns])
    );
    expect(cleaned).toHaveLength(0);
  });

  it("compactPagGraphObservabilityPayloadsHaveRequiredKeysAndNoForbiddenFields", () => {
    const forbidden: readonly string[] = [
      "raw_prompt",
      "user_prompt",
      "prompt",
      "chain_of_thought",
      "cot",
      "api_key",
      "token",
      "secret"
    ];
    const rRec: Record<string, unknown> = buildPagGraphRevReconciledTraceRow({
      chatId: "chat-a",
      sessionId: "sess-a",
      namespace: "ns-x",
      graph_rev_before: 1,
      graph_rev_after: 2,
      reason_code: "post_trace"
    });
    const plRec: Readonly<Record<string, unknown>> | null = extractCompactPagEventPayload(rRec);
    expect(plRec).not.toBeNull();
    expect(plRec!["session_id"]).toBe("sess-a");
    expect(plRec!["namespace"]).toBe("ns-x");
    expect(plRec!["graph_rev_after"]).toBe(2);
    expect(plRec!["reason_code"]).toBe("post_trace");
    for (const k of Object.keys(plRec!)) {
      expect(forbidden.includes(k.toLowerCase())).toBe(false);
    }
    const rSnap: Record<string, unknown> = buildPagSnapshotRefreshedTraceRow({
      chatId: "chat-a",
      sessionId: "sess-a",
      namespaces: ["n1", "n2"],
      graphRevByNamespace: { n1: 3, n2: 7 },
      reason_code: "post_refresh"
    });
    const plSnap: Readonly<Record<string, unknown>> | null = extractCompactPagEventPayload(rSnap);
    expect(plSnap).not.toBeNull();
    expect(plSnap!["session_id"]).toBe("sess-a");
    expect(plSnap!["namespaces"]).toEqual(["n1", "n2"]);
    expect(plSnap!["graph_rev_after"]).toBe(7);
    expect(plSnap!["reason_code"]).toBe("post_refresh");
    for (const k of Object.keys(plSnap!)) {
      expect(forbidden.includes(k.toLowerCase())).toBe(false);
    }
    const sRec: string = JSON.stringify(rRec);
    const sSnap: string = JSON.stringify(rSnap);
    expect(sRec.includes("pag_graph_rev_reconciled")).toBe(true);
    expect(sSnap.includes("pag_snapshot_refreshed")).toBe(true);
  });

  describe("TC-G4-replay observability and bounded path", () => {
    function mergeHooksWithDebug(
      emitDesktopGraphDebug: (event: string, detail: Record<string, unknown>) => void
    ): PagGraphTraceMergeEmitHooks {
      return {
        chatId: "chat-g4",
        sessionId: "sess-g4",
        graphRevBeforeByNamespace: {},
        defaultNamespace: "ns-g4",
        emitDesktopGraphDebug
      };
    }

    it("TC-G4-A1-lastRowNegative-emits-no-desktop-trace-replay", async () => {
      const dbg = vi.fn();
      const hooks: PagGraphTraceMergeEmitHooks = mergeHooksWithDebug(dbg);
      await PagGraphSessionTraceMerge.afterFullLoad(
        { nodes: [], links: [] },
        {},
        [],
        ["ns-g4"],
        "ns-g4",
        true,
        hooks
      );
      const replayEv: unknown[] = dbg.mock.calls
        .map((c: unknown[]) => c[0])
        .filter(
          (ev: unknown) => ev === DESKTOP_TRACE_REPLAY_START_EVENT || ev === DESKTOP_TRACE_REPLAY_END_EVENT
        );
      expect(replayEv).toHaveLength(0);
    });

    it("TC-G4-non-empty-replay-single-start-end-when-debug-enabled", async () => {
      const dbg = vi.fn();
      const hooks: PagGraphTraceMergeEmitHooks = mergeHooksWithDebug(dbg);
      const ns: string = "ns-g4-one";
      const rows: Record<string, unknown>[] = [
        rowPagNodeUpsert(ns, 1, {
          node_id: "B:g4.py",
          level: "B",
          path: "g4.py",
          title: "t",
          kind: "file"
        })
      ];
      await PagGraphSessionTraceMerge.afterFullLoad(
        {
          nodes: [nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: ns })!],
          links: []
        },
        { [ns]: 1 },
        rows,
        [ns],
        ns,
        true,
        hooks
      );
      const events: string[] = dbg.mock.calls.map((c: unknown[]) => String(c[0]));
      expect(events.filter((e: string) => e === DESKTOP_TRACE_REPLAY_START_EVENT)).toHaveLength(1);
      expect(events.filter((e: string) => e === DESKTOP_TRACE_REPLAY_END_EVENT)).toHaveLength(1);
      const startCall: unknown[] | undefined = dbg.mock.calls.find(
        (c: unknown[]) => c[0] === DESKTOP_TRACE_REPLAY_START_EVENT
      );
      expect(startCall).toBeDefined();
      const startArg: Record<string, unknown> = startCall![1] as Record<string, unknown>;
      expect(startArg).toHaveProperty("row_count");
      expect(startArg).toHaveProperty("duration_ms");
      expect(startArg).toHaveProperty("rows_processed");
      expect(startArg["duration_ms"]).toBeNull();
      expect(startArg["rows_processed"]).toBeNull();
      expect(startArg["row_count"]).toBe(1);
      for (const c of dbg.mock.calls) {
        if (c[0] !== DESKTOP_TRACE_REPLAY_START_EVENT && c[0] !== DESKTOP_TRACE_REPLAY_END_EVENT) {
          continue;
        }
        const detail: Record<string, unknown> = c[1] as Record<string, unknown>;
        expect(Object.keys(detail).sort()).toEqual(["duration_ms", "row_count", "rows_processed"]);
        expect(JSON.stringify(detail)).not.toContain("topic.publish");
      }
    });

    it("TC-G4-REPLAY-ChunkedSnapshotMatchesSinglePass", async () => {
      const ns: string = "ns-g4-chunk";
      const merged0: MemoryGraphData = {
        nodes: [nodeFromPag({ node_id: "A:1", level: "A", path: ".", title: "p", namespace: ns })!],
        links: []
      };
      const revs0: Record<string, number> = { [ns]: 0 };
      const rows: Record<string, unknown>[] = [];
      for (let r: number = 1; r <= 1200; r += 1) {
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
      const lastRow: number = rows.length - 1;
      const nsSet: Set<string> = new Set([ns]);
      const refAp: ReturnType<typeof applyDeltasInRange> = applyDeltasInRange(
        merged0,
        revs0,
        rows,
        0,
        lastRow,
        nsSet,
        [],
        true,
        undefined
      );
      const refHi: ReturnType<typeof PagGraphSessionTraceMerge.applyHighlightFromTraceRows> =
        PagGraphSessionTraceMerge.applyHighlightFromTraceRows(
          refAp.merged,
          rows,
          [ns],
          ns,
          -1,
          undefined
        );
      const refSnap: PagGraphSessionSnapshot = buildSnapshotFromReconcile(
        refHi.merged,
        refAp.revs,
        lastRow,
        refAp.warnings,
        "ready",
        null,
        true,
        refHi.highlights
      );
      const chunked: PagGraphSessionSnapshot = await PagGraphSessionTraceMerge.afterFullLoad(
        merged0,
        revs0,
        rows,
        [ns],
        ns,
        true,
        undefined,
        undefined,
        undefined
      );
      expect(chunked).toEqual(refSnap);
    });
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
