import React from "react";

import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { mockWorkspace } from "../state/mockData";

function severityForKind(kind: string): "info" | "warning" | "error" {
  if (kind === "error_row") {
    return "error";
  }
  if (kind === "unknown") {
    return "warning";
  }
  return "info";
}

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
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const useLive: boolean = s.rawTraceRows.length > 0;
  return (
    <section className="card">
      <div className="cardHeader">Диалог агентов (trace projection)</div>
      <div className="cardBody">
        <div className="mono" style={{ marginBottom: 12 }}>{useLive ? `live: ${s.normalizedRows.length} норм. trace rows` : "пока нет live trace (mock-образец ниже)"}</div>
        {useLive
          ? s.normalizedRows.map((row) => {
              const sev: "info" | "warning" | "error" = severityForKind(row.kind);
              return (
                <div key={row.messageId} style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                    <div style={{ fontWeight: 750 }}>{row.kind}</div>
                    <div className="mono">{row.createdAt || ""}</div>
                  </div>
                  <div style={{ marginTop: 6 }}>{row.humanLine}</div>
                  <div style={{ marginTop: 6, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="pill" style={{ borderColor: severityColor(sev), background: "transparent" }}>
                      <span style={{ color: severityColor(sev), fontWeight: 750 }}>{sev}</span>
                    </span>
                    <span className="mono">{row.technicalLine}</span>
                    <span className="mono">id={row.messageId}</span>
                  </div>
                </div>
              );
            })
          : mockWorkspace.agentDialogue.map((row) => (
              <div key={row.id} style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                  <div style={{ fontWeight: 750 }}>
                    {row.fromAgent} → {row.toAgent}
                  </div>
                  <div className="mono">{row.atIso}</div>
                </div>
                <div style={{ marginTop: 6 }}>{row.humanText}</div>
                <div style={{ marginTop: 6, display: "flex", gap: 12, alignItems: "center" }}>
                  <span
                    className="pill"
                    style={{ borderColor: severityColor(row.severity), background: "transparent" }}
                  >
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
