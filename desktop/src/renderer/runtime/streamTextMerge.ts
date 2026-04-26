/**
 * Слияние фрагментов стрима: провайдеры шлют кумулятив, дельту или
 * куски с перекрытием. Сравнение/накопление ведём в Unicode NFC.
 */

function toNfc(s: string): string {
  return s.normalize("NFC");
}

/**
 * Слияние накопленного текста `prev` и пришедшего `chunk`.
 * Результат в NFC — для стабильного merge при следующей дельте.
 */
export function mergeStreamText(prev: string, chunk: string): string {
  const p: string = toNfc(prev);
  const c: string = toNfc(chunk);
  if (c.length === 0) {
    return p;
  }
  if (p.length === 0) {
    return c;
  }
  if (c.startsWith(p)) {
    return c;
  }
  if (p.startsWith(c)) {
    return p;
  }
  const maxK: number = Math.min(p.length, c.length) - 1;
  const minLen: number = Math.min(p.length, c.length);
  for (let k: number = maxK; k >= 1; k -= 1) {
    if (p.slice(-k) !== c.slice(0, k)) {
      continue;
    }
    if (k === 1 && minLen > 3) {
      continue;
    }
    if (k === c.length) {
      return p;
    }
    if (k === p.length) {
      return c;
    }
    return p + c.slice(k);
  }
  return p + c;
}
