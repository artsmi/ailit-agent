import * as os from "node:os";
import * as path from "node:path";

/**
 * Соответствует `agent_core.runtime.paths.default_runtime_dir` (AILIT_RUNTIME_DIR, XDG_RUNTIME_DIR/ailit, ~/.ailit/runtime).
 */
export function defaultRuntimeDir(): string {
  const explicit: string | undefined = process.env["AILIT_RUNTIME_DIR"]?.trim();
  if (explicit) {
    return path.resolve(explicit);
  }
  const xdg: string | undefined = process.env["XDG_RUNTIME_DIR"]?.trim();
  if (xdg) {
    return path.join(xdg, "ailit");
  }
  return path.join(os.homedir(), ".ailit", "runtime");
}

export function safeChatIdForTraceFile(chatId: string): string {
  return Array.from(chatId)
    .filter((c) => /[A-Za-z0-9_-]/.test(c))
    .join("");
}

export function traceJsonlPath(params: { readonly runtimeDir: string; readonly chatId: string }): string {
  const safe: string = safeChatIdForTraceFile(params.chatId);
  return path.join(params.runtimeDir, "trace", `trace-${safe}.jsonl`);
}

export function supervisorSocketPath(runtimeDir: string): string {
  return path.join(runtimeDir, "supervisor.sock");
}
