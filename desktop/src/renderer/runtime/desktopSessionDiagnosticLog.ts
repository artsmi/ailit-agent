import type { NormalizedTraceProjection } from "./traceNormalize";

/**
 * Одна строка для `session/desk-diagnostic-*.log` (append-only, разбор UI vs trace).
 */
export function formatTraceProjectionDiagnosticLine(
  eventSeq: number,
  n: NormalizedTraceProjection
): string {
  const tip: string = n.technicalLine.replace(/\s+/g, " ").trim().slice(0, 240);
  return `${n.createdAt}\teventSeq=${String(eventSeq)}\t${n.kind}\t${n.messageId}\t${tip}`;
}
