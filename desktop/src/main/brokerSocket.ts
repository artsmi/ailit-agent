import * as net from "node:net";

function brokerUnixPath(endpoint: string): string {
  const raw: string = endpoint.trim();
  if (raw.startsWith("unix://")) {
    return raw.slice("unix://".length);
  }
  return raw;
}

export async function brokerJsonRequest(params: {
  readonly endpoint: string;
  readonly line: string;
  readonly timeoutMs: number;
}): Promise<unknown> {
  const unixPath: string = brokerUnixPath(params.endpoint);
  return new Promise((resolve, reject) => {
    const sock: net.Socket = net.createConnection(unixPath);
    const timer: ReturnType<typeof setTimeout> = setTimeout(() => {
      sock.destroy();
      reject(new Error("broker request timeout"));
    }, params.timeoutMs);
    let buffer = "";
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
      const first = buffer.slice(0, idx).trim();
      clearTimeout(timer);
      sock.end();
      try {
        resolve(JSON.parse(first) as unknown);
      } catch (e) {
        reject(e);
      }
    });
    sock.on("connect", () => {
      sock.write(`${params.line}\n`);
    });
  });
}
