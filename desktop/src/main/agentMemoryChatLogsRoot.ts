import * as os from "node:os";
import * as path from "node:path";

import { safeChatIdForTraceFile } from "./defaultRuntimeDir";

/**
 * Согласовано с ``agent_memory_chat_log.default_chat_logs_dir``:
 * ``AILIT_AGENT_MEMORY_CHAT_LOG_DIR`` (env) или ``~/.ailit/agent-memory/chat_logs``.
 */
export function resolveAgentMemoryChatLogsRoot(): string {
  const ex: string | undefined = process.env["AILIT_AGENT_MEMORY_CHAT_LOG_DIR"]?.trim();
  if (ex) {
    const expanded: string = expandTildePrefix(ex);
    return path.resolve(expanded);
  }
  return path.resolve(os.homedir(), ".ailit", "agent-memory", "chat_logs");
}

function expandTildePrefix(raw: string): string {
  const t: string = raw.trim();
  if (t === "~") {
    return os.homedir();
  }
  if (t.startsWith("~/") || t.startsWith("~\\")) {
    return path.join(os.homedir(), t.slice(2));
  }
  return t;
}

export type ChatLogSessionPaths = {
  readonly root: string;
  readonly sessionDir: string;
  readonly safeChatId: string;
};

/**
 * Каталог сессии: ``<chat_logs_root>/<safe_chat_id>/`` (оба пути absolute, resolved).
 */
export function resolveChatLogSessionPaths(chatId: string): { readonly ok: true; readonly paths: ChatLogSessionPaths } | { readonly ok: false; readonly error: string } {
  const safeChatId: string = safeChatIdForTraceFile(chatId);
  if (!safeChatId) {
    return { ok: false, error: "invalid chatId" };
  }
  const root: string = resolveAgentMemoryChatLogsRoot();
  const sessionDir: string = path.resolve(path.join(root, safeChatId));
  const rootPrefix: string = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (sessionDir !== root && !sessionDir.startsWith(rootPrefix)) {
    return { ok: false, error: "session dir outside chat_logs root" };
  }
  return { ok: true, paths: { root, sessionDir, safeChatId } };
}
