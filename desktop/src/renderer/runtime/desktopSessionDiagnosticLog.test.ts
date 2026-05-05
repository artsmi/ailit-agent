import { describe, expect, it } from "vitest";

import {
  formatMemoryPagGraphDiagnosticLine,
  formatMemoryW14GraphHighlightDiagnosticLine
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
});
