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

/** Полный лог trace + D-событий в renderer (append-only). */
export function desktopAilitFullLogFileName(): string {
  return "ailit-desktop-full.log";
}

/** Компактный лог той же сессии (append-only). */
export function desktopAilitCompactLogFileName(): string {
  return "ailit-desktop-compact.log";
}

/**
 * Каталог сессии чата под корнем AgentMemory chat_logs (для отображения путей).
 * Корень резолвит main через ``AILIT_AGENT_MEMORY_CHAT_LOG_DIR`` или ``~/.ailit/agent-memory/chat_logs``.
 */
export function agentMemoryChatLogSessionDirPosix(chatLogsRoot: string, chatId: string): string {
  const safe: string = safeChatIdForTraceFile(chatId);
  return joinPosixPath(chatLogsRoot, safe);
}

export function desktopAilitFullLogAbsolutePathPosix(chatLogsRoot: string, chatId: string): string {
  return joinPosixPath(agentMemoryChatLogSessionDirPosix(chatLogsRoot, chatId), desktopAilitFullLogFileName());
}

export function desktopAilitCompactLogAbsolutePathPosix(chatLogsRoot: string, chatId: string): string {
  return joinPosixPath(agentMemoryChatLogSessionDirPosix(chatLogsRoot, chatId), desktopAilitCompactLogFileName());
}

export function agentMemoryVerboseLogAbsolutePathPosix(chatLogsRoot: string, chatId: string): string {
  return joinPosixPath(agentMemoryChatLogSessionDirPosix(chatLogsRoot, chatId), agentMemoryChatLogFileName(chatId));
}

export function joinPosixPath(base: string, ...parts: string[]): string {
  const a: string = base.replace(/[/\\]+$/, "");
  const b: string = parts.map((p) => p.replace(/^[/\\]+|[/\\]+$/g, "")).filter(Boolean).join("/");
  return b ? `${a}/${b}` : a;
}

/** Имя verbose-лога AgentMemory: ``<safe_chat>.log`` внутри каталога сессии. */
export function agentMemoryChatLogFileName(chatId: string): string {
  return `${safeChatIdForTraceFile(chatId)}.log`;
}
