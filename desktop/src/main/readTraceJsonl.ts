import { promises as fs } from "node:fs";

import { traceJsonlPath } from "./defaultRuntimeDir";

export async function readDurableTraceRows(params: {
  readonly runtimeDir: string;
  readonly chatId: string;
}): Promise<{ readonly ok: true; readonly rows: Record<string, unknown>[] } | { readonly ok: false; readonly error: string }> {
  const p: string = traceJsonlPath(params);
  try {
    const text: string = await fs.readFile(p, "utf8");
    const lines: string[] = text.split("\n");
    const rows: Record<string, unknown>[] = [];
    for (const line of lines) {
      const raw: string = line.trim();
      if (!raw) {
        continue;
      }
      try {
        const obj: unknown = JSON.parse(raw);
        if (obj && typeof obj === "object" && !Array.isArray(obj)) {
          rows.push(obj as Record<string, unknown>);
        }
      } catch {
        // skip bad line
      }
    }
    return { ok: true, rows };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
