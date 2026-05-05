import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { parse as parseYaml } from "yaml";

import type { DesktopConfigSnapshot, HighlightNamespacePolicy } from "../shared/desktopConfigContract";

/** Prefix for observable yaml errors (task 1.1 / OR-009). */
export const DESKTOP_CONFIG_YAML_ERROR_PREFIX: string = "desktop_config_yaml_error:";

/**
 * Env overrides (defaults < yaml < env). Documented for OR-009 / task 1.1:
 * - AILIT_HOME: base dir for `desktop/config.yaml` (else ~/.ailit/desktop/config.yaml).
 * - AILIT_DESKTOP_MAX_NODES: positive int overrides max_nodes after yaml merge.
 * - AILIT_DESKTOP_MAX_EDGES: positive int overrides max_edges after yaml merge.
 */

const BUILTIN_VERSION: number = 1;
const BUILTIN_MAX_NODES: number = 100_000;
const BUILTIN_MAX_EDGES: number = 200_000;
const BUILTIN_HIGHLIGHT_POLICY: HighlightNamespacePolicy = "first_selected";
const BUILTIN_TRACE_RECONNECT_MIN_MS: number = 800;
const BUILTIN_MEMORY_JOURNAL_POLL_MS: number = 2000;
const BUILTIN_PAG_SQLITE_POLL_MS: number = 2500;
const BUILTIN_USER_DECISION_TIMEOUT_S: number = 300;

let cachedSnapshot: DesktopConfigSnapshot | null = null;

function buildTemplateYaml(): string {
  return [
    "# Desktop UI configuration (OR-009). Paths below are documentation only.",
    `version: ${String(BUILTIN_VERSION)}`,
    "",
    "# max_nodes / max_edges: align with task_2_1 / Python pag_slice_caps after wave 2.",
    `max_nodes: ${String(BUILTIN_MAX_NODES)}`,
    `max_edges: ${String(BUILTIN_MAX_EDGES)}`,
    "",
    "# D-CFG-1: explicit = user-selected primary; first_selected = first project in workspace.",
    `highlight_namespace_policy: ${BUILTIN_HIGHLIGHT_POLICY}`,
    "",
    "# FR1 trace reconnect minimum delay (ms).",
    `trace_reconnect_min_ms: ${String(BUILTIN_TRACE_RECONNECT_MIN_MS)}`,
    "",
    "# Memory journal panel polling (ms); key matches desktop-realtime-graph-protocol.md.",
    `memory_journal_poll_ms: ${String(BUILTIN_MEMORY_JOURNAL_POLL_MS)}`,
    "",
    "# FR3 PAG sqlite poller interval (ms). Single key; no duplicate yaml alias.",
    `pag_sqlite_poll_interval_ms: ${String(BUILTIN_PAG_SQLITE_POLL_MS)}`,
    "",
    "# Tool approval / user decision watchdog (seconds).",
    `user_decision_timeout_s: ${String(BUILTIN_USER_DECISION_TIMEOUT_S)}`,
    "",
    "# --- Data paths (comments; runtime uses supervisor / env as elsewhere) ---",
    "# runtime_dir: supervisor status result.runtime_dir",
    "# trace: {runtime_dir}/trace/trace-<chat>.jsonl",
    "# memory_journal: AILIT_MEMORY_JOURNAL_PATH or ~/.ailit/runtime/memory-journal.jsonl",
    "# pag_sqlite default: ~/.ailit/pag/store.sqlite3",
    "# electron userData: app.getPath('userData')",
    ""
  ].join("\n");
}

function asNonNegativeInt(v: unknown, fallback: number): number {
  if (typeof v === "number" && Number.isFinite(v)) {
    const n: number = Math.trunc(v);
    if (n >= 0) {
      return n;
    }
    return fallback;
  }
  if (typeof v === "string") {
    const t: string = v.trim();
    if (t.length > 0) {
      const n: number = parseInt(t, 10);
      if (Number.isFinite(n) && n >= 0) {
        return n;
      }
    }
  }
  return fallback;
}

function parseHighlightPolicy(v: unknown): HighlightNamespacePolicy | null {
  if (v === "explicit" || v === "first_selected") {
    return v;
  }
  if (typeof v === "string") {
    const s: string = v.trim();
    if (s === "explicit" || s === "first_selected") {
      return s;
    }
  }
  return null;
}

/**
 * D-CFG-1: valid enum from yaml replaces builtin default; unknown/missing → effective first_selected.
 */
function effectiveHighlightPolicy(parsed: HighlightNamespacePolicy | null): HighlightNamespacePolicy {
  return parsed ?? BUILTIN_HIGHLIGHT_POLICY;
}

