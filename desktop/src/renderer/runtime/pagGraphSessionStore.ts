import type { ProjectRegistryEntry } from "@shared/ipc";

import { loadPagGraphMerged, type PagGraphSliceFn } from "./loadPagGraphMerged";
import { MEM3D_PAG_MAX_NODES } from "./pagGraphLimits";
import { highlightFromTraceRow } from "./pagHighlightFromTrace";
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
  readonly loadState: "idle" | "loading" | "ready" | "error";
  readonly loadError: string | null;
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
    const failCodes: (string | undefined)[] = [];
    let merged: MemoryGraphData = { nodes: [], links: [] };
    const revs: Record<string, number> = {};
    for (const namespace of namespaces) {
      const r: Awaited<ReturnType<typeof loadPagGraphMerged>> = await loadPagGraphMerged(
        (p) => slice(p) as never,
        { namespace, level: null }
      );
      if (!r.ok) {
        errors.push(`${namespace}: ${r.error}`);
        failCodes.push(r.errorCode);
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
        errors.length === namespaces.length && failCodes.every((c) => c === "missing_db");
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
  loadError: string | null
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
): { readonly merged: MemoryGraphData; readonly revs: RevRec; readonly warnings: readonly string[] } {
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
  const wlist: string[] = [...prevWarnings];
  for (let i: number = from; i <= toInclusive; i += 1) {
    const row: Record<string, unknown> = rows[i]! as Record<string, unknown>;
    const d: ReturnType<typeof parsePagGraphTraceDelta> = parsePagGraphTraceDelta(row);
    if (d === null) {
      continue;
    }
    if (!shouldApplyTraceDelta(d, namespaces)) {
      continue;
    }
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
  return { merged, revs, warnings: wlist };
}

export class PagGraphSessionTraceMerge {
  static applyHighlightFromLastRow(
    merged: MemoryGraphData,
    rows: readonly Record<string, unknown>[],
    defaultNamespace: string
  ): MemoryGraphData {
    if (rows.length === 0) {
      return merged;
    }
    const last: Record<string, unknown> = rows[rows.length - 1]! as Record<string, unknown>;
    const ev: ReturnType<typeof highlightFromTraceRow> = highlightFromTraceRow(last, defaultNamespace);
    if (ev === null) {
      return merged;
    }
    return ensureHighlightNodes(merged, ev.nodeIds, ev.namespace);
  }

  /**
   * Сразу после `loadFull`: реплей существующих trace-rows на merged из БД (идемпотентно по merge),
   * затем highlight с последней строки. Rev catch-up: см. `buildRevsInForDeltas` + `useInitialTraceCatchup`.
   */
  static afterFullLoad(
    merged0: MemoryGraphData,
    revs0: RevRec,
    rows: readonly Record<string, unknown>[],
    namespaces: readonly string[],
    defaultNamespace: string
  ): PagGraphSessionSnapshot {
    const ns: Set<string> = new Set(namespaces);
    const lastRow: number = rows.length - 1;
    if (lastRow < 0) {
      const m1: MemoryGraphData = this.applyHighlightFromLastRow(merged0, rows, defaultNamespace);
      return buildSnapshotFromReconcile(m1, revs0, -1, [], "ready", null);
    }
    const ap: {
      readonly merged: MemoryGraphData;
      readonly revs: RevRec;
      readonly warnings: readonly string[];
    } = applyDeltasInRange(merged0, revs0, rows, 0, lastRow, ns, [], true);
    const m1: MemoryGraphData = this.applyHighlightFromLastRow(ap.merged, rows, defaultNamespace);
    return buildSnapshotFromReconcile(m1, ap.revs, lastRow, ap.warnings, "ready", null);
  }

  /**
   * Инкремент: строго строки (last+1)..(len-1) — без N× pagGraphSlice.
   */
  static applyIncremental(
    cur: PagGraphSessionSnapshot,
    rows: readonly Record<string, unknown>[],
    namespaces: readonly string[],
    defaultNamespace: string
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
    const m1: MemoryGraphData = this.applyHighlightFromLastRow(ap.merged, rows, defaultNamespace);
    return buildSnapshotFromReconcile(m1, ap.revs, end, ap.warnings, "ready", null);
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
