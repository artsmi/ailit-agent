import "@testing-library/jest-dom/vitest";
import type { DesktopApi } from "@shared/ipc";
const api: DesktopApi = {
  ping: () => Promise.resolve("pong"),
  supervisorStatus: () => Promise.resolve({ ok: false, error: "not available in unit test" }),
  supervisorBrokers: () => Promise.resolve({ ok: false, error: "not available" }),
  supervisorCreateOrGetBroker: () => Promise.resolve({ ok: false, error: { code: "test", message: "n/a" } }),
  supervisorStopBroker: () => Promise.resolve({ ok: true, result: null }),
  brokerRequest: () => Promise.resolve({ ok: false, error: "n/a" }),
  traceReadDurable: () => Promise.resolve({ ok: true, rows: [] }),
  appendTraceRow: (_params) => Promise.resolve({ ok: true, row: _params.row }),
  traceSubscribe: () => Promise.resolve({ ok: true }),
  traceUnsubscribe: () => Promise.resolve({ ok: true }),
  onTraceRow: () => () => {},
  onTraceChannel: () => () => {},
  projectRegistryList: () =>
    Promise.resolve({
      ok: true,
      registryFile: "/tmp/.ailit/config.yaml",
      entries: [],
      activeProjectIds: []
    }),
  saveTextFile: () => Promise.resolve({ ok: false, error: "no headless" }),
  agentMemoryChatLogsRoot: () => Promise.resolve({ ok: true, root: "/tmp/ailit-test-chat-logs" }),
  ensureChatLogSessionDir: () =>
    Promise.resolve({
      ok: true,
      chatLogsRoot: "/tmp/ailit-test-chat-logs",
      sessionDir: "/tmp/ailit-test-chat-logs/sess",
      safeChatId: "sess"
    }),
  appendDesktopGraphPairLog: () =>
    Promise.resolve({
      ok: true,
      fullPath: "/tmp/ailit-desktop-full.log",
      compactPath: "/tmp/ailit-desktop-compact.log"
    }),
  pagGraphSlice: () => Promise.resolve({ ok: false, kind: "ailit_pag_graph_slice_v1", error: "not in test" }),
  memoryJournalRead: () => Promise.resolve({ ok: true, path: "/tmp/memory-journal.jsonl", rows: [] }),
  homeDir: () => Promise.resolve("/tmp"),
  getDesktopConfigSnapshot: () =>
    Promise.resolve({
      config_path: "/tmp/.ailit/desktop/config.yaml",
      version: 1,
      max_nodes: 100_000,
      max_edges: 200_000,
      highlight_namespace_policy: "first_selected",
      trace_reconnect_min_ms: 800,
      memory_journal_poll_ms: 2000,
      pag_sqlite_poll_interval_ms: 2500,
      user_decision_timeout_s: 300
    })
};

Object.defineProperty(window, "ailitDesktop", {
  value: api,
  configurable: true,
  writable: true
});
