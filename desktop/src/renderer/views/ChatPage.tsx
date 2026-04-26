import React from "react";

import { ChatAnalyticsAside } from "../components/chat/ChatAnalyticsAside";
import { CandyChatConsoleBlock } from "../components/chat/CandyChatConsoleBlock";
import { ChatSessionTabs } from "../components/chat/ChatSessionTabs";
import { useChatLayout } from "../shell/ChatLayoutContext";
import { useDesktopSession, type ChatLine } from "../runtime/DesktopSessionContext";
import type { ChatSessionRecordV1 } from "../state/persistedUi";
import { CandyMaterialIcon } from "../shell/CandyMaterialIcon";

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

function connectionLabel(c: ReturnType<typeof useDesktopSession>["connection"]): string {
  if (c === "ready") {
    return "Готово";
  }
  if (c === "connecting") {
    return "Подключение…";
  }
  if (c === "error") {
    return "Ошибка";
  }
  return "—";
}

function groupMessagesForLayout(lines: readonly ChatLine[]): { readonly kind: "user" | "ai"; readonly items: readonly ChatLine[] }[] {
  const out: { kind: "user" | "ai"; items: ChatLine[] }[] = [];
  for (const m of lines) {
    const k: "user" | "ai" = m.from === "user" ? "user" : "ai";
    const last: { kind: "user" | "ai"; items: ChatLine[] } | undefined = out[out.length - 1];
    if (last !== undefined && last.kind === k) {
      last.items.push(m);
    } else {
      out.push({ kind: k, items: [m] });
    }
  }
  return out;
}

/**
 * Чат в стиле `ai_agent_minimalist_chat_candy_style`: вкладки сессий, консоль tool/shell, опциональная правая панель.
 */
export function ChatPage(): React.JSX.Element {
  const s: ReturnType<typeof useDesktopSession> = useDesktopSession();
  const { openNewDialog } = useChatLayout();
  const [draft, setDraft] = React.useState("");
  const [aside, setAside] = React.useState(false);

  const active: ChatSessionRecordV1 | undefined = s.sessions.find((x) => x.id === s.activeSessionId);
  const subFile: string =
    s.registry.find((e) => s.selectedProjectIds.includes(e.projectId))?.title ?? "—";

  const groups = React.useMemo(() => groupMessagesForLayout(s.chatLines), [s.chatLines]);

  const addNewChat: () => void = React.useCallback(() => {
    if (s.registry.length === 0) {
      void s.loadProjects();
      openNewDialog();
      return;
    }
    if (s.selectedProjectIds.length === 0) {
      openNewDialog();
      return;
    }
    const n: number = s.sessions.length + 1;
    s.createNewChatSession(s.selectedProjectIds, `Диалог ${n}`);
  }, [openNewDialog, s]);

  return (
    <div className="candyChatRoot" data-candy-chat="1">
      <div className="candyChatHeader">
        <div className="candyChatHeaderLeft">
          <span className="candyChatHeaderTitle">{active ? briefTitle(active, s.registry) : "Чат"}</span>
          <span className="candyChatHeaderRule" />
          <span className="candyChatHeaderSub">{subFile}</span>
        </div>
        <div className="candyChatHeaderRight">
          <button className="candyChatHeaderBtn" type="button" onClick={() => setAside((v) => !v)} title="Аналитика">
            <CandyMaterialIcon name="analytics" />
            <span className="candyChatHeaderBtnText">Аналитика</span>
          </button>
          <button
            className="candyChatHeaderIconBtn"
            type="button"
            onClick={() => void s.loadProjects()}
            title="Обновить registry"
          >
            <CandyMaterialIcon name="sync" />
          </button>
          <button
            className="candyChatHeaderIconBtn"
            type="button"
            onClick={() => void s.connectToBroker()}
            title="Переподключить broker"
          >
            <CandyMaterialIcon name="lan" />
          </button>
        </div>
      </div>

      <ChatSessionTabs
        activeSessionId={s.activeSessionId}
        sessions={s.sessions}
        titleFor={(sess) => briefTitle(sess, s.registry)}
        onAdd={addNewChat}
        onRename={(id, label) => s.renameSession(id, label)}
        onSelect={(id) => s.setActiveSessionId(id)}
      />

      <div className="candyChatSplit">
        <div className="candyChatMainCol">
          {s.lastError ? <div className="candyChatErrBanner">{s.lastError}</div> : null}
          <div className="candyChatScroll">
            <div className="candyChatScrollInner">
              {groups.map((g, gi) => (
                <div className="candyChatGroup" key={`g-${gi}`}>
                  <div className="candyChatGroupHead">
                    {g.kind === "user" ? (
                      <>
                        <div className="candyChatAvatar candyChatAvatarUser" aria-hidden="true">
                          <CandyMaterialIcon name="person" />
                        </div>
                        <span className="candyChatGroupLabel candyChatGroupLabelUser">Вы</span>
                      </>
                    ) : (
                      <>
                        <div className="candyChatAvatar candyChatAvatarAi" aria-hidden="true">
                          <CandyMaterialIcon name="smart_toy" />
                        </div>
                        <span className="candyChatGroupLabel candyChatGroupLabelAi">Ailit</span>
                      </>
                    )}
                  </div>
                  <div className="candyChatGroupBody">
                    {g.items.map((m) => {
                      if (m.lineKind === "console") {
                        return (
                          <CandyChatConsoleBlock
                            key={m.id}
                            shell={m.consoleShell ?? "sh"}
                            text={m.text}
                          />
                        );
                      }
                      return (
                        <div
                          className={
                            m.from === "system" ? "candyChatSystemLine markdownBody" : "candyMsgText markdownBody"
                          }
                          key={m.id}
                        >
                          {m.text}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="candyChatInputWrap">
            <div className="candyChatInputGlow" />
            <div className="candyChatInputBox">
              <div className="candyChatInputRow">
                <button className="candyChatInputAttach" type="button" tabIndex={-1} disabled title="Скоро">
                  <CandyMaterialIcon name="add" />
                </button>
                <textarea
                  className="candyChatTextarea"
                  rows={1}
                  placeholder="Ответьте или введите команду…"
                  value={draft}
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
                  className="candyChatSend"
                  type="button"
                  onClick={() => {
                    const t: string = draft;
                    setDraft("");
                    void s.sendUserPrompt(t);
                  }}
                >
                  <CandyMaterialIcon name="arrow_upward" filled />
                </button>
              </div>
              <div className="candyChatInputMeta">
                <div className="candyChatInputModel">
                  <CandyMaterialIcon name="memory" />
                  <span>ailit</span>
                </div>
                <span className="candyChatInputHint">Shift+Enter — новая строка</span>
              </div>
            </div>
          </div>
        </div>
        {aside ? (
          <ChatAnalyticsAside
            connectionLabel={connectionLabel(s.connection)}
            onClose={() => setAside(false)}
            registry={s.registry}
            selectedProjectIds={s.selectedProjectIds}
          />
        ) : null}
      </div>
    </div>
  );
}