function mergeRecordIntoBase(rec: Record<string, unknown>): Omit<DesktopConfigSnapshot, "config_path"> {
  const version: number = asNonNegativeInt(rec["version"], BUILTIN_VERSION);
  const max_nodes: number = asNonNegativeInt(rec["max_nodes"], BUILTIN_MAX_NODES);
  const max_edges: number = asNonNegativeInt(rec["max_edges"], BUILTIN_MAX_EDGES);
  const rawPolicy: HighlightNamespacePolicy | null = parseHighlightPolicy(rec["highlight_namespace_policy"]);
  const highlight_namespace_policy: HighlightNamespacePolicy = effectiveHighlightPolicy(rawPolicy);
  const trace_reconnect_min_ms: number = asNonNegativeInt(rec["trace_reconnect_min_ms"], BUILTIN_TRACE_RECONNECT_MIN_MS);
  const memory_journal_poll_ms: number = asNonNegativeInt(rec["memory_journal_poll_ms"], BUILTIN_MEMORY_JOURNAL_POLL_MS);
  const pag_sqlite_poll_interval_ms: number = asNonNegativeInt(
    rec["pag_sqlite_poll_interval_ms"],
    BUILTIN_PAG_SQLITE_POLL_MS
  );
  const user_decision_timeout_s: number = asNonNegativeInt(rec["user_decision_timeout_s"], BUILTIN_USER_DECISION_TIMEOUT_S);
  return {
    version,
    max_nodes,
    max_edges,
    highlight_namespace_policy,
    trace_reconnect_min_ms,
    memory_journal_poll_ms,
    pag_sqlite_poll_interval_ms,
    user_decision_timeout_s
  };
}

function builtinBase(): Omit<DesktopConfigSnapshot, "config_path"> {
  return mergeRecordIntoBase({});
}

function applyDocumentedEnv(base: Omit<DesktopConfigSnapshot, "config_path">): Omit<DesktopConfigSnapshot, "config_path"> {
  const nodesRaw: string | undefined = process.env["AILIT_DESKTOP_MAX_NODES"]?.trim();
  const edgesRaw: string | undefined = process.env["AILIT_DESKTOP_MAX_EDGES"]?.trim();
  let max_nodes: number = base.max_nodes;
  let max_edges: number = base.max_edges;
  if (nodesRaw && nodesRaw.length > 0) {
    const n: number = parseInt(nodesRaw, 10);
    if (Number.isFinite(n) && n > 0) {
      max_nodes = n;
    }
  }
  if (edgesRaw && edgesRaw.length > 0) {
    const n: number = parseInt(edgesRaw, 10);
    if (Number.isFinite(n) && n > 0) {
      max_edges = n;
    }
  }
  if (max_nodes === base.max_nodes && max_edges === base.max_edges) {
    return base;
  }
  return { ...base, max_nodes, max_edges };
}

export function resolveDesktopConfigPath(): string {
  const homeRaw: string | undefined = process.env["AILIT_HOME"]?.trim();
  const baseDir: string =
    homeRaw && homeRaw.length > 0 ? path.join(homeRaw, "desktop") : path.join(os.homedir(), ".ailit", "desktop");
  return path.join(baseDir, "config.yaml");
}

export function loadDesktopConfigOrCreateTemplate(): DesktopConfigSnapshot {
  const config_path: string = resolveDesktopConfigPath();
  const dir: string = path.dirname(config_path);
  let merged: Omit<DesktopConfigSnapshot, "config_path"> = builtinBase();

  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (e) {
    console.error(`${DESKTOP_CONFIG_YAML_ERROR_PREFIX} cannot mkdir: ${e instanceof Error ? e.message : String(e)}`);
    merged = applyDocumentedEnv(builtinBase());
    return { config_path, ...merged };
  }

  let fileExists: boolean = false;
  try {
    const st: fs.Stats = fs.statSync(config_path);
    fileExists = st.isFile();
  } catch {
    fileExists = false;
  }

  if (!fileExists) {
    try {
      fs.writeFileSync(config_path, buildTemplateYaml(), "utf8");
    } catch (e) {
      console.error(`${DESKTOP_CONFIG_YAML_ERROR_PREFIX} cannot write template: ${e instanceof Error ? e.message : String(e)}`);
    }
    merged = applyDocumentedEnv(mergeRecordIntoBase({}));
    return { config_path, ...merged };
  }

  try {
    const txt: string = fs.readFileSync(config_path, "utf8");
    const doc: unknown = parseYaml(txt);
    const rec: Record<string, unknown> | null =
      doc && typeof doc === "object" && !Array.isArray(doc) ? (doc as Record<string, unknown>) : null;
    if (!rec) {
      console.error(`${DESKTOP_CONFIG_YAML_ERROR_PREFIX} root must be a mapping`);
      merged = applyDocumentedEnv(builtinBase());
    } else {
      merged = applyDocumentedEnv(mergeRecordIntoBase(rec));
    }
  } catch (e) {
    console.error(`${DESKTOP_CONFIG_YAML_ERROR_PREFIX} ${e instanceof Error ? e.message : String(e)}`);
    merged = applyDocumentedEnv(builtinBase());
  }

  return { config_path, ...merged };
}

export function warmDesktopConfigCache(): DesktopConfigSnapshot {
  cachedSnapshot = loadDesktopConfigOrCreateTemplate();
  return cachedSnapshot;
}

export function getCachedDesktopConfigSnapshot(): DesktopConfigSnapshot {
  if (cachedSnapshot) {
    return cachedSnapshot;
  }
  return warmDesktopConfigCache();
}
