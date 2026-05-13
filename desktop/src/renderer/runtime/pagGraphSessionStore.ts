import type { ProjectRegistryEntry } from "@shared/ipc";

import { loadPagGraphMerged, type PagGraphSliceFn } from "./loadPagGraphMerged";
import { MEM3D_PAG_MAX_NODES } from "./pagGraphLimits";
import {
  lastPagSearchHighlightFromTrace,
  lastPagSearchHighlightFromTraceAfterMerge,
  type PagSearchHighlightV1
} from "./pagHighlightFromTrace";
import { pagSearchHighlightShallowEqualForGlow } from "./pagSearchHighlightShallowEqual";
import {
  ensureHighlightNodes,
  linkFromPag,
  mergeMemoryGraph,
  nodeFromPag,
  type MemoryGraphData,
  type MemoryGraphLink,
  type MemoryGraphNode
} from "./memoryGraphState";
import {
  buildDesktopTraceReplayEndDetail,
  buildDesktopTraceReplayStartDetail,
  buildPagGraphRevReconciledTraceRow,
  buildPagSnapshotRefreshedTraceRow,
  DESKTOP_TRACE_REPLAY_END_EVENT,
  DESKTOP_TRACE_REPLAY_START_EVENT,
  type PagGraphRevReconciledReasonCode,
  type PagSnapshotRefreshedReasonCode
} from "./pagGraphObservabilityCompact";
import {
  collapsePagGraphRevMismatchWarningsToLatestPerNamespace,
  dedupePagGraphSnapshotWarnings,
  reconcileStalePagGraphRevMismatchWarnings
} from "./pagGraphRevWarningFormat";
import {
  applyPagGraphTraceDelta,
  parsePagGraphTraceDelta,
  type PagGraphTraceDelta
} from "./pagGraphTraceDeltas";
import {
  mapPagSearchHighlightReasonToDiagnosticSource,
  PAG_MODE_TRACE_ONLY_ACCUMULATION
} from "./desktopSessionDiagnosticLog";

function str(x: unknown): string {
  return typeof x === "string" ? x : x == null ? "" : String(x);
}

/**
 * Снимок PAG-графа для **одного** `sessionId` (D13.4); единый source of truth для 2D/3D.
 */
export type PagGraphSessionSnapshot = {
  readonly merged: MemoryGraphData;
  readonly graphRevByNamespace: Readonly<Record<string, number>>;
  /**
   * Индекс последнего сырого trace-row, эффекты дельт которого учтены
   * в `merged` / rev (инкременты после init и full load).
   */
  readonly lastAppliedTraceIndex: number;
  /** Rev mismatch, large graph, и т.д. (не пусто → banner). */
  readonly warnings: readonly string[];
  /** > {@link MEM3D_PAG_MAX_NODES} нод в merged: предупредить, не усечь молча. */
  readonly atLargeGraphWarning: boolean;
  /**
   * `false` — на последнем успешном full load для всех запрошенных namespace был только
   * `missing_db` и срез из БД пуст; `true` — sqlite/срез доступен хотя бы по одному namespace.
   */
  readonly pagDatabasePresent: boolean;
  readonly loadState: "idle" | "loading" | "ready" | "error";
  readonly loadError: string | null;
  /**
   * Последняя подсветка по workspace namespace после merge (C-HL-1); UI 3D/2D не парсит trace повторно.
   */
  readonly searchHighlightsByNamespace: Readonly<Record<string, PagSearchHighlightV1 | null>>;
};

/** Опциональные хуки compact observability (D-PROD-1); без IPC в unit-тестах store. */
export type PagGraphTraceMergeEmitHooks = {
  readonly chatId: string;
  readonly sessionId: string;
  readonly graphRevBeforeByNamespace: Readonly<Record<string, number>>;
  readonly defaultNamespace: string;
  readonly emitTraceRow?: (row: Record<string, unknown>) => void;
  /** Идемпотентность §9: последний emit `graph_rev_after` per `sessionId+namespace`. */
  readonly reconciledEmitRevByNs?: Map<string, number>;
  readonly fullLoad?: {
    readonly kind: "user_refresh" | "poll_retry" | "initial_load";
    readonly namespaces: readonly string[];
  };
  /** Служебные source=D записи в `ailit-desktop-*.log` (без IPC в unit-тестах). */
  readonly emitDesktopGraphDebug?: (event: string, detail: Record<string, unknown>) => void;
  /** Дедуп D-PAGMODE-1: ключ `sessionId\\u001fnamespace`. */
  readonly traceOnlyPagModeSentKeys?: Set<string>;
};

export function createEmptyPagGraphSessionSnapshot(
  init: { readonly loadState: PagGraphSessionSnapshot["loadState"] } = { loadState: "idle" }
): PagGraphSessionSnapshot {
  return {
    merged: { nodes: [], links: [] },
    graphRevByNamespace: {},
    lastAppliedTraceIndex: -1,
    warnings: [],
    atLargeGraphWarning: false,
    pagDatabasePresent: true,
    loadState: init.loadState,
    loadError: null,
    searchHighlightsByNamespace: {}
  };
}

