import type { PagSearchHighlightV1 } from "./pagHighlightFromTrace";

function stringArraysShallowEqual(
  a: readonly string[] | undefined,
  b: readonly string[] | undefined
): boolean {
  if (a === b) {
    return true;
  }
  if (a === undefined || b === undefined) {
    return a === b;
  }
  if (a.length !== b.length) {
    return false;
  }
  for (let i: number = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) {
      return false;
    }
  }
  return true;
}

/**
 * UC-02 / architecture §4.3 — визуальная эквивалентность glow для одного namespace.
 *
 * Два значения считаются равными, если оба `null`, либо оба non-null и совпадают
 * `nodeIds`/`edgeIds` (по ссылке или поэлементно в том же порядке), `ttlMs`, `reason`,
 * `intensity`, `queryId`, а также `kind` и `namespace` как часть DTO.
 */
export function pagSearchHighlightShallowEqualForGlow(
  h1: PagSearchHighlightV1 | null,
  h2: PagSearchHighlightV1 | null
): boolean {
  if (h1 === h2) {
    return true;
  }
  if (h1 === null || h2 === null) {
    return false;
  }
  return (
    h1.kind === h2.kind &&
    h1.namespace === h2.namespace &&
    h1.ttlMs === h2.ttlMs &&
    h1.reason === h2.reason &&
    h1.intensity === h2.intensity &&
    h1.queryId === h2.queryId &&
    stringArraysShallowEqual(h1.nodeIds, h2.nodeIds) &&
    stringArraysShallowEqual(h1.edgeIds, h2.edgeIds)
  );
}
