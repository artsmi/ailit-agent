import { describe, expect, it } from "vitest";

import { computeMemoryGraphDataKey, type MemoryGraphDataKeySnap } from "./memoryGraphDataKey";

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

  it("меняется при смене loadState (hard error и т.п.)", () => {
    const a: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), loadState: "ready" }
    });
    const b: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      snap: { ...snapBase(), loadState: "error" }
    });
    expect(a).not.toBe(b);
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