/** Список namespace, как в MemoryGraph3D: выбранные проекты или весь registry. */
export class PagGraphWorkspaceNamespaces {
  static list(
    registry: readonly ProjectRegistryEntry[],
    selectedProjectIds: readonly string[]
  ): readonly string[] {
    const ids: readonly string[] =
      selectedProjectIds.length > 0
        ? selectedProjectIds
        : registry.map((proj) => proj.projectId);
    const out: string[] = [];
    for (const id of ids) {
      const ns: string = registry.find((p) => p.projectId === id)?.namespace ?? "";
      if (ns && !out.includes(ns)) {
        out.push(ns);
      }
    }
    return out;
  }

  static defaultNamespace(
    registry: readonly ProjectRegistryEntry[],
    selectedProjectIds: readonly string[]
  ): string {
    if (selectedProjectIds.length > 0) {
      const f: ProjectRegistryEntry | undefined = registry.find(
        (p) => p.projectId === selectedProjectIds[0]
      );
      return f?.namespace ?? "default";
    }
    return registry[0]?.namespace ?? "default";
  }
}

/**
 * `code: missing_db` в JSON pag-slice; без кода (старый ailit/IPC) — тот же смысл по тексту memory_cli.
 */
function isPagSqliteFileMissingError(message: string, errorCode: string | undefined): boolean {
  if (errorCode === "missing_db") {
    return true;
  }
  const m: string = message.toLowerCase();
  if (m.includes("sqlite not found")) {
    return true;
  }
  if (m.includes("no such file") && m.includes("sqlite")) {
    return true;
  }
  return false;
}

export class PagGraphSessionFullLoad {
  static async run(
    slice: PagGraphSliceFn,
    namespaces: readonly string[]
  ): Promise<
    | {
        readonly ok: true;
        readonly merged: MemoryGraphData;
        readonly graphRevByNamespace: Record<string, number>;
        /** Все `namespace` вернули `missing_db`; граф до появления файла строим из trace. */
        readonly pagSqliteMissing?: true;
      }
    | { readonly ok: false; readonly error: string }
  > {
    if (namespaces.length === 0) {
      return { ok: true, merged: { nodes: [], links: [] }, graphRevByNamespace: {} };
    }
    const errors: string[] = [];
    const failMeta: { readonly code: string | undefined; readonly message: string }[] = [];
    let merged: MemoryGraphData = { nodes: [], links: [] };
    const revs: Record<string, number> = {};
    for (const namespace of namespaces) {
      const r: Awaited<ReturnType<typeof loadPagGraphMerged>> = await loadPagGraphMerged(
        (p) => slice(p) as never,
        { namespace, level: null }
      );
      if (!r.ok) {
        failMeta.push({ code: r.errorCode, message: r.error });
        errors.push(`${namespace}: ${r.error}`);
        continue;
      }
      revs[namespace] = r.graphRev;
      const nNodes: MemoryGraphNode[] = r.nodes
        .map((n) => {
          const raw: Record<string, unknown> = n as Record<string, unknown>;
          return nodeFromPag(
            (raw["namespace"] != null && str(raw["namespace"]) !== ""
              ? raw
              : { ...raw, namespace }
            ) as Record<string, unknown>
          );
        })
        .filter((n): n is MemoryGraphNode => n !== null);
      const nLinks: MemoryGraphLink[] = r.edges
        .map((e) => linkFromPag(e as Record<string, unknown>))
        .filter((l): l is MemoryGraphLink => l !== null);
      const nodesPart: MemoryGraphData = { nodes: nNodes, links: [] };
      const linksPart: MemoryGraphData = { nodes: [], links: nLinks };
      merged = mergeMemoryGraph(mergeMemoryGraph(merged, nodesPart), linksPart);
    }
    if (errors.length > 0 && merged.nodes.length === 0 && merged.links.length === 0) {
      const allMissing: boolean =
        failMeta.length === namespaces.length &&
        failMeta.every((f) => isPagSqliteFileMissingError(f.message, f.code));
      if (allMissing) {
        return {
          ok: true,
          merged: { nodes: [], links: [] },
          graphRevByNamespace: {},
          pagSqliteMissing: true
        };
      }
      return { ok: false, error: errors.join("; ") };
    }
    if (errors.length > 0) {
      // частично загружено — с предупреждением в loadError не перегружаем, см. warn в snapshot
    }
    return { ok: true, merged, graphRevByNamespace: revs };
  }
}

type RevRec = Record<string, number>;

function withLargeWarning(merged: MemoryGraphData, warnings: readonly string[]): {
  readonly atLargeGraphWarning: boolean;
  readonly warnings: readonly string[];
} {
  const atLarge: boolean = merged.nodes.length > MEM3D_PAG_MAX_NODES;
  if (!atLarge) {
    return { atLargeGraphWarning: false, warnings };
  }
  const w: string =
    `PAG: в merged ${merged.nodes.length} нод (>${String(MEM3D_PAG_MAX_NODES)}). ` +
    "Срез тяжёлый; используйте Refresh при необходимости.";
  if (warnings.includes(w)) {
    return { atLargeGraphWarning: true, warnings };
  }
  return { atLargeGraphWarning: true, warnings: [...warnings, w] };
}

