import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

/** JSON pag-slice до 100k нод / 200k рёбер; запас на stdout (G12.3, D-SCL-1). */
export const PAG_GRAPH_SLICE_IPC_MAX_BUFFER: number = 96 * 1024 * 1024;

export type PagGraphSliceOk = {
  readonly ok: true;
  readonly kind: "ailit_pag_graph_slice_v1";
  readonly namespace: string;
  readonly db_path: string;
  /** Монотонный rev PAG в SQLite (G12). */
  readonly graph_rev?: number;
  readonly pag_state: string;
  readonly level_filter: string | null;
  readonly nodes: readonly Record<string, unknown>[];
  readonly edges: readonly Record<string, unknown>[];
  readonly limits: {
    readonly node_limit: number;
    readonly node_offset: number;
    readonly edge_limit: number;
    readonly edge_offset: number;
  };
  readonly has_more: { readonly nodes: boolean; readonly edges: boolean };
};

export type PagGraphSliceErr = {
  readonly ok: false;
  readonly kind: "ailit_pag_graph_slice_v1";
  readonly code?: string;
  readonly error: string;
  readonly namespace?: string;
};

export type PagGraphSliceResult = PagGraphSliceOk | PagGraphSliceErr;

export type PagGraphSliceRunWithStdoutMetrics = {
  readonly result: PagGraphSliceResult;
  /** Размер сырого stdout CLI (байты UTF-8) для compact OR-D6; не содержимое. */
  readonly stdoutByteLength: number;
};

function stdoutByteLengthFromUnknown(raw: unknown): number {
  if (raw == null) {
    return 0;
  }
  if (typeof raw === "string") {
    return Buffer.byteLength(raw, "utf8");
  }
  if (Buffer.isBuffer(raw)) {
    return raw.length;
  }
  return 0;
}

/**
 * Срез PAG через `ailit memory pag-slice` (main process, не renderer).
 */
export async function runPagGraphSliceWithStdoutMetrics(params: {
  readonly namespace: string;
  readonly dbPath?: string;
  readonly level: string | null;
  readonly nodeLimit: number;
  readonly nodeOffset: number;
  readonly edgeLimit: number;
  readonly edgeOffset: number;
}): Promise<PagGraphSliceRunWithStdoutMetrics> {
  const ailit: string = (process.env["AILIT_CLI"] ?? "ailit").trim() || "ailit";
  const args: string[] = [
    "memory",
    "pag-slice",
    "--json",
    "--namespace",
    params.namespace,
    "--node-limit",
    String(params.nodeLimit),
    "--node-offset",
    String(params.nodeOffset),
    "--edge-limit",
    String(params.edgeLimit),
    "--edge-offset",
    String(params.edgeOffset)
  ];
  if (params.dbPath) {
    args.push("--db-path", params.dbPath);
  }
  if (params.level && params.level !== "all") {
    args.push("--level", params.level);
  }
  try {
    const { stdout } = await execFileAsync(ailit, args, {
      env: process.env,
      maxBuffer: PAG_GRAPH_SLICE_IPC_MAX_BUFFER
    });
    const stdoutByteLength: number = stdoutByteLengthFromUnknown(stdout);
    const line: string = stdout
      .trim()
      .split("\n")
      .filter((x) => x.length > 0)
      .pop() ?? "";
    if (!line) {
      return {
        result: { ok: false, kind: "ailit_pag_graph_slice_v1", error: "empty pag-slice output" },
        stdoutByteLength
      };
    }
    return { result: JSON.parse(line) as PagGraphSliceResult, stdoutByteLength };
  } catch (e) {
    const msg: string = e instanceof Error ? e.message : String(e);
    let stdoutByteLength: number = 0;
    if (e && typeof e === "object") {
      const stdoutUnknown: unknown = (e as { stdout?: unknown }).stdout;
      stdoutByteLength = stdoutByteLengthFromUnknown(stdoutUnknown);
    }
    return {
      result: { ok: false, kind: "ailit_pag_graph_slice_v1", error: msg },
      stdoutByteLength
    };
  }
}

/**
 * Обёртка для вызовов, которым не нужен размер stdout (совместимость).
 */
export async function runPagGraphSlice(params: {
  readonly namespace: string;
  readonly dbPath?: string;
  readonly level: string | null;
  readonly nodeLimit: number;
  readonly nodeOffset: number;
  readonly edgeLimit: number;
  readonly edgeOffset: number;
}): Promise<PagGraphSliceResult> {
  const r: PagGraphSliceRunWithStdoutMetrics = await runPagGraphSliceWithStdoutMetrics(params);
  return r.result;
}
