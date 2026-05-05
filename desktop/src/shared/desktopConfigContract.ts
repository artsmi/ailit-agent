/**
 * Desktop ~/.ailit/desktop/config.yaml snapshot (OR-009, task 1.1).
 *
 * D-IPC-1: Renderer получает только этот объект через preload; не читает yaml/fs.
 * D-CFG-1: highlight_namespace_policy — effective после валидации enum (unknown → first_selected).
 */

export type HighlightNamespacePolicy = "explicit" | "first_selected";

export type DesktopConfigSnapshot = {
  readonly config_path: string;
  readonly version: number;
  readonly max_nodes: number;
  readonly max_edges: number;
  readonly highlight_namespace_policy: HighlightNamespacePolicy;
  readonly trace_reconnect_min_ms: number;
  readonly memory_journal_poll_ms: number;
  readonly pag_sqlite_poll_interval_ms: number;
  readonly user_decision_timeout_s: number;
};
