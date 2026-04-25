import React from "react";
import { mockWorkspace } from "../state/mockData";

export function CurrentAgentsPage(): React.JSX.Element {
  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Текущие агенты (manifest seed, mock)</div>
        <div className="cardBody">
          {mockWorkspace.agents.map((a) => (
            <div key={a.agentType} style={{ marginBottom: 14, display: "flex", gap: 12, alignItems: "center" }}>
              <div
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: 999,
                  background: a.color,
                  boxShadow: `0 0 0 6px ${a.color}22`
                }}
              />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 800 }}>{a.displayName}</div>
                <div className="mono">{a.agentType}</div>
                <div style={{ color: "var(--candy-text-2)" }}>{a.role}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Связи (trace-derived, mock)</div>
        <div className="cardBody">
          {mockWorkspace.agentLinks.map((l) => (
            <div key={`${l.fromAgentType}->${l.toAgentType}`} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 750 }}>
                {l.fromAgentType} → {l.toAgentType}
              </div>
              <div className="mono">{l.label}</div>
            </div>
          ))}
          <div className="mono">В MVP это мок. В runtime версии links строятся из trace rows.</div>
        </div>
      </section>
    </div>
  );
}

