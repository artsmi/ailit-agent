import React from "react";

import { useDesktopSession } from "../runtime/DesktopSessionContext";
import type { ChatSessionRecordV1 } from "../state/persistedUi";

function briefTitle(s: ChatSessionRecordV1, reg: ReturnType<typeof useDesktopSession>["registry"]): string {
  if (s.label && s.label !== "Session 1") {
    return s.label;
  }
  const t: string = s.projectIds
    .map((id) => reg.find((p) => p.projectId === id)?.title ?? id)
    .filter(Boolean)
    .join(" + ");
  return t || s.label;
}

/**
 * Чат: сессии в dropdown, новый диалог — в shell.
 */
export function ChatPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const [draft, setDraft] = React.useState("");
  return (
    <div className="chatPage">
      <div className="chatTop">
        <div className="chatSessionRow">
          <label className="sessionLbl" htmlFor="sessionPick">
            Сессия
          </label>
          <select
            className="sessionSelect"
            id="sessionPick"
            value={s.activeSessionId}
            onChange={(e) => {
              s.setActiveSessionId(e.target.value);
            }}
          >
            {s.sessions.map((sess) => (
              <option key={sess.id} value={sess.id}>
                {briefTitle(sess, s.registry)}
              </option>
            ))}
          </select>
        </div>
        <div className="chatWorkspacePills">
          {s.registry
            .filter((p) => s.selectedProjectIds.includes(p.projectId))
            .map((p) => (
              <span className="pill smPill" key={p.projectId}>
                {p.title}
              </span>
            ))}
        </div>
        <div className="chatActions">
          <button className="linkBtn" type="button" onClick={() => void s.loadProjects()}>
            registry
          </button>
          <button className="linkBtn" type="button" onClick={() => void s.connectToBroker()}>
            reconnect
          </button>
        </div>
      </div>
      <section className="card chatCard">
        <div className="cardBody chatStream">
          {s.lastError ? <div className="errLine">{s.lastError}</div> : null}
          {s.chatLines.map((m) => (
            <div className="chatLine" key={m.id}>
              <div
                className="chatFrom"
                style={{
                  color:
                    m.from === "user" ? "var(--candy-text)" : m.from === "system" ? "#6b5b2a" : "var(--candy-accent)"
                }}
              >
                {m.from === "user" ? "User" : m.from === "system" ? "System" : "Assistant"}
              </div>
              <div className="chatText">{m.text}</div>
            </div>
          ))}
        </div>
        <div className="chatComposer">
          <input
            className="chatInput"
            value={draft}
            placeholder="Сообщение…"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                const t: string = draft;
                setDraft("");
                void s.sendUserPrompt(t);
              }
            }}
          />
          <button
            className="primaryButton smBtn"
            type="button"
            onClick={() => {
              const t: string = draft;
              setDraft("");
              void s.sendUserPrompt(t);
            }}
          >
            Send
          </button>
        </div>
      </section>
    </div>
  );
}
