import React from "react";
import { buildMockSessionReportV1, downloadReportJson, downloadReportMarkdown } from "../state/reportExport";

export function ReportsPage(): React.JSX.Element {
  const report = React.useMemo(() => buildMockSessionReportV1(), []);

  return (
    <section className="card">
      <div className="cardHeader">Отчёты (mock export)</div>
      <div className="cardBody">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <button className="primaryButton" type="button" onClick={() => downloadReportMarkdown(report)}>
            Export Markdown
          </button>
          <button className="primaryButton" type="button" onClick={() => downloadReportJson(report)}>
            Export JSON
          </button>
          <span className="mono">generated_at: {report.generatedAtIso}</span>
        </div>
        <div style={{ marginTop: 16 }}>
          <div className="mono">preview JSON (частично)</div>
          <pre className="mono" style={{ overflow: "auto", maxHeight: 340 }}>
            {JSON.stringify(report, null, 2).slice(0, 1800)}
          </pre>
        </div>
      </div>
    </section>
  );
}

