import { BrowserWindow, dialog, ipcMain, type IpcMainInvokeEvent } from "electron";
import { promises as fs } from "node:fs";

import { brokerJsonRequest } from "./brokerSocket";
import { defaultRuntimeDir, supervisorSocketPath } from "./defaultRuntimeDir";
import { listProjectRegistry } from "./projectRegistryBridge";
import { readDurableTraceRows } from "./readTraceJsonl";
import { supervisorJsonRequest } from "./supervisorSocket";
import { traceSubscribe, traceUnsubscribe } from "./traceSocketPool";

function asRecord(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

export function registerIpcHandlers(): void {
  ipcMain.handle("ailit:ping", async () => "pong");

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
    async (
      _e: unknown,
      params: { readonly chatId: string; readonly namespace: string; readonly projectRoot: string }
    ) => {
      const runtimeDir: string = defaultRuntimeDir();
      const sock: string = supervisorSocketPath(runtimeDir);
      try {
        const raw: unknown = await supervisorJsonRequest({
          socketPath: sock,
          request: {
            cmd: "create_or_get_broker",
            chat_id: params.chatId,
            namespace: params.namespace,
            project_root: params.projectRoot
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
