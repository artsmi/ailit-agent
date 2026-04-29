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

/** Журнал UI/чата для диагностики (append-only, одна сессия = один файл). */
export function desktopDiagnosticLogFileName(chatId: string): string {
  return `desk-diagnostic-${safeChatIdForTraceFile(chatId)}.log`;
}

export function desktopDiagnosticLogRelativePath(chatId: string): string {
  return `session/${desktopDiagnosticLogFileName(chatId)}`;
}

export function joinPosixPath(base: string, ...parts: string[]): string {
  const a: string = base.replace(/[/\\]+$/, "");
  const b: string = parts.map((p) => p.replace(/^[/\\]+|[/\\]+$/g, "")).filter(Boolean).join("/");
  return b ? `${a}/${b}` : a;
}

/** `~/.ailit/agent-memory/chat_logs/<safe_chat>.log` (home — абсолютный путь). */
export function agentMemoryChatLogFileName(chatId: string): string {
  return `${safeChatIdForTraceFile(chatId)}.log`;
}

export function agentMemoryChatLogAbsolutePath(homeDir: string, chatId: string): string {
  return joinPosixPath(homeDir, ".ailit", "agent-memory", "chat_logs", agentMemoryChatLogFileName(chatId));
}
