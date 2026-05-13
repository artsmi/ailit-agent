import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { parse as parseYaml } from "yaml";

/**
 * Путь к ``~/.ailit/agent-memory/config.yaml`` или ``AILIT_AGENT_MEMORY_CONFIG``
 * (согласовано с ``AgentMemoryConfigPaths.default_file_path`` в Python).
 */
export function resolveAgentMemoryConfigYamlPath(): string {
  const ex: string | undefined = process.env["AILIT_AGENT_MEMORY_CONFIG"]?.trim();
  if (ex) {
    return path.resolve(expandTildePrefix(ex));
  }
  return path.resolve(os.homedir(), ".ailit", "agent-memory", "config.yaml");
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

function coerceYamlBool(raw: unknown, defaultVal: boolean): boolean {
  if (raw === undefined || raw === null) {
    return defaultVal;
  }
  if (typeof raw === "boolean") {
    return raw;
  }
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw !== 0;
  }
  if (typeof raw === "string") {
    const s: string = raw.trim().toLowerCase();
    if (["0", "false", "no", "off", "n"].includes(s)) {
      return false;
    }
    if (["1", "true", "yes", "on", "y"].includes(s)) {
      return true;
    }
  }
  return defaultVal;
}

function extractChatLogsEnabled(doc: unknown): boolean {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    return true;
  }
  const root: Record<string, unknown> = doc as Record<string, unknown>;
  const mem: unknown = root["memory"];
  if (!mem || typeof mem !== "object" || Array.isArray(mem)) {
    return true;
  }
  const debug: unknown = (mem as Record<string, unknown>)["debug"];
  if (!debug || typeof debug !== "object" || Array.isArray(debug)) {
    return true;
  }
  const raw: unknown = (debug as Record<string, unknown>)["chat_logs_enabled"];
  return coerceYamlBool(raw, true);
}

let cachedMtimeMs: number | null = null;
let cachedChatLogsEnabled: boolean | null = null;

/**
 * ``memory.debug.chat_logs_enabled`` из agent-memory config (default ``true``).
 * Кэш по ``mtimeMs``; при отсутствии файла / ошибке чтения — ``true``.
 */
export function readAgentMemoryChatLogsEnabled(): boolean {
  const cfgPath: string = resolveAgentMemoryConfigYamlPath();
  try {
    const st: fs.Stats = fs.statSync(cfgPath);
    if (cachedMtimeMs === st.mtimeMs && cachedChatLogsEnabled !== null) {
      return cachedChatLogsEnabled;
    }
    const text: string = fs.readFileSync(cfgPath, "utf8");
    const doc: unknown = parseYaml(text) as unknown;
    const enabled: boolean = extractChatLogsEnabled(doc);
    cachedMtimeMs = st.mtimeMs;
    cachedChatLogsEnabled = enabled;
    return enabled;
  } catch {
    cachedMtimeMs = null;
    cachedChatLogsEnabled = true;
    return true;
  }
}
