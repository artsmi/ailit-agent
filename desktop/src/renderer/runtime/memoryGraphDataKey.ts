/**
 * Сериализация rev (PAG / observability) — **не** входит в React key `ForceGraph3D` (OR-011).
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

/**
 * Каноническая подпись **набора** namespace для ключа графа (порядок выбора в UI не важен).
 */
export function formatMemoryGraphNamespaceSetKey(namespaces: readonly string[]): string {
  const uniq: string[] = [];
  for (const n of namespaces) {
    if (n.length === 0) {
      continue;
    }
    if (!uniq.includes(n)) {
      uniq.push(n);
    }
  }
  uniq.sort();
  return uniq.join("|");
}

export type MemoryGraphDataKeySnap = {
  readonly loadState: "idle" | "loading" | "ready" | "error";
  readonly pagDatabasePresent: boolean;
  /**
   * В снимке PAG остаётся для контракта тестов/данных; **не** участвует в строке ключа (OR-011).
   */
  readonly graphRevByNamespace: Readonly<Record<string, number>>;
};

/**
 * Remount triggers (`ForceGraph3D` React `key` / `graphDataKey`):
 *
 * - смена `activeSessionId`;
 * - смена набора выбранных namespace (`namespaceSetKey`, порядок не важен);
 * - смена фазы загрузки: `error` vs «live» (`idle`/`loading`/`ready` дают одну фазу — задача 3.1);
 * - смена `pagDatabasePresent` (в т.ч. missing_db → ready / появление SQLite PAG).
 *
 * Не триггер: монотонный инкремент `graphRevByNamespace` при том же session, том же
 * `namespaceSetKey`, той же фазе и том же `pagDatabasePresent` (steady state / дельты).
 */

/**
 * Фаза загрузки для ключа remount: `idle`/`loading`/`ready` не различаются (задача 3.1),
 * чтобы refresh PAG не дергал `ForceGraph3D` при той же фазе / `pagDatabasePresent` / наборе NS.
 */
export type MemoryGraphDataKeyLoadPhase = "error" | "live";

export function graphLoadPhaseForDataKey(
  loadState: MemoryGraphDataKeySnap["loadState"]
): MemoryGraphDataKeyLoadPhase {
  return loadState === "error" ? "error" : "live";
}

/**
 * Ключ `ForceGraph3D` (remount / WebGL) — **не** включает `merged.nodes.length`
 * и **не** включает значения `graphRevByNamespace` (OR-011).
 * Сегмент фазы — `live`/`error` (не сырой `loadState`), см. задачу 3.1.
 */
export function computeMemoryGraphDataKey(p: {
  readonly activeSessionId: string;
  /**
   * Подпись набора namespace из UI (`formatMemoryGraphNamespaceSetKey(namespaces)` в `MemoryGraph3DPage`).
   */
  readonly namespaceSetKey: string;
  /** `null` — PAG-граф ещё не в store для активного session. */
  readonly snap: MemoryGraphDataKeySnap | null;
}): string {
  const nsSeg: string = p.namespaceSetKey.length > 0 ? p.namespaceSetKey : "_";
  if (p.snap == null) {
    return `${p.activeSessionId}-ns${nsSeg}-none-pdx-`;
  }
  const phase: MemoryGraphDataKeyLoadPhase = graphLoadPhaseForDataKey(p.snap.loadState);
  const pd: string = p.snap.pagDatabasePresent ? "1" : "0";
  return `${p.activeSessionId}-ns${nsSeg}-${phase}-pd${pd}`;
}
