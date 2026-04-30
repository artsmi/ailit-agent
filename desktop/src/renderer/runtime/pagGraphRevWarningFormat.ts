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
