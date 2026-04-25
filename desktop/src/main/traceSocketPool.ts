import * as net from "node:net";
import { BrowserWindow } from "electron";

const SUB_CMD = '{"cmd":"subscribe_trace"}';

function endpointToUnixPath(endpoint: string): string {
  const raw: string = endpoint.trim();
  if (raw.startsWith("unix://")) {
    return raw.slice("unix://".length);
  }
  return raw;
}

type TraceClient = {
  readonly socket: net.Socket;
  readonly buffer: { value: string };
};

const clients: Map<string, TraceClient> = new Map();

function broadcastTraceRow(chatId: string, row: Record<string, unknown>): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send("ailit:traceRow", { chatId, row });
  }
}

function broadcastTraceChannel(evt: { readonly chatId: string; readonly kind: "open" | "end" | "error"; readonly detail?: string }): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send("ailit:traceChannel", evt);
  }
}

export function traceUnsubscribe(chatId: string): void {
  const cur: TraceClient | undefined = clients.get(chatId);
  if (cur) {
    cur.socket.destroy();
    clients.delete(chatId);
  }
}

/**
 * Подписка на live trace: отдельное соединение + `subscribe_trace` (см. broker._BrokerHandler).
 */
export function traceSubscribe(params: { readonly chatId: string; readonly endpoint: string }): { readonly ok: true } | { readonly ok: false; readonly error: string } {
  traceUnsubscribe(params.chatId);
  const pathUnix: string = endpointToUnixPath(params.endpoint);
  const sock: net.Socket = net.createConnection(pathUnix);
  const state: { value: string } = { value: "" };
  const client: TraceClient = { socket: sock, buffer: state };
  clients.set(params.chatId, client);
  sock.setEncoding("utf8");
  sock.on("connect", () => {
    broadcastTraceChannel({ chatId: params.chatId, kind: "open" });
    sock.write(`${SUB_CMD}\n`);
  });
  sock.on("data", (chunk: string) => {
    state.value += chunk;
    let idx: number;
    while ((idx = state.value.indexOf("\n")) >= 0) {
      const line: string = state.value.slice(0, idx).trim();
      state.value = state.value.slice(idx + 1);
      if (!line) {
        continue;
      }
      try {
        const obj: unknown = JSON.parse(line);
        if (obj && typeof obj === "object" && !Array.isArray(obj)) {
          broadcastTraceRow(params.chatId, obj as Record<string, unknown>);
        }
      } catch {
        // ignore non-json
      }
    }
  });
  sock.on("close", () => {
    clients.delete(params.chatId);
    broadcastTraceChannel({ chatId: params.chatId, kind: "end" });
  });
  sock.on("error", (err: Error) => {
    clients.delete(params.chatId);
    broadcastTraceChannel({ chatId: params.chatId, kind: "error", detail: err.message });
  });
  return { ok: true };
}
