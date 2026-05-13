import { newMessageId } from "./uuid";

const DESKTOP_GOAL_ID: string = "g-desktop";

/** Логический id compact observability (grep/CI): append pair-log IPC batch. */
export const DESKTOP_PAIRLOG_APPEND_EVENT: string = "desktop.pairlog.append";

/** Compact D-source: начало bounded trace replay (ключи всегда; null по канону §Observability). */
export const DESKTOP_TRACE_REPLAY_START_EVENT: string = "desktop.trace.replay.start";

/** Compact D-source: конец bounded trace replay. */
export const DESKTOP_TRACE_REPLAY_END_EVENT: string = "desktop.trace.replay.end";

/**
 * Compact observability: ForceGraph3D `refresh()` (grep/CI); без DTO сцены.
 * C2: при `skipped_calls != null` поле `window_ms` обязано быть non-null (тот же emission).
 */
export const DESKTOP_GRAPH_REFRESH_EVENT: string = "desktop.graph.refresh";

/**
 * D2 / UC-G4-02: минимальный набор `reason` для `desktop.graph.refresh`.
 * Расширение только с явным обновлением контракта и review.
 */
export type DesktopGraphRefreshReason = "highlight" | "resize" | "layout" | "scene";

/** Алиас для импортов из прежних путей (`Mem3dGraphRefreshReason`). */
export type Mem3dGraphRefreshReason = DesktopGraphRefreshReason;

function formatScalar(value: number | null): string {
  if (value === null) {
    return "null";
  }
  return String(value);
}

/**
 * Одна grep-friendly строка для `console.info` / pair-log (без DTO сцены).
 * C2: `skipped_calls` — сумма пропущенных `fg.refresh()`; `window_ms` — ms от первого skip до emit.
 */
export function buildDesktopGraphRefreshCompactLine(p: {
  readonly isoTimestamp: string;
  readonly reason: DesktopGraphRefreshReason;
  readonly refresh_calls: number;
  readonly skipped_calls: number | null;
  readonly window_ms: number | null;
}): string {
  if (!Number.isInteger(p.refresh_calls) || p.refresh_calls < 0) {
    throw new Error("refresh_calls must be a non-negative integer");
  }
  if (p.skipped_calls !== null) {
    if (p.window_ms === null) {
      throw new Error("C2: window_ms must be non-null when skipped_calls is non-null");
    }
    if (!Number.isInteger(p.skipped_calls) || p.skipped_calls <= 0) {
      throw new Error("skipped_calls must be a positive integer when non-null");
    }
  }
  return (
    `timestamp=${p.isoTimestamp}\tevent=${DESKTOP_GRAPH_REFRESH_EVENT}\t` +
    `reason=${p.reason}\trefresh_calls=${String(p.refresh_calls)}\t` +
    `skipped_calls=${formatScalar(p.skipped_calls)}\twindow_ms=${formatScalar(p.window_ms)}`
  );
}

export function emitDesktopGraphRefreshCompact(p: {
  readonly reason: DesktopGraphRefreshReason;
  readonly refresh_calls: number;
  readonly skipped_calls: number | null;
  readonly window_ms: number | null;
  readonly isoNow?: () => string;
}): void {
  const iso: string = p.isoNow?.() ?? new Date().toISOString();
  console.info(
    buildDesktopGraphRefreshCompactLine({
      isoTimestamp: iso,
      reason: p.reason,
      refresh_calls: p.refresh_calls,
      skipped_calls: p.skipped_calls,
      window_ms: p.window_ms
    })
  );
}

/**
 * Payload для `emitDesktopGraphDebug(desktop.trace.replay.*)` / buildDCompactLine.
 * Не включает массив строк trace.
 */
export function buildDesktopTraceReplayStartDetail(p: {
  readonly row_count: number | null;
  readonly duration_ms: number | null;
  readonly rows_processed: number | null;
}): Record<string, unknown> {
  return {
    row_count: p.row_count,
    duration_ms: p.duration_ms,
    rows_processed: p.rows_processed
  };
}

