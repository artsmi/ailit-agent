import * as net from "node:net";

export async function supervisorJsonRequest(params: {
  readonly socketPath: string;
  readonly request: Record<string, unknown>;
  readonly timeoutMs: number;
}): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const sock: net.Socket = net.createConnection(params.socketPath);
    const payload: string = `${JSON.stringify(params.request)}\n`;
    let buffer = "";
    const timer: ReturnType<typeof setTimeout> = setTimeout(() => {
      sock.destroy();
      reject(new Error("supervisor request timeout"));
    }, params.timeoutMs);
    sock.setEncoding("utf8");
    sock.on("error", (err: Error) => {
      clearTimeout(timer);
      reject(err);
    });
    sock.on("data", (chunk: string) => {
      buffer += chunk;
      const idx = buffer.indexOf("\n");
      if (idx < 0) {
        return;
      }
      const line = buffer.slice(0, idx).trim();
      clearTimeout(timer);
      sock.end();
      try {
        resolve(JSON.parse(line) as unknown);
      } catch (e) {
        reject(e);
      }
    });
    sock.on("connect", () => {
      sock.write(payload);
    });
  });
}
