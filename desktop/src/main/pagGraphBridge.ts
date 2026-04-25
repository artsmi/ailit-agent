import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export type PagGraphSliceOk = {
  readonly ok: true;
  readonly kind: "ailit_pag_graph_slice_v1";
  readonly namespace: string;
  readonly db_path: string;
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

/**
 * Срез PAG через `ailit memory pag-slice` (main process, не renderer).
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
      maxBuffer: 20 * 1024 * 1024
    });
    const line: string = stdout
      .trim()
      .split("\n")
      .filter((x) => x.length > 0)
      .pop() ?? "";
    if (!line) {
      return { ok: false, kind: "ailit_pag_graph_slice_v1", error: "empty pag-slice output" };
    }
    return JSON.parse(line) as PagGraphSliceResult;
  } catch (e) {
    const msg: string = e instanceof Error ? e.message : String(e);
    return { ok: false, kind: "ailit_pag_graph_slice_v1", error: msg };
  }
}
