const NS_PLACEHOLDER = "\u2063";

function escapeNsForRevMismatchMessage(namespace: string): string {
  return namespace.replace(/»/g, NS_PLACEHOLDER);
}

function unescapeNsForRevMismatchMessage(fragment: string): string {
  return fragment.replace(new RegExp(NS_PLACEHOLDER, "g"), "»");
}

export function formatPagGraphRevMismatchWarning(
  namespace: string,
  expectedNextRev: number,
  traceRev: number
): string {
  const safeNs: string = escapeNsForRevMismatchMessage(namespace);
  return (
    `PAG: несоответствие graph rev (ожидается ${String(expectedNextRev)}, в trace ${String(traceRev)}) ` +
    `для «${safeNs}». Выполните Refresh.`
  );
}

export function pagGraphRevMismatchDedupeKey(
  namespace: string,
  expectedNextRev: number,
  traceRev: number
): string {
  return `${namespace}\u001f${String(expectedNextRev)}\u001f${String(traceRev)}`;
}

const REV_MISMATCH_WITH_NS_RE: RegExp =
  /^PAG: несоответствие graph rev \(ожидается (\d+), в trace (\d+)\) для «([^»]*)»\. Выполните Refresh\.$/;

const REV_MISMATCH_LEGACY_RE: RegExp =
  /^PAG: несоответствие graph rev \(ожидается (\d+), в trace (\d+)\)\. Выполните Refresh\.$/;

export function parsePagGraphRevMismatchWarning(
  warning: string
): { readonly namespace: string; readonly expectedNextRev: number; readonly traceRev: number } | null {
  const mNs: RegExpMatchArray | null = warning.match(REV_MISMATCH_WITH_NS_RE);
  if (mNs !== null) {
    const ns: string = unescapeNsForRevMismatchMessage(mNs[3] ?? "");
    return {
      namespace: ns,
      expectedNextRev: Number(mNs[1]),
      traceRev: Number(mNs[2])
    };
  }
  const mLegacy: RegExpMatchArray | null = warning.match(REV_MISMATCH_LEGACY_RE);
  if (mLegacy !== null) {
    return {
      namespace: "",
      expectedNextRev: Number(mLegacy[1]),
      traceRev: Number(mLegacy[2])
    };
  }
  return null;
}

export function tryParsePagGraphRevMismatchDedupeKey(warning: string): string | null {
  const mNs: RegExpMatchArray | null = warning.match(REV_MISMATCH_WITH_NS_RE);
  if (mNs !== null) {
    const ns: string = unescapeNsForRevMismatchMessage(mNs[3] ?? "");
    return pagGraphRevMismatchDedupeKey(ns, Number(mNs[1]), Number(mNs[2]));
  }
  const mLegacy: RegExpMatchArray | null = warning.match(REV_MISMATCH_LEGACY_RE);
  if (mLegacy !== null) {
    return pagGraphRevMismatchDedupeKey("", Number(mLegacy[1]), Number(mLegacy[2]));
  }
  return null;
}

export function dedupePagGraphSnapshotWarnings(warnings: readonly string[]): readonly string[] {
  const seenRevKeys: Set<string> = new Set();
  const seenOther: Set<string> = new Set();
  const out: string[] = [];
  for (const w of warnings) {
    const rk: string | null = tryParsePagGraphRevMismatchDedupeKey(w);
    if (rk !== null) {
      if (seenRevKeys.has(rk)) {
        continue;
      }
      seenRevKeys.add(rk);
      out.push(w);
      continue;
    }
    if (seenOther.has(w)) {
      continue;
    }
    seenOther.add(w);
    out.push(w);
  }
  return out;
}

function namespaceFromRevMismatchDedupeKey(rk: string): string {
  const i: number = rk.indexOf("\u001f");
  return i < 0 ? "" : rk.slice(0, i);
}

/**
 * Снять rev-mismatch строки, устаревшие относительно текущего `graphRevByNamespace`
 * (trace-rev из предупреждения уже «вошёл» в согласованный rev).
 */
export function reconcileStalePagGraphRevMismatchWarnings(
  warnings: readonly string[],
  revs: Readonly<Record<string, number>>,
  namespaces: Readonly<Set<string>>
): readonly string[] {
  const out: string[] = [];
  for (const w of warnings) {
    const rk: string | null = tryParsePagGraphRevMismatchDedupeKey(w);
    if (rk === null) {
      out.push(w);
      continue;
    }
    const ns: string = namespaceFromRevMismatchDedupeKey(rk);
    if (!namespaces.has(ns)) {
      out.push(w);
      continue;
    }
    const parts: string[] = rk.split("\u001f");
    const expectedNextStr: string | undefined = parts.length >= 2 ? parts[1] : undefined;
    const traceRevStr: string | undefined = parts.length >= 3 ? parts[2] : undefined;
    const expectedNextRev: number = expectedNextStr != null ? Number(expectedNextStr) : Number.NaN;
    const traceRev: number = traceRevStr != null ? Number(traceRevStr) : Number.NaN;
    if (!Number.isFinite(traceRev) || !Number.isFinite(expectedNextRev)) {
      out.push(w);
      continue;
    }
    const cur: number = revs[ns] ?? 0;
    if (cur > traceRev) {
      continue;
    }
    if (cur === traceRev && traceRev - expectedNextRev >= 2) {
      continue;
    }
    out.push(w);
  }
  return out;
}

/**
 * UC-03 Н2: не более одного rev-mismatch на namespace — оставляем последнее по порядку списка.
 */
export function collapsePagGraphRevMismatchWarningsToLatestPerNamespace(
  warnings: readonly string[]
): readonly string[] {
  const revLastByNs: Map<string, string> = new Map();
  const revNsOrder: string[] = [];
  const nonRev: string[] = [];
  for (const w of warnings) {
    const rk: string | null = tryParsePagGraphRevMismatchDedupeKey(w);
    if (rk === null) {
      nonRev.push(w);
      continue;
    }
    const ns: string = namespaceFromRevMismatchDedupeKey(rk);
    if (!revLastByNs.has(ns)) {
      revNsOrder.push(ns);
    }
    revLastByNs.set(ns, w);
  }
  const collapsed: string[] = revNsOrder.map((ns: string) => revLastByNs.get(ns)!);
  return [...nonRev, ...collapsed];
}
