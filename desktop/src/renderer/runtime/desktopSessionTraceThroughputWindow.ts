/**
 * Скользящее окно ~1 с для агрегата «строк trace / с» без копирования `rawTraceRows`.
 */

export class TraceRowsPerSecondSlidingWindow {
  private readonly queue: Array<{ readonly t: number; readonly c: number }> = [];
  private sum: number = 0;

  /**
   * Учитывает только новые строки (append), не in-place dedup replace.
   *
   * @param appendedRows — число новых ключей в merge.
   * @param nowMs — монотонное время (``performance.now()``).
   * @returns оценка строк за последнюю 1 с (целое ≥ 0).
   */
  recordMerge(appendedRows: number, nowMs: number): number {
    if (appendedRows > 0) {
      this.queue.push({ t: nowMs, c: appendedRows });
      this.sum += appendedRows;
    }
    while (this.queue.length > 0) {
      const first: { readonly t: number; readonly c: number } | undefined = this.queue[0];
      if (first === undefined || first.t >= nowMs - 1000) {
        break;
      }
      const head: { readonly t: number; readonly c: number } | undefined = this.queue.shift();
      if (head !== undefined) {
        this.sum -= head.c;
      }
    }
    return Math.max(0, Math.round(this.sum));
  }
}