/** Сборка snapshot после merge; экспорт для эталона TC-G4 vs chunked replay. */
export function buildSnapshotFromReconcile(
  merged: MemoryGraphData,
  revs: Readonly<RevRec>,
  lastIndex: number,
  warnings: readonly string[],
  loadState: PagGraphSessionSnapshot["loadState"],
  loadError: string | null,
  pagDatabasePresent: boolean,
  searchHighlightsByNamespace: Readonly<Record<string, PagSearchHighlightV1 | null>>
): PagGraphSessionSnapshot {
  const w2: { readonly atLargeGraphWarning: boolean; readonly warnings: readonly string[] } = withLargeWarning(
    merged,
    warnings
  );
  return {
    merged,
    graphRevByNamespace: { ...revs },
    lastAppliedTraceIndex: lastIndex,
    warnings: w2.warnings,
    atLargeGraphWarning: w2.atLargeGraphWarning,
    pagDatabasePresent,
    loadState,
    loadError,
    searchHighlightsByNamespace: { ...searchHighlightsByNamespace }
  };
}

function shouldApplyTraceDelta(
  d: PagGraphTraceDelta,
  namespaces: Readonly<Set<string>>
): boolean {
  return namespaces.has(d.namespace);
}

/**
 * Для **первой** PAG-дельты по namespace в [from, to] (с учётом фильтра) — `rev` первой дельты.
 */
function firstPagDeltaRevInRangeByNamespace(
  rows: readonly Record<string, unknown>[],
  from: number,
  toInclusive: number,
  namespaces: Readonly<Set<string>>
): Readonly<Record<string, number>> {
  const firstRevByNamespace: RevRec = {};
  for (let i: number = from; i <= toInclusive; i += 1) {
    const row: Record<string, unknown> = rows[i]! as Record<string, unknown>;
    const d: ReturnType<typeof parsePagGraphTraceDelta> = parsePagGraphTraceDelta(row);
    if (d === null) {
      continue;
    }
    if (!shouldApplyTraceDelta(d, namespaces)) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(firstRevByNamespace, d.namespace)) {
      continue;
    }
    firstRevByNamespace[d.namespace] = d.rev;
  }
  return firstRevByNamespace;
}

/**
 * «Catch-up» после `pag-slice` + полная история trace, начиная с `rev:1`: `graph_rev` из БД (116) и
 * дельта 1 вместе давали ожидание 117, не 1 (см. applyPagGraphTraceDelta). Если **первая** дельта
 * **не** с 1, следы strict от среза: пропуск (rev 3 при 1) — предупреждение.
 */
function buildRevsInForDeltas(
  revsFromSlice: RevRec,
  rows: readonly Record<string, unknown>[],
  from: number,
  toInclusive: number,
  namespaces: Readonly<Set<string>>,
  useInitialTraceCatchup: boolean
): RevRec {
  const out: RevRec = { ...revsFromSlice };
  if (!useInitialTraceCatchup) {
    return out;
  }
  const firstRevs: Readonly<Record<string, number>> = firstPagDeltaRevInRangeByNamespace(
    rows,
    from,
    toInclusive,
    namespaces
  );
  for (const [ns, firstRev] of Object.entries(firstRevs)) {
    const sliceRev: number = revsFromSlice[ns] ?? 0;
    if (firstRev === 1 && sliceRev > 0) {
      out[ns] = 0;
    }
  }
  return out;
}

function emitTraceOnlyPagModeDiagnostics(
  pagDatabasePresent: boolean,
  namespaces: readonly string[],
  hooks: PagGraphTraceMergeEmitHooks | undefined
): void {
  if (pagDatabasePresent || hooks == null) {
    return;
  }
  const emit: ((event: string, detail: Record<string, unknown>) => void) | undefined = hooks.emitDesktopGraphDebug;
  const sent: Set<string> | undefined = hooks.traceOnlyPagModeSentKeys;
  if (emit === undefined || sent === undefined) {
    return;
  }
  const ts: string = new Date().toISOString();
  for (const ns of namespaces) {
    if (ns.length === 0) {
      continue;
    }
    const key: string = `${hooks.sessionId}\u001f${ns}`;
    if (sent.has(key)) {
      continue;
    }
    sent.add(key);
    emit("pag_mode_trace_only_accumulation", {
      ts_utc: ts,
      namespace: ns,
      session_ui: hooks.sessionId,
      pag_mode: PAG_MODE_TRACE_ONLY_ACCUMULATION
    });
  }
}

