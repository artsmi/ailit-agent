import React, { useLayoutEffect } from "react";

import { CandyChatAgentStatusRow } from "../components/chat/CandyChatAgentStatusRow";
import { ChatAnalyticsAside } from "../components/chat/ChatAnalyticsAside";
import { ChatHistoryModal } from "../components/chat/ChatHistoryModal";
import { CandyChatConsoleBlock } from "../components/chat/CandyChatConsoleBlock";
import { CandyMarkdownBody } from "../components/chat/CandyMarkdownBody";
import { ChatSessionTabs } from "../components/chat/ChatSessionTabs";
import { useChatLayout } from "../shell/ChatLayoutContext";
import { useDesktopSession, type ChatLine } from "../runtime/DesktopSessionContext";
import type { ChatSessionRecordV1, ChatToolDisplayV1 } from "../state/persistedUi";
import { CandyMaterialIcon } from "../shell/CandyMaterialIcon";

/** Считаем «у низа», если до низа осталось не больше (px) — погрешность sub-pixel/scroll. */
const NEAR_BOTTOM_PX: number = 32;

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
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const chatScrollRef: React.RefObject<HTMLDivElement | null> = React.useRef<HTMLDivElement | null>(null);
  const stickToBottomRef: React.MutableRefObject<boolean> = React.useRef(true);
  const innerObsRef: React.RefObject<HTMLDivElement | null> = React.useRef<HTMLDivElement | null>(null);

  const active: ChatSessionRecordV1 | undefined = s.sessions.find((x) => x.id === s.activeSessionId);
  const subFile: string =
    s.registry.find((e) => s.selectedProjectIds.includes(e.projectId))?.title ?? "—";

  const visibleChatLines: readonly ChatLine[] = React.useMemo((): readonly ChatLine[] => {
    const ordered: ChatLine[] = [...s.chatLines].sort((a, b) => a.order - b.order);
    if (s.toolDisplay === "hidden") {
      return ordered.filter(
        (m) => m.lineKind !== "console" || m.consoleChannel === undefined || m.consoleChannel !== "tool"
      );
    }
    return ordered;
  }, [s.chatLines, s.toolDisplay]);

  const groups = React.useMemo(() => groupMessagesForLayout(visibleChatLines), [visibleChatLines]);

  const recomputeStickFromScroller: () => void = React.useCallback((): void => {
    const scroller: HTMLDivElement | null = chatScrollRef.current;
    if (!scroller) {
      return;
    }
    if (scroller.scrollHeight <= scroller.clientHeight + 1) {
      stickToBottomRef.current = true;
      return;
    }
    const gap: number = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop;
    stickToBottomRef.current = gap <= NEAR_BOTTOM_PX;
  }, []);

  const scrollToBottom: () => void = React.useCallback((): void => {
    const scroller: HTMLDivElement | null = chatScrollRef.current;
    if (!scroller) {
      return;
    }
    scroller.scrollTop = scroller.scrollHeight;
  }, []);

  React.useEffect((): (() => void) | void => {
    const scroller: HTMLDivElement | null = chatScrollRef.current;
    if (!scroller) {
      return;
    }
    const onScroll: () => void = (): void => {
      recomputeStickFromScroller();
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    recomputeStickFromScroller();
    return () => {
      scroller.removeEventListener("scroll", onScroll);
    };
  }, [recomputeStickFromScroller, s.activeSessionId, aside, visibleChatLines.length]);

  React.useEffect((): (() => void) | void => {
    const inner: HTMLDivElement | null = innerObsRef.current;
    if (!inner || typeof ResizeObserver === "undefined") {
      return;
    }
    const ro: ResizeObserver = new ResizeObserver(() => {
      if (stickToBottomRef.current) {
        requestAnimationFrame(() => {
          scrollToBottom();
          recomputeStickFromScroller();
        });
      }
    });
    ro.observe(inner);
    return () => {
      ro.disconnect();
    };
  }, [recomputeStickFromScroller, scrollToBottom, s.activeSessionId, visibleChatLines.length, aside]);

  const chatStreamSig: string = React.useMemo((): string => {
    return visibleChatLines
      .map((m) => `${m.id}\t${m.text.length}\t${(m.text || "").slice(-40)}`)
      .join("\n");
  }, [visibleChatLines]);

  useLayoutEffect((): (() => void) | void => {
    if (!stickToBottomRef.current) {
      return;
    }
    scrollToBottom();
    const raf0: number = requestAnimationFrame(() => {
      scrollToBottom();
      recomputeStickFromScroller();
    });
    return () => {
      cancelAnimationFrame(raf0);
    };
  }, [chatStreamSig, groups.length, aside, s.activeSessionId, s.lastError, s.agentTurnInProgress, scrollToBottom, recomputeStickFromScroller]);

  React.useEffect((): void => {
    stickToBottomRef.current = true;
  }, [s.activeSessionId]);

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
          <label className="candyChatHeaderToolMode">
            <span className="candyChatHeaderToolModeLabel">tool</span>
            <select
              className="candyChatHeaderToolModeSelect"
              value={s.toolDisplay}
              title="Отображение вызовов tool.* в чате"
              onChange={(e) => s.setToolDisplay(e.target.value as ChatToolDisplayV1)}
            >
              <option value="normal">как в логе</option>
              <option value="compact">мелко</option>
              <option value="hidden">скрыть</option>
            </select>
          </label>
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
        onOpenHistory={() => setHistoryOpen(true)}
        onRemove={s.removeSession}
        onRename={(id, label) => s.renameSession(id, label)}
        onSelect={(id) => s.setActiveSessionId(id)}
      />
      <ChatHistoryModal
        activeSessionId={s.activeSessionId}
        onClose={() => setHistoryOpen(false)}
        onSelect={(id) => s.setActiveSessionId(id)}
        open={historyOpen}
        sessions={s.sessions}
        titleFor={(sess) => briefTitle(sess, s.registry)}
      />

      <div className="candyChatSplit">
        <div className="candyChatMainCol">
          {s.lastError ? <div className="candyChatErrBanner">{s.lastError}</div> : null}
          <div className="candyChatScroll" ref={chatScrollRef}>
            <div className="candyChatScrollInner" ref={innerObsRef}>
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
                        const compact: boolean = s.toolDisplay === "compact" && m.consoleChannel === "tool";
                        return (
                          <CandyChatConsoleBlock
                            key={m.id}
                            shell={m.consoleShell ?? "sh"}
                            text={m.text}
                            variant={compact ? "compact" : "normal"}
                          />
                        );
                      }
                      if (m.lineKind === "reasoning") {
                        return (
                          <div className="candyChatReasoning" key={m.id}>
                            <div className="candyChatReasoningLabel">Мысли</div>
                            <CandyMarkdownBody text={m.text} />
                          </div>
                        );
                      }
                      return (
                        <div
                          className={m.from === "system" ? "candyChatSystemBlock" : "candyMsgBlock"}
                          key={m.id}
                        >
                          <CandyMarkdownBody text={m.text} />
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <CandyChatAgentStatusRow active={s.agentTurnInProgress} />
          <div className="candyChatInputWrap">
            <div className="candyChatInputGlow" />
            <div className="candyChatInputBox">
              <div className="candyChatInputRow">
                <button className="candyChatInputAttach" type="button" tabIndex={-1} disabled title="Скоро">
                  <CandyMaterialIcon name="add" />
                </button>
                <textarea
                  className="candyChatTextarea"
                  rows={2}
                  placeholder="Ответьте или введите команду…"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      if (s.agentTurnInProgress) {
                        return;
                      }
                      const t: string = draft;
                      setDraft("");
                      stickToBottomRef.current = true;
                      void s.sendUserPrompt(t);
                    }
                  }}
                />
                {s.agentTurnInProgress ? (
                  <button
                    className="candyChatSend candyChatSendStop"
                    type="button"
                    title="Остановить"
                    aria-label="Остановить"
                    onClick={() => {
                      void s.requestStopAgent();
                    }}
                  >
                    <CandyMaterialIcon name="stop" filled />
                  </button>
                ) : (
                  <button
                    className="candyChatSend"
                    type="button"
                    aria-label="Отправить"
                    onClick={() => {
                      const t: string = draft;
                      if (!t.trim()) {
                        return;
                      }
                      setDraft("");
                      stickToBottomRef.current = true;
                      void s.sendUserPrompt(t);
                    }}
                  >
                    <CandyMaterialIcon name="arrow_upward" filled />
                  </button>
                )}
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
            chatId={s.chatId}
            connectionLabel={connectionLabel(s.connection)}
            onClose={() => setAside(false)}
            registry={s.registry}
            runtimeDir={s.runtimeDir}
            selectedProjectIds={s.selectedProjectIds}
          />
        ) : null}
      </div>
    </div>
  );
}
