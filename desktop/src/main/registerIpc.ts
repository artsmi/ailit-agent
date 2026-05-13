import { BrowserWindow, dialog, ipcMain, type IpcMainInvokeEvent } from "electron";
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import { brokerJsonRequest } from "./brokerSocket";
import { getCachedDesktopConfigSnapshot, warmDesktopConfigCache } from "./desktopConfig";
import { resolveAgentMemoryChatLogsRoot, resolveChatLogSessionPaths } from "./agentMemoryChatLogsRoot";
import { defaultRuntimeDir, safeChatIdForTraceFile, supervisorSocketPath } from "./defaultRuntimeDir";
import { listProjectRegistry } from "./projectRegistryBridge";
import { runPagGraphSlice, type PagGraphSliceResult } from "./pagGraphBridge";
import { readDurableTraceRows } from "./readTraceJsonl";
import { supervisorJsonRequest } from "./supervisorSocket";
import { traceSubscribe, traceUnsubscribe } from "./traceSocketPool";
import type { SupervisorCreateOrGetBrokerParams } from "../shared/ipc";

function asRecord(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

/** Согласовано с renderer `desktopGraphPairLogWriter` (bounded stderr / FS message). */
const MAIN_COMPACT_OBS_ERROR_MAX_CHARS: number = 400;

function compactMainIpcObsErrorMessage(raw: string): string {
  const collapsed: string = raw.replace(/\s+/g, " ").trim();
  if (collapsed.length <= MAIN_COMPACT_OBS_ERROR_MAX_CHARS) {
    return collapsed;
  }
  return `${collapsed.slice(0, MAIN_COMPACT_OBS_ERROR_MAX_CHARS)}…`;
}

function logDesktopPagSliceRequested(p: {
  readonly isoTimestamp: string;
  readonly namespace: string;
  readonly dbPathSet: boolean;
  readonly level: string | null;
  readonly nodeLimit: number;
  readonly nodeOffset: number;
  readonly edgeLimit: number;
  readonly edgeOffset: number;
}): void {
  const ns: string = p.namespace.replace(/\s+/g, " ").trim();
  const lvl: string = p.level === null || p.level === "" ? "null" : p.level.replace(/\s+/g, " ").trim();
  console.info(
    `timestamp=${p.isoTimestamp}\tevent=desktop.pag_slice.requested\t` +
      `namespace=${ns}\tdb_path_set=${p.dbPathSet ? "true" : "false"}\tlevel=${lvl}\t` +
      `node_limit=${String(p.nodeLimit)}\tnode_offset=${String(p.nodeOffset)}\t` +
      `edge_limit=${String(p.edgeLimit)}\tedge_offset=${String(p.edgeOffset)}`
  );
}

function logDesktopPagSliceCompleted(p: {
  readonly isoTimestamp: string;
  readonly durationMs: number;
  readonly nodeCount: number;
  readonly edgeCount: number;
  readonly hasMoreNodes: boolean;
  readonly hasMoreEdges: boolean;
}): void {
  console.info(
    `timestamp=${p.isoTimestamp}\tevent=desktop.pag_slice.completed\t` +
      `duration_ms=${String(p.durationMs)}\tnode_count=${String(p.nodeCount)}\t` +
      `edge_count=${String(p.edgeCount)}\t` +
      `has_more_nodes=${p.hasMoreNodes ? "true" : "false"}\t` +
      `has_more_edges=${p.hasMoreEdges ? "true" : "false"}`
  );
}

function logDesktopPagSliceError(p: {
  readonly isoTimestamp: string;
  readonly durationMs: number;
  readonly errorCode: string;
  readonly errorMessage: string;
}): void {
  console.warn(
    `timestamp=${p.isoTimestamp}\tevent=desktop.pag_slice.error\t` +
      `duration_ms=${String(p.durationMs)}\terror_code=${p.errorCode}\t` +
      `error=${compactMainIpcObsErrorMessage(p.errorMessage)}`
  );
}

function logDesktopPairlogAppendMainFailed(p: {
  readonly isoTimestamp: string;
  readonly chatId: string;
  readonly errorMessage: string;
}): void {
  const chat: string = p.chatId.replace(/\s+/g, " ").trim();
  console.warn(
    `timestamp=${p.isoTimestamp}\tevent=desktop.pairlog.append_failed\t` +
      `source=main_ipc\tchat_id=${chat}\terror=${compactMainIpcObsErrorMessage(p.errorMessage)}`
  );
}

function broadcastTraceRow(chatId: string, row: Record<string, unknown>): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send("ailit:traceRow", { chatId, row });
  }
}

