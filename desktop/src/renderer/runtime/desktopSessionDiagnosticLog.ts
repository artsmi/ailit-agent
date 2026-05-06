import type { NormalizedTraceProjection } from "./traceNormalize";
import { MEMORY_W14_GRAPH_HIGHLIGHT_EVENT } from "./pagHighlightFromTrace";

/**
 * D-PAGMODE-1: единственный литерал режима trace-only accumulation в session diagnostic.
 */
export const PAG_MODE_TRACE_ONLY_ACCUMULATION: string = "pag_mode=trace_only_accumulation";

const DIAG_SUBJECT_MAX_CHARS: number = 200;

function compactWhitespace(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function truncateSubjectField(value: string, maxChars: number): { readonly text: string; readonly truncated: boolean } {
  if (value.length <= maxChars) {
    return { text: value, truncated: false };
  }
  return { text: value.slice(0, maxChars), truncated: true };
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
 * D-TRACE-CONN-1: синтетический узел связности в проекции ForceGraph (не PAG).
 */
export function formatTraceConnNodeInsertedDiagnosticLine(p: {
  readonly isoTimestamp: string;
  readonly namespace: string;
  readonly componentCount: number;
  readonly representativeNodeIds: readonly string[];
}): string {
  const reps: string = p.representativeNodeIds.join(",");
  return (
    `timestamp=${p.isoTimestamp}\tevent=memory.graph.trace_conn_node\tnamespace=${p.namespace}` +
    `\tcomponent_count=${String(p.componentCount)}\trepresentatives=${reps}`
  );
}

/**
 * Одна строка для `…/chat_logs/<safe>/desk-diagnostic-*.log` (append-only, разбор UI vs trace).
 */
export function formatTraceProjectionDiagnosticLine(
  eventSeq: number,
  n: NormalizedTraceProjection
): string {
  const tip: string = n.technicalLine.replace(/\s+/g, " ").trim().slice(0, 240);
  return `${n.createdAt}\teventSeq=${String(eventSeq)}\t${n.kind}\t${n.messageId}\t${tip}`;
}
