/**
 * Слияние фрагментов стрима: провайдеры иногда шлют кумулятивный снимок вместо дельты.
 */
export function mergeStreamText(prev: string, chunk: string): string {
  if (chunk.length === 0) {
    return prev;
  }
  if (prev.length === 0) {
    return chunk;
  }
  if (chunk.startsWith(prev)) {
    return chunk;
  }
  if (prev.startsWith(chunk)) {
    return prev;
  }
  return prev + chunk;
}
