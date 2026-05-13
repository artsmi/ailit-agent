import { describe, expect, it } from "vitest";

import type { BrokerRequestResult } from "@shared/ipc";

import {
  DESKTOP_SESSION_BROKER_REQUEST_EVENT,
  formatDesktopSessionBrokerRequestLine,
  formatMemoryPagGraphDiagnosticLine,
  formatMemoryW14GraphHighlightDiagnosticLine,
  mapBrokerRequestOutcome
} from "./desktopSessionDiagnosticLog";

/** TC-VITEST-FMT-01: mock payload → compact line с timestamp, event, subject (node upsert stub). */
describe("desktopSessionDiagnosticLog formatters", () => {
  it("TC-VITEST-FMT-01: formatMemoryPagGraphDiagnosticLine node upsert stub", () => {
    const line: string = formatMemoryPagGraphDiagnosticLine({
      isoTimestamp: "2026-05-05T12:00:00.000Z",
      op: "node",
      namespace: "ns-demo",
      rev: 42,
      subject: "node-abc-upsert"
    });
    expect(line).toContain("timestamp=2026-05-05T12:00:00.000Z");
    expect(line).toContain("event=memory.pag_graph");
    expect(line).toContain("op=node");
    expect(line).toContain("subject=node-abc-upsert");
    expect(line).toContain("namespace=ns-demo");
    expect(line).toContain("rev=42");
  });

  it("W14 compact line includes query_id when provided (C-LOG-1)", () => {
    const line: string = formatMemoryW14GraphHighlightDiagnosticLine({
      isoTimestamp: "2026-05-05T12:00:00.000Z",
      namespace: "ns-x",
      source: "w14_trace",
      nodeCount: 2,
      edgeCount: 1,
      ttlMs: 3000,
      queryId: "q-abc"
    });
    expect(line).toContain("event=memory.w14_graph_highlight");
    expect(line).toContain("query_id=q-abc");
  });

  /** TC-G19.1-UNIT-01: brokerRequest compact formatter (OR-D6). */
  it("TC-G19.1-UNIT-01: formatDesktopSessionBrokerRequestLine includes OR-D6 fields", () => {
    const line: string = formatDesktopSessionBrokerRequestLine({
      isoTimestamp: "2026-05-05T12:00:00.000Z",
      durationMs: 42.7,
      outcome: "ok",
      chatId: "chat-a",
      sessionUi: "sess-b",
      brokerOp: "user_prompt",
      rawTraceRowsLength: 12,
      traceRowsPerSec: 3.25,
      rendererBudgetSource: "unavailable",
      longtaskDurationMs: null,
      rafGapMsP95: null
    });
    expect(line).toContain(`event=${DESKTOP_SESSION_BROKER_REQUEST_EVENT}`);
    expect(line).toContain("duration_ms=43");
    expect(line).toContain("outcome=ok");
    expect(line).toContain("chat_id=chat-a");
    expect(line).toContain("session_ui=sess-b");
    expect(line).toContain("rawTraceRows_length=12");
    expect(line).toContain("trace_rows_per_sec=3.25");
    expect(line).toContain("renderer_budget_source=unavailable");
    expect(line).toContain("longtask_duration_ms=null");
    expect(line).toContain("raf_gap_ms_p95=null");
  });

  it("mapBrokerRequestOutcome maps timeout-ish IPC errors", () => {
    expect(
      mapBrokerRequestOutcome({
        ok: false,
        error: "request timed out after 30000ms"
      })
    ).toBe("timeout");
    expect(mapBrokerRequestOutcome({ ok: false, error: "broken" })).toBe("error");
    expect(mapBrokerRequestOutcome({ ok: true, response: {} as never } as BrokerRequestResult)).toBe("ok");
  });
});
