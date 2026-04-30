/**
 * Сериализация rev для `graphDataKey` (3D) — **без** числа нод; индикатор 2.3 (вариант A):
 * ключ **не** должен отличаться только +1 нодой при стабильном rev/сессии/pagDatabasePresent.
 */
export function formatGraphRevByNamespaceKey(
  graphRevByNamespace: Readonly<Record<string, number>> | undefined
): string {
  if (graphRevByNamespace == null) {
    return "";
  }
  return Object.entries(graphRevByNamespace)
    .map(([k, v]) => `${k}:${String(v)}`)
    .sort()
    .join("|");
}

export type MemoryGraphDataKeySnap = {
  readonly loadState: "idle" | "loading" | "ready" | "error";
  readonly pagDatabasePresent: boolean;
  readonly graphRevByNamespace: Readonly<Record<string, number>>;
};

/**
 * Ключ `ForceGraph3D` (remount / WebGL) — **не** включает `merged.nodes.length`.
 * См. `architecture.md` §2.3, задача 1.3.
 */
export function computeMemoryGraphDataKey(p: {
  readonly activeSessionId: string;
  /** `null` — PAG-граф ещё не в store для активного session. */
  readonly snap: MemoryGraphDataKeySnap | null;
}): string {
  if (p.snap == null) {
    return `${p.activeSessionId}-none-pdx-`;
  }
  const st: string = p.snap.loadState;
  const pd: string = p.snap.pagDatabasePresent ? "1" : "0";
  const rev: string = formatGraphRevByNamespaceKey(p.snap.graphRevByNamespace);
  return `${p.activeSessionId}-${st}-pd${pd}-${rev}`;
}