export function buildDesktopTraceReplayEndDetail(p: {
  readonly row_count: number | null;
  readonly duration_ms: number | null;
  readonly rows_processed: number | null;
}): Record<string, unknown> {
  return {
    row_count: p.row_count,
    duration_ms: p.duration_ms,
    rows_processed: p.rows_processed
  };
}

function formatCompactReplayScalar(value: number | null): string {
  if (value === null) {
    return "null";
  }
  return String(value);
}

/**
 * Одна grep-friendly строка для `desktop.trace.replay.start` (ключи всегда в строке; null как литерал).
 */
export function buildDesktopTraceReplayStartCompactLine(p: {
  readonly isoTimestamp: string;
  readonly row_count: number | null;
  readonly duration_ms: number | null;
  readonly rows_processed: number | null;
}): string {
  return (
    `timestamp=${p.isoTimestamp}\tevent=${DESKTOP_TRACE_REPLAY_START_EVENT}\t` +
    `row_count=${formatCompactReplayScalar(p.row_count)}\t` +
    `duration_ms=${formatCompactReplayScalar(p.duration_ms)}\t` +
    `rows_processed=${formatCompactReplayScalar(p.rows_processed)}`
  );
}

/**
 * Одна grep-friendly строка для `desktop.trace.replay.end`.
 */
export function buildDesktopTraceReplayEndCompactLine(p: {
  readonly isoTimestamp: string;
  readonly row_count: number | null;
  readonly duration_ms: number | null;
  readonly rows_processed: number | null;
}): string {
  return (
    `timestamp=${p.isoTimestamp}\tevent=${DESKTOP_TRACE_REPLAY_END_EVENT}\t` +
    `row_count=${formatCompactReplayScalar(p.row_count)}\t` +
    `duration_ms=${formatCompactReplayScalar(p.duration_ms)}\t` +
    `rows_processed=${formatCompactReplayScalar(p.rows_processed)}`
  );
}

/**
 * Одна строка `desktop.pairlog.append` после успешного IPC (без payload графа).
 * `batch_size` — положительное целое; `bytes=null`, если счётчик байт не вычислялся.
 */
export function buildDesktopPairlogAppendCompactLine(p: {
  readonly isoTimestamp: string;
  readonly chatId: string;
  readonly batchSize: number;
  readonly bytes: number | null;
}): string {
  if (!Number.isInteger(p.batchSize) || p.batchSize <= 0) {
    throw new Error("batchSize must be a positive integer");
  }
  const chat: string = p.chatId.replace(/\s+/g, " ").trim();
  const bsz: string = String(p.batchSize);
  if (p.bytes === null) {
    return `timestamp=${p.isoTimestamp}\tevent=${DESKTOP_PAIRLOG_APPEND_EVENT}\tchat_id=${chat}\tbatch_size=${bsz}\tbytes=null`;
  }
  return `timestamp=${p.isoTimestamp}\tevent=${DESKTOP_PAIRLOG_APPEND_EVENT}\tchat_id=${chat}\tbatch_size=${bsz}\tbytes=${String(p.bytes)}`;
}

export type PagGraphRevReconciledReasonCode =
  | "post_slice"
  | "post_trace"
  | "post_refresh"
  | "user_refresh"
  | "debounce_merge"
  | "poll_retry";

export type PagSnapshotRefreshedReasonCode =
  | "user_refresh"
  | "poll_retry"
  | "post_refresh"
  | "initial_load";

function maxGraphRevForNamespaces(
  graphRevByNamespace: Readonly<Record<string, number>>,
  namespaces: readonly string[]
): number {
  let m: number = 0;
  for (const ns of namespaces) {
    const v: number = graphRevByNamespace[ns] ?? 0;
    if (v > m) {
      m = v;
    }
  }
  return m;
}

