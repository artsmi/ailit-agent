import { describe, expect, it } from "vitest";

import { TraceRowsPerSecondSlidingWindow } from "./desktopSessionTraceThroughputWindow";

/** TC-G19.1-UNIT-01: скользящее окно trace append rate (OR-D6 D-D3). */
describe("TraceRowsPerSecondSlidingWindow (G19.1)", () => {
  it("TC-G19.1-UNIT-01: sums appends within one second window", () => {
    const w: TraceRowsPerSecondSlidingWindow = new TraceRowsPerSecondSlidingWindow();
    const t0: number = 10_000;
    expect(w.recordMerge(2, t0)).toBe(2);
    expect(w.recordMerge(1, t0 + 400)).toBe(3);
    expect(w.recordMerge(0, t0 + 900)).toBe(3);
    expect(w.recordMerge(0, t0 + 2000)).toBe(0);
  });
});
