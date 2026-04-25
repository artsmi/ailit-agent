import React from "react";
import { mockWorkspace } from "../state/mockData";

function severityColor(severity: "info" | "warning" | "error"): string {
  if (severity === "error") {
    return "#c62828";
  }
  if (severity === "warning") {
    return "#ef6c00";
  }
  return "var(--candy-accent-2)";
}

export function AgentDialoguePage(): React.JSX.Element {
  return (
    <section className="card">
      <div className="cardHeader">Диалог агентов (projection, mock)</div>
      <div className="cardBody">
        {mockWorkspace.agentDialogue.map((row) => (
          <div key={row.id} style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
              <div style={{ fontWeight: 750 }}>
                {row.fromAgent} → {row.toAgent}
              </div>
              <div className="mono">{row.atIso}</div>
            </div>
            <div style={{ marginTop: 6 }}>{row.humanText}</div>
            <div style={{ marginTop: 6, display: "flex", gap: 12, alignItems: "center" }}>
              <span className="pill" style={{ borderColor: severityColor(row.severity), background: "transparent" }}>
                <span style={{ color: severityColor(row.severity), fontWeight: 750 }}>{row.severity}</span>
              </span>
              <span className="mono">{row.technicalSummary}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

