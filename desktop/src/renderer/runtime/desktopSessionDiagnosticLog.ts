import type { NormalizedTraceProjection } from "./traceNormalize";
import { MEMORY_W14_GRAPH_HIGHLIGHT_EVENT } from "./pagHighlightFromTrace";
import type { BrokerRequestResult } from "@shared/ipc";

/**
 * D-PAGMODE-1: единственный литерал режима trace-only accumulation в session diagnostic.
 */
export const PAG_MODE_TRACE_ONLY_ACCUMULATION: string = "pag_mode=trace_only_accumulation";

/** OR-D6 / C2: round-trip ``brokerRequest`` (renderer → main → broker). */
export const DESKTOP_SESSION_BROKER_REQUEST_EVENT: string = "desktop.session.broker_request";

/** OR-D6: throttled live trace merge (без массива trace). */
export const DESKTOP_SESSION_TRACE_MERGE_EVENT: string = "desktop.session.trace_merge";

const DIAG_SUBJECT_MAX_CHARS: number = 200;
const BOUNDED_SESSION_DIAGNOSTIC_ID_MAX: number = 128;

function compactWhitespace(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function truncateSubjectField(value: string, maxChars: number): { readonly text: string; readonly truncated: boolean } {
  if (value.length <= maxChars) {
    return { text: value, truncated: false };
  }
  return { text: value.slice(0, maxChars), truncated: true };
}

export function boundedDesktopSessionDiagnosticId(value: string): string {
  const t: string = compactWhitespace(value);
  if (t.length <= BOUNDED_SESSION_DIAGNOSTIC_ID_MAX) {
    return t;
  }
  return `${t.slice(0, BOUNDED_SESSION_DIAGNOSTIC_ID_MAX)}…`;
}

function formatTraceRowsPerSecForDiagnostic(n: number): string {
  if (!Number.isFinite(n)) {
    return "0";
  }
  return String(Math.round(n * 1000) / 1000);
}

export function mapBrokerRequestOutcome(r: BrokerRequestResult): "ok" | "timeout" | "error" {
  if (r.ok) {
    return "ok";
  }
  const msg: string = r.error.toLowerCase();
  if (msg.includes("timeout") || msg.includes("timed out") || msg.includes("etimedout")) {
    return "timeout";
  }
  return "error";
}

/**
 * FC-3: compact renderer; **forbidden** — тело ответа broker, raw trace, промпты.
 */
export function formatDesktopSessionBrokerRequestLine(p: {
  readonly isoTimestamp: string;
  readonly durationMs: number;
  readonly outcome: "ok" | "timeout" | "error";
  readonly chatId: string;
  readonly sessionUi: string;
  readonly brokerOp: string;
  readonly rawTraceRowsLength: number;
  readonly traceRowsPerSec: number;
  readonly rendererBudgetSource: "longtask" | "raf_gap" | "unavailable";
  readonly longtaskDurationMs: number | null;
  readonly rafGapMsP95: number | null;
}): string {
  const op: string = compactWhitespace(p.brokerOp).replace(/\s+/g, "_").slice(0, 48);
  const lt: string =
    p.longtaskDurationMs == null
      ? "\tlongtask_duration_ms=null"
      : `\tlongtask_duration_ms=${String(p.longtaskDurationMs)}`;
  const raf: string =
    p.rafGapMsP95 == null ? "\traf_gap_ms_p95=null" : `\traf_gap_ms_p95=${String(p.rafGapMsP95)}`;
  return (
    `timestamp=${p.isoTimestamp}\tevent=${DESKTOP_SESSION_BROKER_REQUEST_EVENT}\t` +
    `broker_op=${op}\tduration_ms=${String(Math.max(0, Math.round(p.durationMs)))}\t` +
    `outcome=${p.outcome}\tchat_id=${boundedDesktopSessionDiagnosticId(p.chatId)}\t` +
    `session_ui=${boundedDesktopSessionDiagnosticId(p.sessionUi)}\t` +
    `rawTraceRows_length=${String(Math.max(0, Math.round(p.rawTraceRowsLength)))}\t` +
    `trace_rows_per_sec=${formatTraceRowsPerSecForDiagnostic(p.traceRowsPerSec)}\t` +
    `renderer_budget_source=${p.rendererBudgetSource}` +
    lt +
    raf
  );
}

export function formatDesktopSessionTraceMergeLine(p: {
  readonly isoTimestamp: string;
  readonly rawTraceRowsLength: number;
  readonly traceRowsPerSec: number;
}): string {
  return (
    `timestamp=${p.isoTimestamp}\tevent=${DESKTOP_SESSION_TRACE_MERGE_EVENT}\t` +
    `rawTraceRows_length=${String(Math.max(0, Math.round(p.rawTraceRowsLength)))}\t` +
    `trace_rows_per_sec=${formatTraceRowsPerSecForDiagnostic(p.traceRowsPerSec)}`
  );
}

export function emitDesktopSessionCompactInfo(line: string): void {
  console.info(line);
}

/**
 * Таблица stdout → compact source для `memory.w14_graph_highlight` (failure-retry-observability §маппинг).
 */
export function mapPagSearchHighlightReasonToDiagnosticSource(reason: string): string {
  const r: string = reason.trim();
  if (r === MEMORY_W14_GRAPH_HIGHLIGHT_EVENT || r === "memory.w14_graph_highlight") {
    return "w14_trace";
  }
  if (r === "context.memory_injected") {
    return "context_memory_injected";
  }
  if (r === "context.compacted") {
    return "context_compacted";
  }
  if (r === "context.restored") {
    return "context_restored";
  }
  return "unknown";
}

export type MemoryPagGraphDiagnosticOp = "node" | "edge";

/**
 * Компактная строка: `memory.pag_graph` (op node|edge) после применения дельты в merge.
 */
export function formatMemoryPagGraphDiagnosticLine(p: {
  readonly isoTimestamp: string;
  readonly op: MemoryPagGraphDiagnosticOp;
  readonly namespace: string;
  readonly rev: number;
  readonly subject: string;
}): string {
  const subjRaw: string = compactWhitespace(p.subject);
  const subj: { readonly text: string; readonly truncated: boolean } = truncateSubjectField(
    subjRaw,
    DIAG_SUBJECT_MAX_CHARS
  );
  const trunc: string = subj.truncated ? "\ttruncated=true" : "";
  return (
    `timestamp=${p.isoTimestamp}\tevent=memory.pag_graph\top=${p.op}\tsubject=${subj.text}` +
    `\tnamespace=${p.namespace}\trev=${String(p.rev)}${trunc}`
  );
}

/**
 * Подсветка после gating (C-HL-1): обязательный `source=` по канону compact.
 */
export function formatMemoryW14GraphHighlightDiagnosticLine(p: {
  readonly isoTimestamp: string;
  readonly namespace: string;
  readonly source: string;
  readonly nodeCount: number;
  readonly edgeCount: number;
  readonly ttlMs: number;
  readonly queryId?: string | null;
}): string {
  const qid: string =
    p.queryId != null && String(p.queryId).trim().length > 0
      ? `\tquery_id=${String(p.queryId).trim()}`
      : "";
  return (
    `timestamp=${p.isoTimestamp}\tevent=memory.w14_graph_highlight\tsource=${p.source}` +
    `\tnamespace=${p.namespace}\tnode_count=${String(p.nodeCount)}` +
    `\tedge_count=${String(p.edgeCount)}\tttl_ms=${String(p.ttlMs)}` +
    qid
  );
}

/** D-PAGMODE-1: первый вход trace-only для namespace (дедуп снаружи). */
export function formatTraceOnlyPagModeDiagnosticLine(p: {
  readonly isoTimestamp: string;
  readonly namespace: string;
  readonly sessionId: string;
}): string {
  return (
    `timestamp=${p.isoTimestamp}\tevent=pag_mode_transition\t${PAG_MODE_TRACE_ONLY_ACCUMULATION}` +
    `\tnamespace=${p.namespace}\tsession_ui=${p.sessionId}`
  );
}

/** UC-02 A2: таймаут выбора режима межпроектных рёбер → fallback F. */
export function formatCrossProjectEdgeDecisionTimeoutDiagnosticLine(p: {
  readonly isoTimestamp: string;
  readonly hiddenCrossEdgesCount: number;
  readonly timeoutS: number;
  readonly namespace: string;
}): string {
  return (
    `timestamp=${p.isoTimestamp}\tevent=cross_project_edge_decision_timeout` +
    `\thidden_cross_edges_count=${String(p.hiddenCrossEdgesCount)}` +
    `\ttimeout_s=${String(p.timeoutS)}\tnamespace=${p.namespace}`
  );
}

/**
 * Устаревший формат строки trace projection; пара логов графа — `ailit-desktop-*.log` (см. `desktopGraphPairLog.ts`).
 */
export function formatTraceProjectionDiagnosticLine(
  eventSeq: number,
  n: NormalizedTraceProjection
): string {
  const tip: string = n.technicalLine.replace(/\s+/g, " ").trim().slice(0, 240);
  return `${n.createdAt}\teventSeq=${String(eventSeq)}\t${n.kind}\t${n.messageId}\t${tip}`;
}
