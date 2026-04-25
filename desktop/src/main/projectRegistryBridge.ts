import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export type ProjectRegistryEntryRow = {
  readonly projectId: string;
  readonly namespace: string;
  readonly title: string;
  readonly path: string;
  readonly active: boolean;
};

export type ProjectRegistryListOutcome =
  | {
      readonly ok: true;
      readonly registryFile: string;
      readonly entries: readonly ProjectRegistryEntryRow[];
      readonly activeProjectIds: readonly string[];
    }
  | { readonly ok: false; readonly error: string };

type JsonListPayload = {
  readonly ok?: boolean;
  readonly registry_file?: string;
  readonly entries?: readonly Record<string, unknown>[];
  readonly active_project_ids?: readonly string[];
};

function mapEntry(row: Record<string, unknown>, activeIds: ReadonlySet<string>): ProjectRegistryEntryRow | null {
  const projectId = String(row["project_id"] ?? "").trim();
  const pathVal = String(row["path"] ?? "").trim();
  const namespace = String(row["namespace"] ?? "").trim();
  const title = String(row["title"] ?? "").trim();
  if (!projectId || !pathVal) {
    return null;
  }
  const active = row["active"] === true || row["active"] === "true" || activeIds.has(projectId);
  return {
    projectId,
    namespace: namespace || projectId,
    title: title || projectId,
    path: pathVal,
    active
  };
}

/**
 * CLI: `ailit project list --json --start <path>` (PATH=ailit в install).
 */
export async function listProjectRegistry(startPath: string | undefined): Promise<ProjectRegistryListOutcome> {
  const ailitBin: string = (process.env["AILIT_CLI"] ?? "ailit").trim() || "ailit";
  const start: string = (startPath ?? process.cwd()).trim() || process.cwd();
  const args: string[] = ["project", "list", "--json", "--start", start];
  try {
    const { stdout, stderr } = await execFileAsync(ailitBin, args, {
      env: process.env,
      maxBuffer: 10 * 1024 * 1024
    });
    if (stderr) {
      // ailit may print to stderr; ignore if stdout parses
    }
    const data = JSON.parse(stdout) as JsonListPayload;
    if (data.ok !== true) {
      return { ok: false, error: "project list: ok!=true" };
    }
    const registryFile: string = String(data.registry_file ?? "");
    const activeIds: ReadonlySet<string> = new Set((data.active_project_ids ?? []).map((x) => String(x)));
    const entriesIn: readonly Record<string, unknown>[] = data.entries ?? [];
    const out: ProjectRegistryEntryRow[] = [];
    for (const e of entriesIn) {
      const m = mapEntry(e, activeIds);
      if (m) {
        out.push(m);
      }
    }
    return {
      ok: true,
      registryFile,
      entries: out,
      activeProjectIds: [...activeIds]
    };
  } catch (e) {
    const msg: string = e instanceof Error ? e.message : String(e);
    return { ok: false, error: msg };
  }
}
