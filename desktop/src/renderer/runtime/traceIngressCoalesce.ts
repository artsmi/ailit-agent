import { dedupKeyForRow } from "./traceNormalize";
import { isTerminalTraceRowForAgentTurn } from "./traceTerminalKinds";

/** Верхняя граница coalesce до принудительного flush (backpressure). */
export const DESKTOP_TRACE_COALESCE_MAX_BUFFER_ROWS: number = 48;

/**
 * Одна операция merge: эквивалент одного вызова `mergeRows` в `DesktopSessionContext` (дедуп по `dedupKeyForRow`).
 */
export function applyTraceRowsMergeBatch(
  prev: readonly Record<string, unknown>[],
  incoming: readonly Record<string, unknown>[],
  seenRowKeys: Set<string>
): Record<string, unknown>[] {
  const next: Record<string, unknown>[] = [...prev];
  const byKey: Map<string, number> = new Map();
  next.forEach((r, i) => {
    byKey.set(dedupKeyForRow(r), i);
  });
  for (const r of incoming) {
    const k: string = dedupKeyForRow(r);
    if (seenRowKeys.has(k)) {
      const idx: number | undefined = byKey.get(k);
      if (idx !== undefined) {
        next[idx] = r;
      }
    } else {
      seenRowKeys.add(k);
      next.push(r);
      byKey.set(k, next.length - 1);
    }
  }
  return next;
}

export type TraceIngressMergeBatch = readonly Record<string, unknown>[];

/**
 * Порядок батчей для той же семантики, что рантайм: terminal → flush буфера → merge terminal;
 * буфер ограничен `maxBuffer`; в конце входа — flush хвоста.
 */
export function computeTraceIngressMergeBatches(
  input: readonly Record<string, unknown>[],
  maxBuffer: number,
  isTerminal: (row: Record<string, unknown>) => boolean = isTerminalTraceRowForAgentTurn
): TraceIngressMergeBatch[] {
  const batches: Record<string, unknown>[][] = [];
  let buf: Record<string, unknown>[] = [];
  const flushBuf = (): void => {
    if (buf.length > 0) {
      batches.push([...buf]);
      buf = [];
    }
  };
  for (const row of input) {
    if (isTerminal(row)) {
      flushBuf();
      batches.push([row]);
    } else {
      buf.push(row);
      if (buf.length >= maxBuffer) {
        flushBuf();
      }
    }
  }
  flushBuf();
  return batches;
}

/** Симуляция последовательных одиночных merge для сравнения с батчами. */
export function simulateSequentialSingleRowMerges(
  rows: readonly Record<string, unknown>[]
): Record<string, unknown>[] {
  const seen: Set<string> = new Set();
  let acc: Record<string, unknown>[] = [];
  for (const row of rows) {
    acc = applyTraceRowsMergeBatch(acc, [row], seen);
  }
  return acc;
}

/** Симуляция батчей, вычисленных coalesce-планом. */
export function simulateBatchedMerges(
  rows: readonly Record<string, unknown>[],
  maxBuffer: number,
  isTerminal: (row: Record<string, unknown>) => boolean = isTerminalTraceRowForAgentTurn
): Record<string, unknown>[] {
  const batches: TraceIngressMergeBatch[] = computeTraceIngressMergeBatches(rows, maxBuffer, isTerminal);
  const seen: Set<string> = new Set();
  let acc: Record<string, unknown>[] = [];
  for (const batch of batches) {
    acc = applyTraceRowsMergeBatch(acc, batch, seen);
  }
  return acc;
}
