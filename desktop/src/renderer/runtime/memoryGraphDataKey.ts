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
 * Фаза загрузки для ключа remount: `idle`/`loading`/`ready` не различаются (задача 3.1),
 * чтобы refresh PAG не дергал `ForceGraph3D` при том же `graphRevByNamespace` / `pd`.
 */
export type MemoryGraphDataKeyLoadPhase = "error" | "live";

export function graphLoadPhaseForDataKey(
  loadState: MemoryGraphDataKeySnap["loadState"]
): MemoryGraphDataKeyLoadPhase {
  return loadState === "error" ? "error" : "live";
}

/**
 * Ключ `ForceGraph3D` (remount / WebGL) — **не** включает `merged.nodes.length`.
 * Сегмент фазы — `live`/`error` (не сырой `loadState`), см. задачу 3.1.
 */
export function computeMemoryGraphDataKey(p: {
  readonly activeSessionId: string;
  /** `null` — PAG-граф ещё не в store для активного session. */
  readonly snap: MemoryGraphDataKeySnap | null;
}): string {
  if (p.snap == null) {
    return `${p.activeSessionId}-none-pdx-`;
  }
  const phase: MemoryGraphDataKeyLoadPhase = graphLoadPhaseForDataKey(p.snap.loadState);
  const pd: string = p.snap.pagDatabasePresent ? "1" : "0";
  const rev: string = formatGraphRevByNamespaceKey(p.snap.graphRevByNamespace);
  return `${p.activeSessionId}-${phase}-pd${pd}-${rev}`;
}
