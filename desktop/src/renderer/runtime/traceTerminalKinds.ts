import { RuntimeTraceNormalizer, type NormalizedKind, type NormalizedTraceProjection } from "./traceNormalize";

const normalizer: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();

function asDict(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

/**
 * Нормализованные виды, совпадающие с семантикой снятия хода в `projectChatTraceRows` (F-D2/F-D4).
 */
export const TERMINAL_NORMALIZED_TRACE_KINDS: ReadonlySet<NormalizedKind> = new Set<NormalizedKind>([
  "assistant_final",
  "turn_completed",
  "turn_failed",
  "error_row"
]);

export function isTerminalNormalizedTraceKind(kind: NormalizedKind): boolean {
  return TERMINAL_NORMALIZED_TRACE_KINDS.has(kind);
}

/** Как `readApprovalResolve` в `chatTraceProjector` — единый SoT для approval_resolve. */
export function readApprovalResolve(
  row: Record<string, unknown>
): { readonly callId: string; readonly ok: boolean | null } | null {
  if (row["type"] !== "service.request") {
    return null;
  }
  const payload: Record<string, unknown> | null = asDict(row["payload"]);
  if (!payload || payload["action"] !== "work.approval_resolve") {
    return null;
  }
  const callId: unknown = payload["call_id"];
  if (typeof callId !== "string" || callId.length === 0) {
    return null;
  }
  const ok: unknown = row["ok"];
  return { callId, ok: typeof ok === "boolean" ? ok : null };
}

function isSessionCancelledTopicRow(row: Record<string, unknown>): boolean {
  if (row["type"] !== "topic.publish") {
    return false;
  }
  const pl: Record<string, unknown> | null = asDict(row["payload"]);
  if (!pl || pl["type"] !== "topic.publish") {
    return false;
  }
  return pl["event_name"] === "session.cancelled";
}

/**
 * Строка требует немедленного flush coalesce-буфера до merge (F3).
 * Fail-open: при сомнении / `unknown` / ошибке нормализации — `true`, чтобы не задерживать terminal-путь.
 */
export function isTerminalTraceRowForAgentTurn(row: Record<string, unknown>): boolean {
  try {
    if (isSessionCancelledTopicRow(row)) {
      return true;
    }
    const approval: { readonly callId: string; readonly ok: boolean | null } | null = readApprovalResolve(row);
    if (approval?.ok === false) {
      return true;
    }
    const n: NormalizedTraceProjection = normalizer.normalizeLine(row);
    if (isTerminalNormalizedTraceKind(n.kind)) {
      return true;
    }
    if (n.kind === "unknown") {
      return true;
    }
    return false;
  } catch {
    return true;
  }
}

export type { NormalizedTraceProjection };
