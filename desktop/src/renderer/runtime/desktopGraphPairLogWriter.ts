import {
  buildAmCompactLine,
  buildAmFullLogBlock,
  buildDCompactLine,
  buildDFullLogBlock,
  wallClockUtcIso
} from "./desktopGraphPairLog";

export type DesktopGraphPairLogEntry = {
  readonly fullRecord: string;
  readonly compactLine: string;
};

/**
 * Счётчики trace_seq / desktop_seq на один chat_id; запись через IPC в main (батч microtask).
 */
export class DesktopGraphPairLogWriter {
  private traceSeq: number = 0;
  private desktopSeq: number = 0;
  private readonly queue: DesktopGraphPairLogEntry[] = [];
  private flushScheduled: boolean = false;

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
    if (!this.flushScheduled) {
      this.flushScheduled = true;
      queueMicrotask(() => {
        this.flush();
      });
    }
  }

  private flush(): void {
    this.flushScheduled = false;
    if (this.queue.length === 0) {
      return;
    }
    const entries: DesktopGraphPairLogEntry[] = this.queue.splice(0, this.queue.length);
    void window.ailitDesktop.appendDesktopGraphPairLog({
      chatId: this.chatId,
      entries
    });
  }
}
