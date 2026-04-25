import { describe, expect, it } from "vitest";

import { buildLiveSessionReportV1, buildMockSessionReportV1, reportToMarkdown } from "./reportExport";

describe("reportToMarkdown", () => {
  it("includes kind and projects from mock report", () => {
    const r: ReturnType<typeof buildMockSessionReportV1> = buildMockSessionReportV1();
    const md: string = reportToMarkdown(r);
    expect(r.kind).toBe("ailit_desktop_session_report_v1");
    expect(md).toContain("## Projects");
    expect(md).toContain("## Chat transcript");
  });
});

describe("G9.9.2 degradation: report surfaces runtime errors in Markdown", () => {
  it("includes last_error when present (live report)", () => {
    const r = buildLiveSessionReportV1({
      projects: [],
      chat: [],
      agentDialogueMessages: null,
      normalizedRows: [],
      rawTraceRows: [],
      toolLogs: [],
      connection: "disconnected",
      runtimeDir: "/tmp/rt",
      brokerEndpoint: null,
      lastError: "Memory unavailable: broker timeout"
    });
    const md: string = reportToMarkdown(r);
    expect(md).toContain("last_error");
    expect(md).toContain("Memory unavailable");
  });
});