export function buildPagGraphRevReconciledTraceRow(p: {
  readonly chatId: string;
  readonly sessionId: string;
  readonly namespace: string;
  readonly graph_rev_before: number | null;
  readonly graph_rev_after: number;
  readonly reason_code: PagGraphRevReconciledReasonCode;
}): Record<string, unknown> {
  const traceId: string = newMessageId();
  const messageId: string = newMessageId();
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: p.chatId,
    broker_id: `broker-${p.chatId}`,
    trace_id: traceId,
    message_id: messageId,
    parent_message_id: null,
    goal_id: DESKTOP_GOAL_ID,
    namespace: p.namespace,
    from_agent: "User:desktop",
    to_agent: `AgentWork:${p.chatId}`,
    created_at: new Date().toISOString(),
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "pag_graph_rev_reconciled",
      payload: {
        session_id: p.sessionId,
        namespace: p.namespace,
        graph_rev_before: p.graph_rev_before,
        graph_rev_after: p.graph_rev_after,
        reason_code: p.reason_code
      }
    }
  };
}

export function buildPagSnapshotRefreshedTraceRow(p: {
  readonly chatId: string;
  readonly sessionId: string;
  readonly namespaces: readonly string[];
  readonly graphRevByNamespace: Readonly<Record<string, number>>;
  readonly reason_code: PagSnapshotRefreshedReasonCode;
}): Record<string, unknown> {
  const traceId: string = newMessageId();
  const messageId: string = newMessageId();
  const graph_rev_after: number = maxGraphRevForNamespaces(p.graphRevByNamespace, p.namespaces);
  const inner: Record<string, unknown> = {
    session_id: p.sessionId,
    graph_rev_after: graph_rev_after,
    reason_code: p.reason_code
  };
  if (p.namespaces.length === 1) {
    inner["namespace"] = p.namespaces[0] ?? "";
  } else {
    inner["namespaces"] = [...p.namespaces];
  }
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: p.chatId,
    broker_id: `broker-${p.chatId}`,
    trace_id: traceId,
    message_id: messageId,
    parent_message_id: null,
    goal_id: DESKTOP_GOAL_ID,
    namespace: p.namespaces[0] ?? "",
    from_agent: "User:desktop",
    to_agent: `AgentWork:${p.chatId}`,
    created_at: new Date().toISOString(),
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "pag_snapshot_refreshed",
      payload: inner
    }
  };
}

/** D2: min interval highlight-path; sliding budget for всех `fg.refresh()`. */
const MEM3D_REFRESH_BUDGET_WINDOW_MS: number = 1000;
const MEM3D_REFRESH_MAX_PER_WINDOW: number = 20;
const MEM3D_REFRESH_MIN_HIGHLIGHT_INTERVAL_MS: number = 50;

/** Минимальный контракт для `fg.refresh()` без импорта react-force-graph-3d типов в gate. */
export type ForceGraphMethodsLike = {
  readonly refresh: () => void;
};

export type Mem3dGraphRefreshGateDeps = {
  readonly now: () => number;
  readonly emit: (p: {
    readonly reason: DesktopGraphRefreshReason;
    readonly refresh_calls: number;
    readonly skipped_calls: number | null;
    readonly window_ms: number | null;
  }) => void;
};

/**
 * Единая агрегирующая точка throttle/budget для всех путей `fg.refresh` на 3D-странице (plan §5.2).
 * highlight: min-interval 50 ms; resize/layout: без min-interval; scene: без min-interval и без учёта
 * в бюджете 20/1000 ms (первая отрисовка после готовности сцены, D2 / UC-G4-02).
 */
export class Mem3dGraphRefreshGate {
  private readonly nowFn: () => number;
  private readonly emitFn: Mem3dGraphRefreshGateDeps["emit"];
  private readonly refreshTimestampsMs: number[] = [];
  private lastHighlightWaveExecutedAtMs: number = Number.NEGATIVE_INFINITY;
  private skipWindowStartMs: number | null = null;
  /** Суммарное число пропущенных `fg.refresh()` (не волн), см. C2. */
  private pendingSkippedRefreshCalls: number = 0;