function emitHighlightChangeDiagnostics(
  prev: Readonly<Record<string, PagSearchHighlightV1 | null>>,
  next: Readonly<Record<string, PagSearchHighlightV1 | null>>,
  emit?: (event: string, detail: Record<string, unknown>) => void
): void {
  if (emit === undefined) {
    return;
  }
  const keys: Set<string> = new Set([...Object.keys(prev), ...Object.keys(next)]);
  const ts: string = new Date().toISOString();
  for (const ns of keys) {
    const a: PagSearchHighlightV1 | null = prev[ns] ?? null;
    const b: PagSearchHighlightV1 | null = next[ns] ?? null;
    if (b === null) {
      continue;
    }
    if (pagSearchHighlightShallowEqualForGlow(a, b)) {
      continue;
    }
    const highlightSource: string = mapPagSearchHighlightReasonToDiagnosticSource(b.reason);
    emit("highlight_recomputed", {
      ts_utc: ts,
      namespace: ns,
      highlight_source: highlightSource,
      reason_raw: b.reason,
      node_count: b.nodeIds.length,
      edge_count: b.edgeIds.length,
      ttl_ms: b.ttlMs,
      query_id: b.queryId ?? null,
      node_ids: b.nodeIds,
      edge_ids: b.edgeIds
    });
  }
}

/** D1: bounded replay chunking; экспорт для TC-G4-REPLAY vs single-pass. */
export const PAG_GRAPH_REPLAY_CHUNK_MAX_ROWS: number = 500;

/** D1: максимум ~4 ms wall на расширение одного чанка (до одного вызова applyDeltasInRange). */
export const PAG_GRAPH_REPLAY_CHUNK_MAX_MS: number = 4;

