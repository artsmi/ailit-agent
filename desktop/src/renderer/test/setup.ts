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
  appendSessionDiagnostic: () => Promise.resolve({ ok: true, filePath: "/tmp/ailit-desk-diag.log" }),
  pagGraphSlice: () => Promise.resolve({ ok: false, kind: "ailit_pag_graph_slice_v1", error: "not in test" }),
  memoryJournalRead: () => Promise.resolve({ ok: true, path: "/tmp/memory-journal.jsonl", rows: [] })
};

Object.defineProperty(window, "ailitDesktop", {
  value: api,
  configurable: true,
  writable: true
});