  public constructor(deps?: Partial<Mem3dGraphRefreshGateDeps>) {
    this.nowFn = deps?.now ?? ((): number => Date.now());
    this.emitFn =
      deps?.emit ??
      ((q: { reason: DesktopGraphRefreshReason; refresh_calls: number; skipped_calls: number | null; window_ms: number | null }): void => {
        emitDesktopGraphRefreshCompact({
          reason: q.reason,
          refresh_calls: q.refresh_calls,
          skipped_calls: q.skipped_calls,
          window_ms: q.window_ms
        });
      });
  }

  private pruneWindowEnd(nowMs: number): void {
    const cut: number = nowMs - MEM3D_REFRESH_BUDGET_WINDOW_MS;
    while (this.refreshTimestampsMs.length > 0) {
      const first: number | undefined = this.refreshTimestampsMs[0];
      if (first === undefined || first > cut) {
        break;
      }
      this.refreshTimestampsMs.shift();
    }
  }

  private countInWindow(): number {
    return this.refreshTimestampsMs.length;
  }

  /**
   * @returns `true`, если хотя бы один `fg.refresh()` был выполнен.
   */
  public tryRefreshPanels(
    reason: DesktopGraphRefreshReason,
    panels: ReadonlyArray<ForceGraphMethodsLike | undefined>
  ): boolean {
    const list: ForceGraphMethodsLike[] = panels.filter((x): x is ForceGraphMethodsLike => x !== undefined);
    const n: number = list.length;
    if (n === 0) {
      return false;
    }
    const nowMs: number = this.nowFn();
    this.pruneWindowEnd(nowMs);

    const sceneBypass: boolean = reason === "scene";
    const highlightIntervalOk: boolean =
      sceneBypass ||
      reason !== "highlight" ||
      nowMs - this.lastHighlightWaveExecutedAtMs >= MEM3D_REFRESH_MIN_HIGHLIGHT_INTERVAL_MS;
    const budgetOk: boolean =
      sceneBypass || this.countInWindow() + n <= MEM3D_REFRESH_MAX_PER_WINDOW;

    if (!highlightIntervalOk || !budgetOk) {
      if (this.skipWindowStartMs === null) {
        this.skipWindowStartMs = nowMs;
      }
      this.pendingSkippedRefreshCalls += n;
      return false;
    }

    for (const fg of list) {
      fg.refresh();
      if (!sceneBypass) {
        this.refreshTimestampsMs.push(nowMs);
      }
    }

    if (reason === "highlight") {
      this.lastHighlightWaveExecutedAtMs = nowMs;
    }

    const skippedCalls: number | null =
      this.pendingSkippedRefreshCalls > 0 ? this.pendingSkippedRefreshCalls : null;
    const windowMs: number | null =
      skippedCalls !== null && this.skipWindowStartMs !== null
        ? Math.max(0, Math.floor(nowMs - this.skipWindowStartMs))
        : null;

    this.emitFn({
      reason,
      refresh_calls: n,
      skipped_calls: skippedCalls,
      window_ms: windowMs
    });

    this.pendingSkippedRefreshCalls = 0;
    this.skipWindowStartMs = null;
    return true;
  }

  /** Только для vitest: сброс окна skip/budget. */
  public resetForTests(): void {
    this.refreshTimestampsMs.length = 0;
    this.lastHighlightWaveExecutedAtMs = Number.NEGATIVE_INFINITY;
    this.skipWindowStartMs = null;
    this.pendingSkippedRefreshCalls = 0;
  }
}

export function extractCompactPagEventPayload(
  row: Readonly<Record<string, unknown>>
): Readonly<Record<string, unknown>> | null {
  if (row["type"] !== "topic.publish") {
    return null;
  }
  const pl: unknown = row["payload"];
  if (!pl || typeof pl !== "object" || Array.isArray(pl)) {
    return null;
  }
  const p1: Record<string, unknown> = pl as Record<string, unknown>;
  const en: unknown = p1["event_name"];
  if (en !== "pag_graph_rev_reconciled" && en !== "pag_snapshot_refreshed") {
    return null;
  }
  const inner: unknown = p1["payload"];
  if (!inner || typeof inner !== "object" || Array.isArray(inner)) {
    return null;
  }
  return inner as Readonly<Record<string, unknown>>;
}
