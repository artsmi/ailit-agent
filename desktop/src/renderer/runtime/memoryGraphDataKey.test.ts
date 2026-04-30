import { describe, expect, it } from "vitest";

import {
  computeMemoryGraphDataKey,
  graphLoadPhaseForDataKey,
  type MemoryGraphDataKeySnap
} from "./memoryGraphDataKey";

function snapBase(): MemoryGraphDataKeySnap {
  return {
    loadState: "ready",
    pagDatabasePresent: false,
    graphRevByNamespace: { "ns-a": 3 }
  };
}

describe("memoryGraphDataKey (2.3 / задача 1.3, вариант A)", () => {
  it("индикатор A: нет n{count} в строке; одинаковый snap-контракт (без длины merged) даёт один ключ", () => {
    const s: MemoryGraphDataKeySnap = snapBase();
    const k: string = computeMemoryGraphDataKey({
      activeSessionId: "ses-1",
      snap: s
    });
    expect(computeMemoryGraphDataKey({ activeSessionId: "ses-1", snap: s })).toBe(k);
    expect(k).not.toMatch(/n\d+/);
  });

  it("меняется только при error vs live (ready/loading/idle дают одну фазу)", () => {
    const liveKey: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), loadState: "ready" }
    });
    expect(computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), loadState: "loading" }
    })).toBe(liveKey);
    expect(computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), loadState: "idle" }
    })).toBe(liveKey);
    const errKey: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), loadState: "error" }
    });
    expect(errKey).not.toBe(liveKey);
    expect(graphLoadPhaseForDataKey("ready")).toBe("live");
    expect(graphLoadPhaseForDataKey("error")).toBe("error");
  });

  it("3.1: второй запрос (loading→ready) при том же rev и pd — тот же ключ, без n{count}", () => {
    const s: MemoryGraphDataKeySnap = {
      loadState: "ready",
      pagDatabasePresent: true,
      graphRevByNamespace: { "ns-a": 7, "ns-b": 2 }
    };
    const kReady: string = computeMemoryGraphDataKey({ activeSessionId: "ses-2", snap: s });
    const kLoading: string = computeMemoryGraphDataKey({
      activeSessionId: "ses-2",
      snap: { ...s, loadState: "loading" }
    });
    expect(kLoading).toBe(kReady);
    expect(kReady).not.toMatch(/n\d+/);
  });

  it("меняется при смене graphRevByNamespace", () => {
    const a: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: snapBase()
    });
    const b: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), graphRevByNamespace: { "ns-a": 4 } }
    });
    expect(a).not.toBe(b);
  });

  it("согласован с pagDatabasePresent: разные pd при остальном равном — разные ключи", () => {
    const a: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), pagDatabasePresent: false }
    });
    const b: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), pagDatabasePresent: true }
    });
    expect(a).not.toBe(b);
  });
});
