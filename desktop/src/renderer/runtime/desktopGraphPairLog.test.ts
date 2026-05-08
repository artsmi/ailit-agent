import { describe, expect, it } from "vitest";

import { buildAmCompactLine, buildAmFullLogBlock, deriveTraceRowEventLabel } from "./desktopGraphPairLog";

describe("desktopGraphPairLog", () => {
  it("deriveTraceRowEventLabel reads topic.publish event_name", () => {
    const row: Record<string, unknown> = {
      type: "topic.publish",
      payload: {
        event_name: "pag.node.upsert",
        payload: { kind: "pag.node.upsert", namespace: "ns", rev: 1 }
      }
    };
    expect(deriveTraceRowEventLabel(row)).toBe("pag.node.upsert");
  });

  it("AM full block contains trace_seq and JSON body", () => {
    const row: Record<string, unknown> = { type: "action.start", message_id: "m1" };
    const block: string = buildAmFullLogBlock("2026-05-07T12:00:00.000Z", 7, row);
    expect(block).toContain("source=AM");
    expect(block).toContain("trace_seq=7");
    expect(block).toContain('"type":"action.start"');
  });

  it("AM compact line includes message_id", () => {
    const row: Record<string, unknown> = {
      type: "topic.publish",
      message_id: "mid-x",
      trace_id: "tid-y",
      namespace: "ns-z",
      payload: { event_name: "memory.w14.graph_highlight", payload: {} }
    };
    const line: string = buildAmCompactLine("2026-05-07T12:00:00.000Z", 3, row);
    expect(line).toContain("trace_seq=3");
    expect(line).toContain("message_id=mid-x");
    expect(line).toContain("memory.w14.graph_highlight");
  });
});