function replayWallNowMs(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

function yieldReplayChunkBound(): Promise<void> {
  return new Promise<void>((resolve) => {
    queueMicrotask(() => {
      resolve();
    });
  });
}

/** Опции одного вызова `applyDeltasInRange` в chunked replay (C4 / catch-up). */
export type ApplyPagGraphDeltasChunkOptions = {
  /**
   * Стартовые rev для применения дельт; если задано, `buildRevsInForDeltas` не вызывается
   * (нужно для первого окна replay: catch-up по первой дельте в [0, lastRow], а не только в чанке).
   */
  readonly initialRevsInOverride?: RevRec;
  /**
   * Пропустить `reconcileStalePagGraphRevMismatchWarnings` (продолжение одного логического
   * `applyDeltasInRange(0, lastRow)` после первого чанка).
   */
  readonly skipStalePagGraphRevReconcile?: boolean;
};

function clonePagGraphMergeForReplayRollback(merged: MemoryGraphData): MemoryGraphData {
  if (typeof structuredClone === "function") {
    return structuredClone(merged) as MemoryGraphData;
  }
  return JSON.parse(JSON.stringify(merged)) as MemoryGraphData;
}

export function applyDeltasInRange(
  mergedIn: MemoryGraphData,
  revsFromSlice: RevRec,
  rows: readonly Record<string, unknown>[],
  from: number,
  toInclusive: number,
  namespaces: Readonly<Set<string>>,
  prevWarnings: readonly string[],
  useInitialTraceCatchup: boolean,
  emitDesktopGraphDebug?: (event: string, detail: Record<string, unknown>) => void,
  chunkOptions?: ApplyPagGraphDeltasChunkOptions
): {
  readonly merged: MemoryGraphData;
  readonly revs: RevRec;
  readonly warnings: readonly string[];
  readonly namespacesDeltaTouched: ReadonlySet<string>;
} {
  const revsIn: RevRec =
    chunkOptions?.initialRevsInOverride != null
      ? { ...chunkOptions.initialRevsInOverride }
      : buildRevsInForDeltas(
          revsFromSlice,
          rows,
          from,
          toInclusive,
          namespaces,
          useInitialTraceCatchup
        );
  let merged: MemoryGraphData = mergedIn;
  const revs: RevRec = { ...revsIn };
  const baseWarnings: readonly string[] =
    chunkOptions?.skipStalePagGraphRevReconcile === true
      ? [...prevWarnings]
      : reconcileStalePagGraphRevMismatchWarnings(prevWarnings, revsFromSlice, namespaces);
  const wlist: string[] = [...baseWarnings];
  const namespacesDeltaTouched: Set<string> = new Set();
  for (let i: number = from; i <= toInclusive; i += 1) {
    const row: Record<string, unknown> = rows[i]! as Record<string, unknown>;
    const d: ReturnType<typeof parsePagGraphTraceDelta> = parsePagGraphTraceDelta(row);
    if (d === null) {
      continue;
    }
    if (!shouldApplyTraceDelta(d, namespaces)) {
      continue;
    }
    namespacesDeltaTouched.add(d.namespace);
    const o: RevRec = {};
    const { data, revWarning } = applyPagGraphTraceDelta(merged, d, revs, o);
    merged = data;
    for (const k of Object.keys(o)) {
      revs[k] = o[k]!;
    }
    if (revWarning !== null) {
      wlist.push(revWarning);
    }
    if (emitDesktopGraphDebug !== undefined) {
      const tsLine: string = new Date().toISOString();
      if (d.kind === "pag.node.upsert") {
        const sid: string = str(d.node["id"]) || "node";
        emitDesktopGraphDebug("merge_pag_delta", {
          ts_utc: tsLine,
          op: "node",
          namespace: d.namespace,
          rev: d.rev,
          subject: sid
        });
      } else {
        const ids: string[] = d.edges
          .map((e) => {
            const er: Record<string, unknown> = e as Record<string, unknown>;
            return str(er["edge_id"]) || str(er["id"]);
          })
          .filter((x) => x.length > 0);
        const subj: string =
          ids.length > 0 ? ids.slice(0, 4).join(",") : `edges=${String(d.edges.length)}`;
        emitDesktopGraphDebug("merge_pag_delta", {
          ts_utc: tsLine,
          op: "edge",
          namespace: d.namespace,
          rev: d.rev,
          subject: subj,
          edge_batch_count: d.edges.length
        });
      }
    }
  }
  const deduped: readonly string[] = dedupePagGraphSnapshotWarnings(wlist);
  const collapsed: readonly string[] = collapsePagGraphRevMismatchWarningsToLatestPerNamespace(deduped);
  return { merged, revs, warnings: collapsed, namespacesDeltaTouched };
}

type ReplayRollbackSnap = {
  readonly m: MemoryGraphData;
  readonly r: RevRec;
  readonly w: readonly string[];
};

/**
 * Bounded replay после full load: чанки по строкам + при превышении wall budget рекурсивное
 * деление окна (откат через snapshot). Семантика как у одного `applyDeltasInRange(0, lastRow)`.
 */
async function applyAfterFullLoadReplayDeltasBounded(
  merged0: MemoryGraphData,
  revs0: RevRec,
  rows: readonly Record<string, unknown>[],
  lastRow: number,
  namespaces: Readonly<Set<string>>,
  emitDesktopGraphDebug?: (event: string, detail: Record<string, unknown>) => void
): Promise<{
  readonly merged: MemoryGraphData;
  readonly revs: RevRec;
  readonly warnings: readonly string[];
  readonly namespacesDeltaTouched: ReadonlySet<string>;
}> {
  const revsInFullCatchUp: RevRec = buildRevsInForDeltas(revs0, rows, 0, lastRow, namespaces, true);
  let mergedAcc: MemoryGraphData = merged0;
  let revsAcc: RevRec = { ...revs0 };
  let warningsAcc: readonly string[] = [];
  const namespacesDeltaUnion: Set<string> = new Set();

  const takeReplaySnap = (): ReplayRollbackSnap => ({
    m: clonePagGraphMergeForReplayRollback(mergedAcc),
    r: { ...revsAcc },
    w: [...warningsAcc]
  });
  const restoreReplaySnap = (s: ReplayRollbackSnap): void => {
    mergedAcc = s.m;
    revsAcc = { ...s.r };
    warningsAcc = [...s.w];
  };

  const commitChunk = (ap: ReturnType<typeof applyDeltasInRange>): void => {
    mergedAcc = ap.merged;
    revsAcc = ap.revs;
    warningsAcc = ap.warnings;
    for (const nsT of ap.namespacesDeltaTouched) {
      namespacesDeltaUnion.add(nsT);
    }
  };

  async function replayWindow(cur: number, hi: number): Promise<void> {
    if (cur > hi) {
      return;
    }
    const windowStartsAtTraceOrigin: boolean = cur === 0;
    const skipStale: boolean = cur > 0;
    const snapBeforeTry: ReplayRollbackSnap = takeReplaySnap();
    const t0: number = replayWallNowMs();
    const apChunk: ReturnType<typeof applyDeltasInRange> = applyDeltasInRange(
      mergedAcc,
      revsAcc,
      rows,
      cur,
      hi,
      namespaces,
      warningsAcc,
      false,
      emitDesktopGraphDebug,
      {
        initialRevsInOverride: windowStartsAtTraceOrigin ? revsInFullCatchUp : undefined,
        skipStalePagGraphRevReconcile: skipStale
      }
    );
    const dt: number = replayWallNowMs() - t0;
    const span: number = hi - cur + 1;
    if (dt <= PAG_GRAPH_REPLAY_CHUNK_MAX_MS || cur >= hi) {
      commitChunk(apChunk);
      return;
    }
    restoreReplaySnap(snapBeforeTry);
    const mid: number = cur + Math.floor(span / 2) - 1;
    await yieldReplayChunkBound();
    await replayWindow(cur, mid);
    await yieldReplayChunkBound();
    await replayWindow(mid + 1, hi);
  }

  let outerCur: number = 0;
  while (outerCur <= lastRow) {
    const outerHi: number = Math.min(outerCur + PAG_GRAPH_REPLAY_CHUNK_MAX_ROWS - 1, lastRow);
    await replayWindow(outerCur, outerHi);
    outerCur = outerHi + 1;
    if (outerCur <= lastRow) {
      await yieldReplayChunkBound();
    }
  }

  return {
    merged: mergedAcc,
    revs: revsAcc,
    warnings: warningsAcc,
    namespacesDeltaTouched: namespacesDeltaUnion
  };
}

function emitKeyReconciled(sessionId: string, namespace: string): string {
  return `${sessionId}\u001f${namespace}`;
}

function shouldEmitPagGraphRevReconciled(
  map: Map<string, number> | undefined,
  sessionId: string,
  namespace: string,
  graphRevAfter: number
): boolean {
  if (!map) {
    return true;
  }
  const k: string = emitKeyReconciled(sessionId, namespace);
  if (map.get(k) === graphRevAfter) {
    return false;
  }
  map.set(k, graphRevAfter);
  return true;
}

function emitPagGraphObservability(params: {
  readonly hooks: PagGraphTraceMergeEmitHooks | undefined;
  readonly namespaces: readonly string[];
  readonly graphRevAfterByNs: Readonly<RevRec>;
  readonly namespacesDeltaTouched: ReadonlySet<string>;
  readonly isAfterFullLoad: boolean;
}): void {
  const h: PagGraphTraceMergeEmitHooks | undefined = params.hooks;
  if (h == null || typeof h.emitTraceRow !== "function") {
    return;
  }
  const before: Readonly<Record<string, number>> = h.graphRevBeforeByNamespace;
  if (params.isAfterFullLoad && h.fullLoad != null) {
    const nsList: readonly string[] = h.fullLoad.namespaces;
    if (nsList.length > 0) {
      let snapReason: PagSnapshotRefreshedReasonCode;
      if (h.fullLoad.kind === "user_refresh") {
        snapReason = "user_refresh";
      } else if (h.fullLoad.kind === "poll_retry") {
        snapReason = "poll_retry";
      } else {
        snapReason = "initial_load";
      }
      h.emitTraceRow(
        buildPagSnapshotRefreshedTraceRow({
          chatId: h.chatId,
          sessionId: h.sessionId,
          namespaces: nsList,
          graphRevByNamespace: params.graphRevAfterByNs,
          reason_code: snapReason
        })
      );
    }
  }
  for (const ns of params.namespaces) {
    const after: number | undefined = params.graphRevAfterByNs[ns];
    if (after === undefined) {
      continue;
    }
    if (!shouldEmitPagGraphRevReconciled(h.reconciledEmitRevByNs, h.sessionId, ns, after)) {
      continue;
    }
    const hasBefore: boolean = Object.prototype.hasOwnProperty.call(before, ns);
    const graphRevBefore: number | null = hasBefore ? before[ns]! : null;
    let reasonCode: PagGraphRevReconciledReasonCode;
    if (h.fullLoad?.kind === "user_refresh") {
      reasonCode = "user_refresh";
    } else if (h.fullLoad?.kind === "poll_retry") {
      reasonCode = "poll_retry";
    } else if (params.namespacesDeltaTouched.has(ns)) {
      reasonCode = "post_trace";
    } else if (params.isAfterFullLoad) {
      reasonCode = "post_slice";
    } else {
      reasonCode = "debounce_merge";
    }
    h.emitTraceRow(
      buildPagGraphRevReconciledTraceRow({
        chatId: h.chatId,
        sessionId: h.sessionId,
        namespace: ns,
        graph_rev_before: graphRevBefore,
        graph_rev_after: after,
        reason_code: reasonCode
      })
    );
  }
}

function resolveHighlightGatingChatId(
  highlightGatingChatId: string | undefined,
  hooks: PagGraphTraceMergeEmitHooks | undefined
): string | undefined {
  if (typeof highlightGatingChatId === "string" && highlightGatingChatId.length > 0) {
    return highlightGatingChatId;
  }
  const h: string | undefined = hooks?.chatId;
  return typeof h === "string" && h.length > 0 ? h : undefined;
}

export class PagGraphSessionTraceMerge {
  /**
   * D-HI-1: `PagSearchHighlightV1` из последней **применимой** trace-строки (ledger / W14 и т.д.
   * в `pagHighlightFromTrace`). При инкременте без новых строк highlight не пересчитывается
   * (см. `applyIncremental`, architecture §4.3).
   *
   * C-HL-1 / UC-03: при непустом `gatingChatId` подсветка на строке учитывается только внутри recall-окна и
   * после триггера A или B — см. `isUc03HighlightAllowedAtRowIndex` в `chatTraceAmPhase` (фазы AM,
   * `isMemoryQueryStart`) и `user_prompt` в `traceNormalize`.
   */
  static applyHighlightFromTraceRows(
    merged: MemoryGraphData,
    rows: readonly Record<string, unknown>[],
    namespaces: readonly string[],
    defaultNamespace: string,
    lastConsumedTraceIndex: number = -1,
    gatingChatId?: string
  ): { readonly merged: MemoryGraphData; readonly highlights: Readonly<Record<string, PagSearchHighlightV1 | null>> } {
    const nsList: readonly string[] = namespaces.length > 0 ? namespaces : [defaultNamespace];
    const highlights: Record<string, PagSearchHighlightV1 | null> = {};
    for (const ns of nsList) {
      highlights[ns] = null;
    }
    if (rows.length === 0) {
      return { merged, highlights };
    }
    let out: MemoryGraphData = merged;
    for (const ns of nsList) {
      const previous: ReturnType<typeof lastPagSearchHighlightFromTrace> | null =
        lastConsumedTraceIndex < 0
          ? null
          : lastPagSearchHighlightFromTrace(
              rows.slice(0, lastConsumedTraceIndex + 1),
              ns,
              gatingChatId
            );
      const ev: ReturnType<typeof lastPagSearchHighlightFromTrace> = lastPagSearchHighlightFromTraceAfterMerge(
        rows,
        ns,
        previous,
        lastConsumedTraceIndex,
        gatingChatId
      );
      highlights[ns] = ev;
      if (ev !== null) {
        /** G1: `merged` остаётся суперсетом (в т.ч. highlight-only узлы для 2D); **N_scene** для 3D — только `project`. */
        out = ensureHighlightNodes(out, ev.nodeIds, ev.namespace);
      }
    }
    return { merged: out, highlights };
  }

  /**
   * Сразу после `loadFull`: реплей существующих trace-rows на merged из БД (идемпотентно по merge),
   * затем highlight с последней применимой строки trace. Rev catch-up: см. `buildRevsInForDeltas` + `useInitialTraceCatchup`.
   *
   * При `rows.length > 0` реплей идёт чанками (**D1**) с `queueMicrotask` между чанками; семантика совпадает с одним
   * вызовом `applyDeltasInRange(..., 0, lastRow, ...)` (см. тест `TC-G4-REPLAY-ChunkedSnapshotMatchesSinglePass`).
   */
  static async afterFullLoad(
    merged0: MemoryGraphData,
    revs0: RevRec,
    rows: readonly Record<string, unknown>[],
    namespaces: readonly string[],
    defaultNamespace: string,
    pagDatabasePresent: boolean = true,
    hooks?: PagGraphTraceMergeEmitHooks,
    highlightGatingChatId?: string,
    prevSearchHighlights?: Readonly<Record<string, PagSearchHighlightV1 | null>>
  ): Promise<PagGraphSessionSnapshot> {
    const gate: string | undefined = resolveHighlightGatingChatId(highlightGatingChatId, hooks);
    const ns: Set<string> = new Set(namespaces);
    const lastRow: number = rows.length - 1;
    const prevHi: Readonly<Record<string, PagSearchHighlightV1 | null>> = prevSearchHighlights ?? {};
    const diagEmit: ((event: string, detail: Record<string, unknown>) => void) | undefined = hooks?.emitDesktopGraphDebug;
    if (lastRow < 0) {
      const hi: {
        readonly merged: MemoryGraphData;
        readonly highlights: Readonly<Record<string, PagSearchHighlightV1 | null>>;
      } = this.applyHighlightFromTraceRows(merged0, rows, namespaces, defaultNamespace, -1, gate);
      const snap0: PagGraphSessionSnapshot = buildSnapshotFromReconcile(
        hi.merged,
        revs0,
        -1,
        [],
        "ready",
        null,
        pagDatabasePresent,
        hi.highlights
      );
      emitHighlightChangeDiagnostics(prevHi, hi.highlights, diagEmit);
      emitTraceOnlyPagModeDiagnostics(pagDatabasePresent, namespaces, hooks);
      emitPagGraphObservability({
        hooks,
        namespaces,
        graphRevAfterByNs: revs0,
        namespacesDeltaTouched: new Set(),
        isAfterFullLoad: true
      });
      if (hooks?.emitDesktopGraphDebug !== undefined) {
        hooks.emitDesktopGraphDebug("merge_after_full_load", {
          last_applied_trace_index: snap0.lastAppliedTraceIndex,
          merged_node_count: snap0.merged.nodes.length,
          merged_link_count: snap0.merged.links.length,
          graph_rev_by_namespace: snap0.graphRevByNamespace,
          warnings_count: snap0.warnings.length,
          pag_database_present: snap0.pagDatabasePresent
        });
      }
      return snap0;
    }
    const replayDebug: ((event: string, detail: Record<string, unknown>) => void) | undefined = diagEmit;
    const replayT0: number = replayWallNowMs();
    if (replayDebug !== undefined) {
      replayDebug(
        DESKTOP_TRACE_REPLAY_START_EVENT,
        buildDesktopTraceReplayStartDetail({
          row_count: rows.length,
          duration_ms: null,
          rows_processed: null
        })
      );
    }
    const apAll: {
      readonly merged: MemoryGraphData;
      readonly revs: RevRec;
      readonly warnings: readonly string[];
      readonly namespacesDeltaTouched: ReadonlySet<string>;
    } = await applyAfterFullLoadReplayDeltasBounded(merged0, revs0, rows, lastRow, ns, diagEmit);
    const hi2: {
      readonly merged: MemoryGraphData;
      readonly highlights: Readonly<Record<string, PagSearchHighlightV1 | null>>;
    } = this.applyHighlightFromTraceRows(apAll.merged, rows, namespaces, defaultNamespace, -1, gate);
    const snap: PagGraphSessionSnapshot = buildSnapshotFromReconcile(
      hi2.merged,
      apAll.revs,
      lastRow,
      apAll.warnings,
      "ready",
      null,
      pagDatabasePresent,
      hi2.highlights
    );
    emitHighlightChangeDiagnostics(prevHi, hi2.highlights, diagEmit);
    emitTraceOnlyPagModeDiagnostics(pagDatabasePresent, namespaces, hooks);
    emitPagGraphObservability({
      hooks,
      namespaces,
      graphRevAfterByNs: apAll.revs,
      namespacesDeltaTouched: apAll.namespacesDeltaTouched,
      isAfterFullLoad: true
    });
    if (replayDebug !== undefined) {
      const wallDelta: number = replayWallNowMs() - replayT0;
      replayDebug(
        DESKTOP_TRACE_REPLAY_END_EVENT,
        buildDesktopTraceReplayEndDetail({
          row_count: rows.length,
          duration_ms: Number.isFinite(wallDelta) ? Math.round(wallDelta) : null,
          rows_processed: lastRow + 1
        })
      );
    }
    if (hooks?.emitDesktopGraphDebug !== undefined) {
      hooks.emitDesktopGraphDebug("merge_after_full_load", {
        last_applied_trace_index: snap.lastAppliedTraceIndex,
        merged_node_count: snap.merged.nodes.length,
        merged_link_count: snap.merged.links.length,
        graph_rev_by_namespace: snap.graphRevByNamespace,
        warnings_count: snap.warnings.length,
        pag_database_present: snap.pagDatabasePresent
      });
    }
    return snap;
  }

  /**
   * Инкремент: строго строки (last+1)..(len-1) — без N× pagGraphSlice.
   */
  static applyIncremental(
    cur: PagGraphSessionSnapshot,
    rows: readonly Record<string, unknown>[],
    namespaces: readonly string[],
    defaultNamespace: string,
    hooks?: PagGraphTraceMergeEmitHooks,
    highlightGatingChatId?: string
  ): PagGraphSessionSnapshot {
    const gate: string | undefined = resolveHighlightGatingChatId(highlightGatingChatId, hooks);
    const start: number = cur.lastAppliedTraceIndex + 1;
    if (rows.length === 0) {
      return cur;
    }
    const end: number = rows.length - 1;
    const ns: Set<string> = new Set(namespaces);
    if (start > end) {
      // Нет новых trace-строк: дельты уже в merged; повтор highlight не делаем (стабильность).
      return cur;
    }
    const useInitialTraceCatchup: boolean = cur.lastAppliedTraceIndex === -1 && start === 0;
    const diagInc: ((event: string, detail: Record<string, unknown>) => void) | undefined = hooks?.emitDesktopGraphDebug;
    const ap: {
      readonly merged: MemoryGraphData;
      readonly revs: RevRec;
      readonly warnings: readonly string[];
      readonly namespacesDeltaTouched: ReadonlySet<string>;
    } = applyDeltasInRange(
      cur.merged,
      { ...cur.graphRevByNamespace } as RevRec,
      rows,
      start,
      end,
      ns,
      cur.warnings,
      useInitialTraceCatchup,
      diagInc
    );
    const hi3: {
      readonly merged: MemoryGraphData;
      readonly highlights: Readonly<Record<string, PagSearchHighlightV1 | null>>;
    } = this.applyHighlightFromTraceRows(
      ap.merged,
      rows,
      namespaces,
      defaultNamespace,
      cur.lastAppliedTraceIndex,
      gate
    );
    const nxt: PagGraphSessionSnapshot = buildSnapshotFromReconcile(
      hi3.merged,
      ap.revs,
      end,
      ap.warnings,
      "ready",
      null,
      cur.pagDatabasePresent,
      hi3.highlights
    );
    emitHighlightChangeDiagnostics(cur.searchHighlightsByNamespace, hi3.highlights, diagInc);
    emitTraceOnlyPagModeDiagnostics(cur.pagDatabasePresent, namespaces, hooks);
    emitPagGraphObservability({
      hooks,
      namespaces,
      graphRevAfterByNs: ap.revs,
      namespacesDeltaTouched: ap.namespacesDeltaTouched,
      isAfterFullLoad: false
    });
    if (hooks?.emitDesktopGraphDebug !== undefined && nxt !== cur) {
      hooks.emitDesktopGraphDebug("merge_after_incremental", {
        last_applied_trace_index: nxt.lastAppliedTraceIndex,
        merged_node_count: nxt.merged.nodes.length,
        merged_link_count: nxt.merged.links.length,
        graph_rev_by_namespace: nxt.graphRevByNamespace,
        warnings_count: nxt.warnings.length,
        pag_database_present: nxt.pagDatabasePresent
      });
    }
    return nxt;
  }
}

/**
 * In-memory per sessionId: другие вкладки не сбрасываются (D13.4 / G13.6).
 */
export class PagGraphBySessionMap {
  private readonly map: Map<string, PagGraphSessionSnapshot> = new Map();

  get(sessionId: string): PagGraphSessionSnapshot | undefined {
    return this.map.get(sessionId);
  }

  has(sessionId: string): boolean {
    return this.map.has(sessionId);
  }

  set(sessionId: string, snap: PagGraphSessionSnapshot): void {
    this.map.set(sessionId, snap);
  }

  remove(sessionId: string): void {
    this.map.delete(sessionId);
  }
}
