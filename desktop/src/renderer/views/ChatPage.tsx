import React from "react";
import { mockWorkspace } from "../state/mockData";

export function ChatPage(): React.JSX.Element {
  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Чат</div>
        <div className="cardBody">
          {mockWorkspace.chat.map((m) => (
            <div key={m.id} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 750, color: m.from === "user" ? "var(--candy-text)" : "var(--candy-accent)" }}>
                {m.from === "user" ? "User" : "Assistant"}
              </div>
              <div>{m.text}</div>
              <div className="mono">{m.atIso}</div>
            </div>
          ))}
          <div style={{ display: "flex", gap: 12, marginTop: 16, alignItems: "center" }}>
            <button className="primaryButton" type="button" onClick={() => void window.ailitDesktop.ping()}>
              Ping preload (mock)
            </button>
            <span className="mono">runtime: mock-only (G9.1)</span>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Tool logs / usage (mock)</div>
        <div className="cardBody">
          <div className="pill" style={{ marginBottom: 12 }}>
            <span>tokens</span>
            <span className="mono">
              in={mockWorkspace.usage.tokensIn} out={mockWorkspace.usage.tokensOut} cost=${mockWorkspace.usage.costUsd}
            </span>
          </div>
          <div className="mono">
            {mockWorkspace.toolLogs.map((l) => (
              <div key={l}>{l}</div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

