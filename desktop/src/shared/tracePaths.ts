/**
 * Пути trace/runtime — совпадают с `desktop/src/main/defaultRuntimeDir.ts` (без node:fs).
 */
export function safeChatIdForTraceFile(chatId: string): string {
  return Array.from(chatId)
    .filter((c) => /[A-Za-z0-9_-]/.test(c))
    .join("");
}

export function traceJsonlFileName(chatId: string): string {
  return `trace-${safeChatIdForTraceFile(chatId)}.jsonl`;
}

export function traceJsonlRelativePath(chatId: string): string {
  return `trace/${traceJsonlFileName(chatId)}`;
}

export function joinPosixPath(base: string, ...parts: string[]): string {
  const a: string = base.replace(/[/\\]+$/, "");
  const b: string = parts.map((p) => p.replace(/^[/\\]+|[/\\]+$/g, "")).filter(Boolean).join("/");
  return b ? `${a}/${b}` : a;
}
