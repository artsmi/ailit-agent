/**
 * Одна ветка бюджета кадра: ``longtask`` **или** gap rAF (OR-D6 / архитектура FC-1).
 */

const DEFAULT_WINDOW_MS: number = 3000;

export type RendererBudgetSource = "longtask" | "raf_gap" | "unavailable";

export type RendererBudgetDiagnosticFields = {
  readonly renderer_budget_source: RendererBudgetSource;
  readonly longtask_duration_ms: number | null;
  readonly raf_gap_ms_p95: number | null;
};

function percentile95(values: readonly number[]): number | null {
  if (values.length === 0) {
    return null;
  }
  const sorted: number[] = [...values].sort((a, b) => a - b);
  const idx: number = Math.ceil(0.95 * sorted.length) - 1;
  const i: number = Math.max(0, Math.min(sorted.length - 1, idx));
  return Math.round(sorted[i]!);
}

export class RendererBudgetTelemetry {
  private readonly windowMs: number;
  private observer: PerformanceObserver | null = null;
  private longtaskBranch: boolean = false;
  private maxLongtaskMs: number = 0;
  private windowStartMs: number = 0;
  private rafGapsMs: number[] = [];
  private lastRafMs: number | null = null;

  public constructor(windowMs: number = DEFAULT_WINDOW_MS) {
    this.windowMs = windowMs;
  }

  public mount(): void {
    try {
      const obs: PerformanceObserver = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          if (e.entryType !== "longtask") {
            continue;
          }
          const d: number = Math.round(e.duration);
          if (d > this.maxLongtaskMs) {
            this.maxLongtaskMs = d;
          }
        }
      });
      const observeInit: Parameters<PerformanceObserver["observe"]>[0] = {
        type: "longtask",
        buffered: true
      };
      obs.observe(observeInit);
      this.observer = obs;
      this.longtaskBranch = true;
    } catch {
      this.longtaskBranch = false;
      this.observer = null;
    }
    this.windowStartMs = typeof performance !== "undefined" ? performance.now() : 0;
  }

  public unmount(): void {
    if (this.observer) {
      this.observer.disconnect();
      this.observer = null;
    }
    this.rafGapsMs = [];
    this.lastRafMs = null;
  }

  /**
   * Вызывать из rAF; при ветке ``longtask`` gaps не собираются (OR-D6: одна ветка).
   */
  public onAnimationFrame(nowMs: number, traceActive: boolean): void {
    if (this.longtaskBranch) {
      return;
    }
    if (!traceActive) {
      this.lastRafMs = null;
      return;
    }
    if (this.lastRafMs != null) {
      const gap: number = Math.max(0, nowMs - this.lastRafMs);
      if (gap > 0 && gap < 10_000) {
        this.rafGapsMs.push(gap);
      }
    }
    this.lastRafMs = nowMs;
    if (nowMs - this.windowStartMs > this.windowMs * 2) {
      this.rafGapsMs = this.rafGapsMs.slice(-200);
      this.windowStartMs = nowMs;
    }
  }

  /**
   * Снимок для compact-строки; сбрасывает окно longtask после чтения.
   */
  public consumeForDiagnostic(nowMs: number): RendererBudgetDiagnosticFields {
    if (this.longtaskBranch) {
      const v: number | null = this.maxLongtaskMs > 0 ? this.maxLongtaskMs : null;
      this.maxLongtaskMs = 0;
      return {
        renderer_budget_source: "longtask",
        longtask_duration_ms: v,
        raf_gap_ms_p95: null
      };
    }
    if (this.rafGapsMs.length > 0) {
      const sorted: number[] = [...this.rafGapsMs].sort((a, b) => a - b);
      const p95: number | null = percentile95(sorted);
      this.rafGapsMs = [];
      return {
        renderer_budget_source: "raf_gap",
        longtask_duration_ms: null,
        raf_gap_ms_p95: p95
      };
    }
    void nowMs;
    return {
      renderer_budget_source: "unavailable",
      longtask_duration_ms: null,
      raf_gap_ms_p95: null
    };
  }
}
