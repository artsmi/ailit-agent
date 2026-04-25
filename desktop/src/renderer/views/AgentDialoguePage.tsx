import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { pairCoversMessage } from "../runtime/agentDialogueProjection";
import { useDesktopSession } from "../runtime/DesktopSessionContext";
import { mockWorkspace } from "../state/mockData";

function severityColor(sev: "info" | "warning" | "error"): string {
  if (sev === "error") {
    return "#c62828";
  }
  if (sev === "warning") {
    return "#ef6c00";
  }
  return "var(--candy-accent-2)";
}

function safe(s: string | null): string {
  if (!s) {
    return "";
  }
  return String(s);
}

export function AgentDialoguePage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const nav: ReturnType<typeof useNavigate> = useNavigate();
  const [sp]: [URLSearchParams, (next: URLSearchParams) => void] = useSearchParams();
  const left: string = safe(sp.get("a"));
  const right: string = safe(sp.get("b"));
  const useLive: boolean = s.rawTraceRows.length > 0;
  const rows: typeof s.agentDialogueMessages = useLive
    ? s.agentDialogueMessages.filter((m) => pairCoversMessage(left, right, m))
    : [];
  return (
    <section className="card">
      <div className="cardHeader">Диалог агентов (человекочитаемо)</div>
      <div className="cardBody">
        {left && right
          ? (
            <div className="mono" style={{ marginBottom: 12 }}>
              фильтр: {left} ↔ {right} (
              <button
                className="pill"
                type="button"
                style={{ background: "transparent" }}
                onClick={() => {
                  nav({ pathname: "/agent-dialogue" });
                }}
              >
                сброс
              </button>
              )
            </div>
          )
          : useLive
            ? (
              <div className="mono" style={{ marginBottom: 12 }}>
                live: {s.agentDialogueMessages.length} реплик, trace rows {s.rawTraceRows.length}
              </div>
            )
            : (
              <div className="mono" style={{ marginBottom: 12 }}>
                пока нет live trace (пример human-readable ниже)
              </div>
            )}
        {useLive
          ? rows.length
            ? rows.map((m) => (
                <div key={m.rawRef.messageId} style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                    <div style={{ fontWeight: 800 }}>
                      {m.fromDisplay} <span className="mono" style={{ fontWeight: 600 }}>→</span> {m.toDisplay}
                    </div>
                    <div className="mono">{m.createdAt || ""}</div>
                  </div>
                  <div style={{ marginTop: 6 }}>{m.humanText}</div>
                  <div style={{ marginTop: 6, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="pill" style={{ borderColor: severityColor(m.severity), background: "transparent" }}>
                      <span style={{ color: severityColor(m.severity), fontWeight: 750 }}>{m.severity}</span>
                    </span>
                    <span className="mono">{m.technicalSummary}</span>
                    <span className="mono">id={m.rawRef.messageId}</span>
                  </div>
                  <details style={{ marginTop: 8 }} className="mono">
                    <summary>raw JSON (debug)</summary>
                    <pre style={{ maxHeight: 200, overflow: "auto" }}>{JSON.stringify(m.raw, null, 2)}</pre>
                  </details>
                </div>
            ))
            : (
              <div className="mono" style={{ marginTop: 8 }}>
                Нет inter-agent реплик: только пользователь/системные события или пустой trace. Нормировка trace →
                {s.normalizedRows[0] ? " см. also normalized" : ""} raw rows.
              </div>
            )
          : mockWorkspace.agentDialogue.map((row) => (
              <div key={row.id} style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                  <div style={{ fontWeight: 800 }}>
                    {row.fromAgent} <span className="mono" style={{ fontWeight: 600 }}>→</span> {row.toAgent}
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