export function registerIpcHandlers(): void {
  warmDesktopConfigCache();

  ipcMain.handle("ailit:ping", async () => "pong");
  ipcMain.handle("ailit:homeDir", async () => os.homedir());
  ipcMain.handle("ailit:getDesktopConfigSnapshot", async () => getCachedDesktopConfigSnapshot());

  ipcMain.handle("ailit:supervisorStatus", async () => {
    const runtimeDir: string = defaultRuntimeDir();
    const sock: string = supervisorSocketPath(runtimeDir);
    try {
      const st = await fs.stat(sock);
      if (typeof st.isSocket === "function" && !st.isSocket()) {
        return { ok: false, error: "supervisor path is not a unix socket" };
      }
    } catch {
      return {
        ok: false,
        error:
          "supervisor socket не найден. Проверьте: ailit runtime supervisor, systemctl --user status ailit.service"
      };
    }
    try {
      const raw: unknown = await supervisorJsonRequest({
        socketPath: sock,
        request: { cmd: "status" },
        timeoutMs: 2000
      });
      return raw;
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  });

  ipcMain.handle("ailit:supervisorBrokers", async () => {
    const runtimeDir: string = defaultRuntimeDir();
    const sock: string = supervisorSocketPath(runtimeDir);
    try {
      const raw: unknown = await supervisorJsonRequest({
        socketPath: sock,
        request: { cmd: "brokers" },
        timeoutMs: 2000
      });
      return raw;
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  });

  ipcMain.handle(
    "ailit:supervisorCreateOrGetBroker",
    async (_e: unknown, params: SupervisorCreateOrGetBrokerParams) => {
      const runtimeDir: string = defaultRuntimeDir();
      const sock: string = supervisorSocketPath(runtimeDir);
      try {
        const raw: unknown = await supervisorJsonRequest({
          socketPath: sock,
          request: {
            cmd: "create_or_get_broker",
            chat_id: params.chatId,
            primary_namespace: params.primaryNamespace,
            primary_project_root: params.primaryProjectRoot,
            workspace: params.workspace.map((e) => ({
              namespace: e.namespace,
              project_root: e.projectRoot
            }))
          },
          timeoutMs: 5000
        });
        return raw;
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    }
  );

  ipcMain.handle("ailit:supervisorStopBroker", async (_e: unknown, params: { readonly chatId: string }) => {
    const runtimeDir: string = defaultRuntimeDir();
    const sock: string = supervisorSocketPath(runtimeDir);
    try {
      const raw: unknown = await supervisorJsonRequest({
        socketPath: sock,
        request: { cmd: "stop_broker", chat_id: params.chatId },
        timeoutMs: 5000
      });
      return raw;
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  });

  /**
   * Cooperative Stop (UC-05, plan.md волна 4): renderer шлёт JSON-line в broker-сокет
   * через этот же handler. Операция `runtime.cancel_active_turn` — `service.request`
   * на `AgentWork:<chat_id>` с payload `{ action, chat_id, user_turn_id }` (см.
   * `context/proto/desktop-electron-runtime-bridge.md`). Повторный Stop идемпотентен
   * на стороне UI (`DesktopSessionContext`); broker должен принять повторный cancel.
   */
  ipcMain.handle(
    "ailit:brokerRequest",
    async (_e: unknown, params: { readonly endpoint: string; readonly request: Record<string, unknown> }) => {
      try {
        const line: string = JSON.stringify(params.request);
        const raw: unknown = await brokerJsonRequest({
          endpoint: params.endpoint,
          line,
          timeoutMs: 30_000
        });
        const rec = asRecord(raw);
        if (rec) {
          return { ok: true, response: rec as never };
        }
        return { ok: false, error: "empty broker response" };
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    }
  );

  ipcMain.handle(
    "ailit:traceReadDurable",
    async (_e: unknown, params: { readonly runtimeDir: string; readonly chatId: string }) => {
      return readDurableTraceRows(params);
    }
  );

  ipcMain.handle(
    "ailit:appendTraceRow",
    async (_e: unknown, params: {
      readonly runtimeDir: string;
      readonly chatId: string;
      readonly row: Record<string, unknown>;
    }) => {
      try {
        const p: string = path.join(
          params.runtimeDir,
          "trace",
          `trace-${safeChatIdForTraceFile(params.chatId)}.jsonl`
        );
        await fs.mkdir(path.dirname(p), { recursive: true });
        await fs.appendFile(p, `${JSON.stringify(params.row)}\n`, "utf8");
        broadcastTraceRow(params.chatId, params.row);
        return { ok: true, row: params.row };
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    }
  );

  ipcMain.handle(
    "ailit:traceSubscribe",
    async (_e: unknown, params: { readonly chatId: string; readonly endpoint: string }) => {
      try {
        return traceSubscribe(params);
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    }
  );

  ipcMain.handle("ailit:traceUnsubscribe", async (_e: unknown, params: { readonly chatId: string }) => {
    traceUnsubscribe(params.chatId);
    return { ok: true };
  });

  ipcMain.handle("ailit:projectRegistryList", async (_e: unknown, params: { readonly startPath?: string }) => {
    return listProjectRegistry(params.startPath);
  });

  ipcMain.handle(
    "ailit:pagGraphSlice",
    async (
      _e: unknown,
      params: {
        readonly namespace: string;
        readonly dbPath?: string;
        readonly level: string | null;
        readonly nodeLimit: number;
        readonly nodeOffset: number;
        readonly edgeLimit: number;
        readonly edgeOffset: number;
      }
    ): Promise<PagGraphSliceResult> => {
      const startedAtMs: number = Date.now();
      const requestedAt: string = new Date().toISOString();
      logDesktopPagSliceRequested({
        isoTimestamp: requestedAt,
        namespace: params.namespace,
        dbPathSet: Boolean(params.dbPath && params.dbPath.trim().length > 0),
        level: params.level,
        nodeLimit: params.nodeLimit,
        nodeOffset: params.nodeOffset,
        edgeLimit: params.edgeLimit,
        edgeOffset: params.edgeOffset
      });
      const result: PagGraphSliceResult = await runPagGraphSlice({
        namespace: params.namespace,
        dbPath: params.dbPath,
        level: params.level,
        nodeLimit: params.nodeLimit,
        nodeOffset: params.nodeOffset,
        edgeLimit: params.edgeLimit,
        edgeOffset: params.edgeOffset
      });
      const durationMs: number = Math.max(0, Date.now() - startedAtMs);
      const endedAt: string = new Date().toISOString();
      if (result.ok) {
        logDesktopPagSliceCompleted({
          isoTimestamp: endedAt,
          durationMs,
          nodeCount: result.nodes.length,
          edgeCount: result.edges.length,
          hasMoreNodes: result.has_more.nodes,
          hasMoreEdges: result.has_more.edges
        });
      } else {
        logDesktopPagSliceError({
          isoTimestamp: endedAt,
          durationMs,
          errorCode: result.code ?? "unknown",
          errorMessage: result.error
        });
      }
      return result;
    }
  );

  ipcMain.handle(
    "ailit:memoryJournalRead",
    async (
      _e: unknown,
      params: { readonly chatId: string; readonly limit?: number }
    ) => {
      const rawPath: string =
        process.env["AILIT_MEMORY_JOURNAL_PATH"]?.trim() ||
        path.join(os.homedir(), ".ailit", "runtime", "memory-journal.jsonl");
      const filePath: string = path.resolve(rawPath);
      const limit: number = Math.max(1, Math.min(Number(params.limit ?? 400), 2000));
      try {
        const txt: string = await fs.readFile(filePath, "utf8");
        const rows: Record<string, unknown>[] = [];
        for (const line of txt.split(/\r?\n/)) {
          const raw: string = line.trim();
          if (!raw) {
            continue;
          }
          try {
            const obj: unknown = JSON.parse(raw);
            if (
              obj &&
              typeof obj === "object" &&
              !Array.isArray(obj) &&
              String((obj as Record<string, unknown>)["chat_id"] ?? "") === params.chatId
            ) {
              rows.push(obj as Record<string, unknown>);
            }
          } catch {
            /* skip malformed journal lines in UI */
          }
        }
        return { ok: true, path: filePath, rows: rows.slice(-limit) } as const;
      } catch (e) {
        const code = (e as { code?: string }).code;
        if (code === "ENOENT") {
          return { ok: true, path: filePath, rows: [] } as const;
        }
        return { ok: false, error: e instanceof Error ? e.message : String(e) } as const;
      }
    }
  );

  ipcMain.handle("ailit:agentMemoryChatLogsRoot", async () => {
    return { ok: true, root: resolveAgentMemoryChatLogsRoot() } as const;
  });

  ipcMain.handle("ailit:ensureChatLogSessionDir", async (_e: unknown, params: { readonly chatId: string }) => {
    const resolved = resolveChatLogSessionPaths(params.chatId);
    if (!resolved.ok) {
      return { ok: false, error: resolved.error } as const;
    }
    const { root, sessionDir, safeChatId } = resolved.paths;
    try {
      await fs.mkdir(sessionDir, { recursive: true });
      return { ok: true, chatLogsRoot: root, sessionDir, safeChatId } as const;
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) } as const;
    }
  });

  ipcMain.handle(
    "ailit:appendDesktopGraphPairLog",
    async (
      _e: unknown,
      params: {
        readonly chatId: string;
        readonly entries: readonly { readonly fullRecord: string; readonly compactLine: string }[];
      }
    ) => {
      if (params.entries.length === 0) {
        return { ok: false, error: "no entries" } as const;
      }
      const resolved = resolveChatLogSessionPaths(params.chatId);
      if (!resolved.ok) {
        logDesktopPairlogAppendMainFailed({
          isoTimestamp: new Date().toISOString(),
          chatId: params.chatId,
          errorMessage: resolved.error
        });
        return { ok: false, error: resolved.error } as const;
      }
      const { sessionDir } = resolved.paths;
      const fullPath: string = path.resolve(path.join(sessionDir, "ailit-desktop-full.log"));
      const compactPath: string = path.resolve(path.join(sessionDir, "ailit-desktop-compact.log"));
      try {
        await fs.mkdir(sessionDir, { recursive: true });
        for (const e of params.entries) {
          const fr: string = e.fullRecord.endsWith("\n") ? e.fullRecord : `${e.fullRecord}\n`;
          const cl: string = e.compactLine.endsWith("\n") ? e.compactLine : `${e.compactLine}\n`;
          await fs.appendFile(fullPath, fr, "utf8");
          await fs.appendFile(compactPath, cl, "utf8");
        }
        return { ok: true, fullPath, compactPath } as const;
      } catch (e) {
        const errMsg: string = e instanceof Error ? e.message : String(e);
        logDesktopPairlogAppendMainFailed({
          isoTimestamp: new Date().toISOString(),
          chatId: params.chatId,
          errorMessage: errMsg
        });
        return { ok: false, error: errMsg } as const;
      }
    }
  );

  ipcMain.handle(
    "ailit:saveTextFile",
    async (
      event: IpcMainInvokeEvent,
      params: { readonly suggestedName: string; readonly content: string }
    ) => {
      const win: BrowserWindow | null =
        BrowserWindow.fromWebContents(event.sender) ?? BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? null;
      if (!win) {
        return { ok: false, error: "no window" };
      }
      const res = await dialog.showSaveDialog(win, { defaultPath: params.suggestedName });
      if (res.canceled || !res.filePath) {
        return { ok: false, error: "cancelled" };
      }
      try {
        await fs.writeFile(res.filePath, params.content, "utf8");
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    }
  );
}
