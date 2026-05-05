import { describe, expect, it } from "vitest";

import {
  computeMemoryGraphDataKey,
  formatMemoryGraphNamespaceSetKey,
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

describe("memoryGraphDataKey (2.3 / задача 1.3, вариант A + OR-011)", () => {
  const nsA: string = formatMemoryGraphNamespaceSetKey(["ns-a"]);
  const nsAb: string = formatMemoryGraphNamespaceSetKey(["ns-a", "ns-b"]);

  it("индикатор A: нет n{count} в строке; одинаковый snap-контракт (без длины merged) даёт один ключ", () => {
    const s: MemoryGraphDataKeySnap = snapBase();
    const k: string = computeMemoryGraphDataKey({
      activeSessionId: "ses-1",
      namespaceSetKey: nsA,
      snap: s
    });
    expect(
      computeMemoryGraphDataKey({ activeSessionId: "ses-1", namespaceSetKey: nsA, snap: s })
    ).toBe(k);
    expect(k).not.toMatch(/n\d+/);
  });

  it("меняется только при error vs live (ready/loading/idle дают одну фазу)", () => {
    const liveKey: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsA,
      snap: { ...snapBase(), loadState: "ready" }
    });
    expect(
      computeMemoryGraphDataKey({
        activeSessionId: "x",
        namespaceSetKey: nsA,
        snap: { ...snapBase(), loadState: "loading" }
      })
    ).toBe(liveKey);
    expect(
      computeMemoryGraphDataKey({
        activeSessionId: "x",
        namespaceSetKey: nsA,
        snap: { ...snapBase(), loadState: "idle" }
      })
    ).toBe(liveKey);
    const errKey: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsA,
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
    const kReady: string = computeMemoryGraphDataKey({
      activeSessionId: "ses-2",
      namespaceSetKey: nsAb,
      snap: s
    });
    const kLoading: string = computeMemoryGraphDataKey({
      activeSessionId: "ses-2",
      namespaceSetKey: nsAb,
      snap: { ...s, loadState: "loading" }
    });
    expect(kLoading).toBe(kReady);
    expect(kReady).not.toMatch(/n\d+/);
  });

  it("OR-011: инкремент только graphRevByNamespace — ключ тот же (steady state)", () => {
    const a: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsA,
      snap: snapBase()
    });
    const b: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsA,
      snap: { ...snapBase(), graphRevByNamespace: { "ns-a": 4 } }
    });
    expect(a).toBe(b);
  });

  it("меняется при смене namespaceSetKey (набор выбранных NS)", () => {
    const a: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsA,
      snap: snapBase()
    });
    const b: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsAb,
      snap: snapBase()
    });
    expect(a).not.toBe(b);
  });

  it("согласован с pagDatabasePresent: разные pd при остальном равном — разные ключи", () => {
    const a: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsA,
      snap: { ...snapBase(), pagDatabasePresent: false }
    });
    const b: string = computeMemoryGraphDataKey({
      activeSessionId: "x",
      namespaceSetKey: nsA,
      snap: { ...snapBase(), pagDatabasePresent: true }
    });
    expect(a).not.toBe(b);
  });

  it("TC-VITEST-REMOUNT-01: последовательные rev для одного namespace — ключ не меняется", () => {
    const nsKey: string = formatMemoryGraphNamespaceSetKey(["ns-a"]);
    const prev: MemoryGraphDataKeySnap = {
      loadState: "ready",
      pagDatabasePresent: true,
      graphRevByNamespace: { "ns-a": 10 }
    };
    const next: MemoryGraphDataKeySnap = {
      ...prev,
      graphRevByNamespace: { "ns-a": 11 }
    };
    const kPrev: string = computeMemoryGraphDataKey({
      activeSessionId: "session-z",
      namespaceSetKey: nsKey,
      snap: prev
    });
    const kNext: string = computeMemoryGraphDataKey({
      activeSessionId: "session-z",
      namespaceSetKey: nsKey,
      snap: next
    });
    expect(kNext).toBe(kPrev);
  });

  it("TC-VITEST-REMOUNT-02: missing_db → ready (pagDatabasePresent) — ключ меняется", () => {
    const nsKey: string = formatMemoryGraphNamespaceSetKey(["ns-a"]);
    const missingDb: MemoryGraphDataKeySnap = {
      loadState: "ready",
      pagDatabasePresent: false,
      graphRevByNamespace: { "ns-a": 0 }
    };
    const ready: MemoryGraphDataKeySnap = {
      ...missingDb,
      pagDatabasePresent: true
    };
    const kMissing: string = computeMemoryGraphDataKey({
      activeSessionId: "session-db",
      namespaceSetKey: nsKey,
      snap: missingDb
    });
    const kReady: string = computeMemoryGraphDataKey({
      activeSessionId: "session-db",
      namespaceSetKey: nsKey,
      snap: ready
    });
    expect(kReady).not.toBe(kMissing);
  });
});
