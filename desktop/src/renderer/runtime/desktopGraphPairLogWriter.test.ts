import type { MockInstance } from "vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopGraphPairLogWriter } from "./desktopGraphPairLogWriter";

describe("DesktopGraphPairLogWriter", () => {
  let appendSpy: MockInstance<typeof window.ailitDesktop.appendDesktopGraphPairLog>;

  beforeEach(() => {
    appendSpy = vi.spyOn(window.ailitDesktop, "appendDesktopGraphPairLog").mockResolvedValue({
      ok: true,
      fullPath: "/tmp/ailit-desktop-full.log",
      compactPath: "/tmp/ailit-desktop-compact.log"
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("Burst TC-G4-PAIRLOG-Burst: 100 sync logD then one microtask drain → single IPC", async () => {
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const w: DesktopGraphPairLogWriter = new DesktopGraphPairLogWriter("chat-burst");
    for (let i: number = 0; i < 100; i += 1) {
      w.logD("evt", { i });
    }
    // Vitest async + IPC promise chain: несколько microtask-tick, чтобы завершился
    // `flushTail.then(() => drainOnceIpc)` и `await append` (см. TC-G4-PAIRLOG-Burst).
    for (let j: number = 0; j < 8; j += 1) {
      await Promise.resolve();
    }
    expect(appendSpy).toHaveBeenCalledTimes(1);
    const firstArg: unknown = appendSpy.mock.calls[0]?.[0];
    expect(firstArg).toMatchObject({ chatId: "chat-burst" });
    expect((firstArg as { entries: unknown[] }).entries).toHaveLength(100);
    await Promise.resolve();
    const infos: string = infoSpy.mock.calls.map((c) => String(c[0])).join("\n");
    expect(infos).toContain("desktop.pairlog.append");
    expect(infos).toContain("batch_size=100");
    expect(infos).toContain("bytes=null");
    infoSpy.mockRestore();
  });

  it("Multi-tick TC-G4-PAIRLOG-Multi-tick: 50×(logD + await) → IPC count ≤ 25", async () => {
    const w: DesktopGraphPairLogWriter = new DesktopGraphPairLogWriter("chat-mt");
    for (let i: number = 0; i < 50; i += 1) {
      w.logD("tick", { i });
      await Promise.resolve();
    }
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => {
        resolve();
      });
    });
    await Promise.resolve();
    expect(appendSpy.mock.calls.length).toBeLessThanOrEqual(25);
  });
});
