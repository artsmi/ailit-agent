import React from "react";

import { useDesktopSession } from "../runtime/DesktopSessionContext";

export function ChatPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const [draft, setDraft] = React.useState("");

  return (
    <div className="grid2">
      <section className="card">
        <div className="cardHeader">Чат (runtime, замена ailit chat)</div>
        <div className="cardBody">
          <div className="mono" style={{ marginBottom: 10 }}>
            connect: {s.connection}
            {s.brokerEndpoint ? " • broker" : ""}
            {s.reconnectAttempt ? ` • trace reconnects=${s.reconnectAttempt}` : ""}
          </div>
          {s.lastError ? (
            <div className="mono" style={{ color: "var(--candy-warn, #a04010)", marginBottom: 10 }}>
              {s.lastError}
            </div>
          ) : null}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Активные проекты (workspace)</div>
            {s.registry.length ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {s.registry.map((p) => (
                  <label
                    key={p.projectId}
                    style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}
                    className="mono"
                  >
                    <input
                      type="checkbox"
                      checked={s.selectedProjectIds.includes(p.projectId)}
                      onChange={() => s.toggleProject(p.projectId)}
                    />
                    {p.title} <span className="pill" style={{ border: 0, padding: "0 6px" }}>{p.namespace}</span>
                    <span style={{ opacity: 0.6 }}>({p.path})</span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="mono">Список пуст: `ailit project add` (реестр в ~/.ailit), затем «Load registry».</div>
            )}
            <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button className="primaryButton" type="button" onClick={() => void s.loadProjects()}>
                Load registry
              </button>
              <button type="button" onClick={() => void s.connectToBroker()}>
                Reconnect runtime
              </button>
            </div>
            {!s.registry.length && (
              <div className="mono" style={{ marginTop: 8, opacity: 0.7 }}>
                 Подсказка: без зарегистрированного проекта `work.handle_user_prompt` не сможет выбрать namespace/корень.
              </div>
            )}
            {s.registry.length > 0 && s.selectedProjectIds.length === 0 && (
              <div className="mono" style={{ color: "var(--candy-warn, #a04010)" }}>
                Не отмечен ни один проект. Отметьте один или несколько.
              </div>
            )}
          </div>
          {s.chatLines.map((m) => (
            <div key={m.id} style={{ marginBottom: 12 }}>
              <div
                style={{
                  fontWeight: 750,
                  color:
                    m.from === "user" ? "var(--candy-text)" : m.from === "system" ? "#6b5b2a" : "var(--candy-accent)"
                }}
              >
                {m.from === "user" ? "User" : m.from === "system" ? "System" : "Assistant"}
              </div>
              <div>{m.text}</div>
              <div className="mono">{m.atIso}</div>
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <input
              className="mono"
              style={{ flex: "1 1 280px", padding: "8px 10px", borderRadius: 8, border: "1px solid #f0b8d0" }}
              value={draft}
              placeholder="Сообщение для AgentWork (action.start)…"
              onChange={(e) => setDraft(e.target.value)}
            />
            <button
              className="primaryButton"
              type="button"
              onClick={() => {
                const t: string = draft;
                setDraft("");
                void s.sendUserPrompt(t);
              }}
            >
              Send
            </button>
            <span className="mono">raw trace rows: {s.rawTraceRows.length}</span>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="cardHeader">Tool logs / usage</div>
        <div className="cardBody">
          {s.rawTraceRows.slice(-5).map((r, i) => (
            <div key={i} className="mono" style={{ fontSize: 12, marginBottom: 4 }}>
              {String((r as { type?: string }).type ?? "row")} mid={String((r as { message_id?: string }).message_id ?? "")}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
