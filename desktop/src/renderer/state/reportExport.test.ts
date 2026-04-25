import { describe, expect, it } from "vitest";

import { buildMockSessionReportV1, reportToMarkdown } from "./reportExport";

describe("reportToMarkdown", () => {
  it("includes kind and projects from mock report", () => {
    const r: ReturnType<typeof buildMockSessionReportV1> = buildMockSessionReportV1();
    const md: string = reportToMarkdown(r);
    expect(r.kind).toBe("ailit_desktop_session_report_v1");
    expect(md).toContain("## Projects");
    expect(md).toContain("## Chat transcript");
  });
});
