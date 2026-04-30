import type { ProjectRegistryEntry } from "@shared/ipc";

import { loadPagGraphMerged, type PagGraphSliceFn } from "./loadPagGraphMerged";
import { MEM3D_PAG_MAX_NODES } from "./pagGraphLimits";
import {
  lastPagSearchHighlightFromTrace,
  lastPagSearchHighlightFromTraceAfterMerge
} from "./pagHighlightFromTrace";
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
  buildPagGraphRevReconciledTraceRow,
  buildPagSnapshotRefreshedTraceRow,
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
    loadError: null
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

function buildSnapshotFromReconcile(
  merged: MemoryGraphData,
  revs: Readonly<RevRec>,
  lastIndex: number,
  warnings: readonly string[],
  loadState: PagGraphSessionSnapshot["loadState"],
  loadError: string | null,
  pagDatabasePresent: boolean
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
    loadError
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

function applyDeltasInRange(
  mergedIn: MemoryGraphData,
  revsFromSlice: RevRec,
  rows: readonly Record<string, unknown>[],
  from: number,
  toInclusive: number,
  namespaces: Readonly<Set<string>>,
  prevWarnings: readonly string[],
  useInitialTraceCatchup: boolean
): {
  readonly merged: MemoryGraphData;
  readonly revs: RevRec;
  readonly warnings: readonly string[];
  readonly namespacesDeltaTouched: ReadonlySet<string>;
} {
  const revsIn: RevRec = buildRevsInForDeltas(
    revsFromSlice,
    rows,
    from,
    toInclusive,
    namespaces,
    useInitialTraceCatchup
  );
  let merged: MemoryGraphData = mergedIn;
  const revs: RevRec = { ...revsIn };
  const baseWarnings: readonly string[] = reconcileStalePagGraphRevMismatchWarnings(
    prevWarnings,
    revsFromSlice,
    namespaces
  );
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
  }
  const deduped: readonly string[] = dedupePagGraphSnapshotWarnings(wlist);
  const collapsed: readonly string[] = collapsePagGraphRevMismatchWarningsToLatestPerNamespace(deduped);
  return { merged, revs, warnings: collapsed, namespacesDeltaTouched };
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

export class PagGraphSessionTraceMerge {
  /**
   * D-HI-1: `PagSearchHighlightV1` из последней **применимой** trace-строки (ledger / W14 и т.д.
   * в `pagHighlightFromTrace`). При инкременте без новых строк highlight не пересчитывается
   * (см. `applyIncremental`, architecture §4.3).
   */
  static applyHighlightFromTraceRows(
    merged: MemoryGraphData,
    rows: readonly Record<string, unknown>[],
    defaultNamespace: string,
    lastConsumedTraceIndex: number = -1
  ): MemoryGraphData {
    if (rows.length === 0) {
      return merged;
    }
    const previous: ReturnType<typeof lastPagSearchHighlightFromTrace> | null =
      lastConsumedTraceIndex < 0
        ? null
        : lastPagSearchHighlightFromTrace(
            rows.slice(0, lastConsumedTraceIndex + 1),
            defaultNamespace
          );
    const ev: ReturnType<typeof lastPagSearchHighlightFromTrace> = lastPagSearchHighlightFromTraceAfterMerge(
      rows,
      defaultNamespace,
      previous,
      lastConsumedTraceIndex
    );
    if (ev === null) {
      return merged;
    }
    return ensureHighlightNodes(merged, ev.nodeIds, ev.namespace);
  }

  /**
   * Сразу после `loadFull`: реплей существующих trace-rows на merged из БД (идемпотентно по merge),
   * затем highlight с последней применимой строки trace. Rev catch-up: см. `buildRevsInForDeltas` + `useInitialTraceCatchup`.
   */
  static afterFullLoad(
    merged0: MemoryGraphData,
    revs0: RevRec,
    rows: readonly Record<string, unknown>[],
    namespaces: readonly string[],
    defaultNamespace: string,
    pagDatabasePresent: boolean = true,
    hooks?: PagGraphTraceMergeEmitHooks
  ): PagGraphSessionSnapshot {
    const ns: Set<string> = new Set(namespaces);
    const lastRow: number = rows.length - 1;
    if (lastRow < 0) {
      const m1: MemoryGraphData = this.applyHighlightFromTraceRows(merged0, rows, defaultNamespace);
      const snap0: PagGraphSessionSnapshot = buildSnapshotFromReconcile(
        m1,
        revs0,
        -1,
        [],
        "ready",
        null,
        pagDatabasePresent
      );
      emitPagGraphObservability({
        hooks,
        namespaces,
        graphRevAfterByNs: revs0,
        namespacesDeltaTouched: new Set(),
        isAfterFullLoad: true
      });
      return snap0;
    }
    const ap: {
      readonly merged: MemoryGraphData;
      readonly revs: RevRec;
      readonly warnings: readonly string[];
      readonly namespacesDeltaTouched: ReadonlySet<string>;
    } = applyDeltasInRange(merged0, revs0, rows, 0, lastRow, ns, [], true);
    const m1: MemoryGraphData = this.applyHighlightFromTraceRows(ap.merged, rows, defaultNamespace);
    const snap: PagGraphSessionSnapshot = buildSnapshotFromReconcile(
      m1,
      ap.revs,
      lastRow,
      ap.warnings,
      "ready",
      null,
      pagDatabasePresent
    );
    emitPagGraphObservability({
      hooks,
      namespaces,
      graphRevAfterByNs: ap.revs,
      namespacesDeltaTouched: ap.namespacesDeltaTouched,
      isAfterFullLoad: true
    });
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
    hooks?: PagGraphTraceMergeEmitHooks
  ): PagGraphSessionSnapshot {
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
      useInitialTraceCatchup
    );
    const m1: MemoryGraphData = this.applyHighlightFromTraceRows(
      ap.merged,
      rows,
      defaultNamespace,
      cur.lastAppliedTraceIndex
    );
    const nxt: PagGraphSessionSnapshot = buildSnapshotFromReconcile(
      m1,
      ap.revs,
      end,
      ap.warnings,
      "ready",
      null,
      cur.pagDatabasePresent
    );
    emitPagGraphObservability({
      hooks,
      namespaces,
      graphRevAfterByNs: ap.revs,
      namespacesDeltaTouched: ap.namespacesDeltaTouched,
      isAfterFullLoad: false
    });
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
