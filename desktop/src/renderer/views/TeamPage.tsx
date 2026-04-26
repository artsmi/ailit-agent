import React from "react";
import { useSearchParams } from "react-router-dom";

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

/**
 * «Команда» — человекочитаемый inter-agent; перейти с графа (ребро) или с «последней пары».
 */
export function TeamPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const [sp] = useSearchParams();
  const fromUrlA: string = safe(sp.get("a"));
  const fromUrlB: string = safe(sp.get("b"));
  const fromLast: { a: string; b: string } | null = s.lastAgentPair;
  const left: string =
    fromUrlA && fromUrlB
      ? fromUrlA
      : fromLast && fromLast.a && fromLast.b
        ? fromLast.a
        : "";
  const right: string =
    fromUrlA && fromUrlB
      ? fromUrlB
      : fromLast && fromLast.a && fromLast.b
        ? fromLast.b
        : "";
  const hasPair: boolean = Boolean(left.trim() && right.trim());
  const useLive: boolean = s.rawTraceRows.length > 0;
  const rowsLive: typeof s.agentDialogueMessages = hasPair
    ? s.agentDialogueMessages.filter((m) => pairCoversMessage(left, right, m))
    : [];
  const rowsMock: typeof mockWorkspace.agentDialogue = hasPair
    ? mockWorkspace.agentDialogue.filter(
        (r) => new Set([r.fromAgent, r.toAgent]).has(left) && new Set([r.fromAgent, r.toAgent]).has(right)
      )
    : mockWorkspace.agentDialogue;
  return (
    <section className="card">
      <div className="cardHeader">Команда</div>
      <div className="cardBody">
        {useLive
          ? hasPair
            ? rowsLive.map((m) => (
                <div key={m.rawRef.messageId} style={{ marginBottom: 14 }}>
                  <div className="teamRow">
                    <div className="teamFromTo">
                      {m.fromDisplay} <span className="mono" style={{ fontWeight: 600 }}>→</span> {m.toDisplay}
                    </div>
                    <div className="mono timeHint">{m.createdAt || ""}</div>
                  </div>
                  <div style={{ marginTop: 5, color: "var(--candy-text)" }}>{m.humanText}</div>
                  <div className="metaRow">
                    <span
                      className="pill"
                      style={{ borderColor: severityColor(m.severity), background: "transparent", fontSize: "0.7rem" }}
                    >
                      <span style={{ color: severityColor(m.severity), fontWeight: 750 }}>{m.severity}</span>
                    </span>
                    <span className="mono metaSmall">{m.technicalSummary}</span>
                  </div>
                </div>
            ))
            : null
          : rowsMock.map((row) => (
              <div key={row.id} style={{ marginBottom: 14 }}>
                <div className="teamRow">
                  <div className="teamFromTo">
                    {row.fromAgent} <span className="mono" style={{ fontWeight: 600 }}>→</span> {row.toAgent}
                  </div>
                  <div className="mono timeHint">{row.atIso}</div>
                </div>
                <div style={{ marginTop: 5, color: "var(--candy-text)" }}>{row.humanText}</div>
                <div className="metaRow">
                  <span
                    className="pill"
                    style={{ borderColor: severityColor(row.severity), background: "transparent", fontSize: "0.7rem" }}
                  >
                    <span style={{ color: severityColor(row.severity), fontWeight: 750 }}>{row.severity}</span>
                  </span>
                  <span className="mono metaSmall">{row.technicalSummary}</span>
                </div>
              </div>
            ))}
      </div>
    </section>
  );
}
