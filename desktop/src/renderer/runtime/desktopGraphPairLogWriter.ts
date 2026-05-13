import type { AppendDesktopGraphPairLogResult } from "@shared/ipc";

import {
  buildAmCompactLine,
  buildAmFullLogBlock,
  buildDCompactLine,
  buildDFullLogBlock,
  wallClockUtcIso
} from "./desktopGraphPairLog";
import { buildDesktopPairlogAppendCompactLine } from "./pagGraphObservabilityCompact";

export type DesktopGraphPairLogEntry = {
  readonly fullRecord: string;
  readonly compactLine: string;
};

/**
 * Счётчики trace_seq / desktop_seq на один chat_id; запись через IPC в main.
 * Burst: один microtask сливает синхронную очередь. Multi-tick: coalesce ≥4 записей
 * за IPC или один flush за кадр через requestAnimationFrame при <4.
 */
export class DesktopGraphPairLogWriter {
  private static readonly MIN_IPC_BATCH: number = 4;

  private traceSeq: number = 0;
  private desktopSeq: number = 0;
  private readonly queue: DesktopGraphPairLogEntry[] = [];
  private microtaskScheduled: boolean = false;
  private rafScheduled: boolean = false;
  /** Сериализация IPC: нельзя откладывать старт drain на отдельный promise-tick (Burst-тест и microtask order). */
  private drainInFlight: boolean = false;

  constructor(private readonly chatId: string) {}

  logAmRow(row: Record<string, unknown>): void {
    const ts: string = wallClockUtcIso();
    this.traceSeq += 1;
    const seq: number = this.traceSeq;
    this.enqueue(buildAmFullLogBlock(ts, seq, row), buildAmCompactLine(ts, seq, row));
  }

  logD(event: string, detail: Record<string, unknown>): void {
    const ts: string = wallClockUtcIso();
    this.desktopSeq += 1;
    const seq: number = this.desktopSeq;
    this.enqueue(buildDFullLogBlock(ts, seq, event, detail), buildDCompactLine(ts, seq, event, detail));
  }

  private enqueue(fullRecord: string, compactLine: string): void {
    if (typeof window.ailitDesktop?.appendDesktopGraphPairLog !== "function") {
      return;
    }
    this.queue.push({ fullRecord, compactLine });
    this.scheduleMicrotaskDrain();
  }

  private scheduleMicrotaskDrain(): void {
    if (this.microtaskScheduled) {
      return;
    }
    this.microtaskScheduled = true;
    queueMicrotask(() => {
      this.microtaskScheduled = false;
      this.onMicrotaskDrain();
    });
  }

  private onMicrotaskDrain(): void {
    if (this.queue.length === 0) {
      return;
    }
    if (this.queue.length >= DesktopGraphPairLogWriter.MIN_IPC_BATCH) {
      this.requestDrain();
      return;
    }
    if (!this.rafScheduled) {
      this.rafScheduled = true;
      requestAnimationFrame(() => {
        this.rafScheduled = false;
        if (this.queue.length > 0) {
          this.requestDrain();
        }
      });
    }
  }

  private requestDrain(): void {
    if (this.drainInFlight) {
      return;
    }
    if (this.queue.length === 0) {
      return;
    }
    this.drainInFlight = true;
    void this.drainOnceIpc()
      .catch(() => undefined)
      .finally(() => {
        this.drainInFlight = false;
        if (this.queue.length > 0) {
          this.requestDrain();
        }
      });
  }

  private async drainOnceIpc(): Promise<void> {
    const fn: unknown = window.ailitDesktop?.appendDesktopGraphPairLog;
    if (typeof fn !== "function") {
      this.queue.length = 0;
      return;
    }
    const entries: DesktopGraphPairLogEntry[] = this.queue.splice(0, this.queue.length);
    if (entries.length === 0) {
      return;
    }
    const append = fn as (params: {
      readonly chatId: string;
      readonly entries: readonly DesktopGraphPairLogEntry[];
    }) => Promise<AppendDesktopGraphPairLogResult>;
    const result: AppendDesktopGraphPairLogResult = await append({
      chatId: this.chatId,
      entries
    });
    const ts: string = wallClockUtcIso();
    if (result.ok) {
      if ("skipped" in result && result.skipped === true) {
        return;
      }
      const line: string = buildDesktopPairlogAppendCompactLine({
        isoTimestamp: ts,
        chatId: this.chatId,
        batchSize: entries.length,
        bytes: null
      });
      console.info(line);
    } else {
      const err: string = result.error.length > 400 ? `${result.error.slice(0, 400)}…` : result.error;
      console.warn(`timestamp=${ts}\tevent=desktop.pairlog.append_failed\tchat_id=${this.chatId}\terror=${err}`);
    }
  }
}
