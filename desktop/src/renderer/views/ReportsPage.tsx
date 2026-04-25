import React from "react";

import { buildLiveSessionReportV1, buildMockSessionReportV1, saveReportJsonViaBridge, saveReportMarkdownViaBridge, type AilitDesktopSessionReportV1 } from "../state/reportExport";
import { useDesktopSession } from "../runtime/DesktopSessionContext";

export function ReportsPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const report: AilitDesktopSessionReportV1 = React.useMemo(() => {
    if (s.rawTraceRows.length) {
      return buildLiveSessionReportV1({
        projects: s.registry.map((p) => ({
          projectId: p.projectId,
          namespace: p.namespace,
          path: p.path,
          title: p.title
        })),
        chat: s.chatLines.map((c) => ({ from: c.from, text: c.text, atIso: c.atIso })),
        normalizedRows: s.normalizedRows,
        rawTraceRows: s.rawTraceRows,
        toolLogs: s.rawTraceRows.slice(0, 32).map((r) => JSON.stringify(r, null, 0).slice(0, 240)),
        connection: s.connection,
        runtimeDir: s.runtimeDir,
        brokerEndpoint: s.brokerEndpoint,
        lastError: s.lastError
      });
    }
    return buildMockSessionReportV1();
  }, [
    s.brokerEndpoint,
    s.chatLines,
    s.connection,
    s.lastError,
    s.normalizedRows,
    s.rawTraceRows,
    s.registry,
    s.runtimeDir
  ]);

  return (
    <section className="card">
      <div className="cardHeader">Отчёты (Markdown / JSON)</div>
      <div className="cardBody">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <button
            className="primaryButton"
            type="button"
            onClick={() => {
              void saveReportMarkdownViaBridge(report);
            }}
          >
            Save Markdown
          </button>
          <button
            className="primaryButton"
            type="button"
            onClick={() => {
              void saveReportJsonViaBridge(report);
            }}
          >
            Save JSON
          </button>
          <span className="mono">source: {report.runtimeHealth.mode}</span>
          <span className="mono">generated_at: {report.generatedAtIso}</span>
        </div>
        <div style={{ marginTop: 16 }}>
          <div className="mono">preview JSON (фрагмент)</div>
          <pre className="mono" style={{ overflow: "auto", maxHeight: 340 }}>
            {JSON.stringify(report, null, 2).slice(0, 2000)}
          </pre>
        </div>
      </div>
    </section>
  );
}
