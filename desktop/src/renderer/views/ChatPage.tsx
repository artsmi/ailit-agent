import React, { useLayoutEffect } from "react";

import { CandyChatAgentStatusRow } from "../components/chat/CandyChatAgentStatusRow";
import { CandyChatMemoryRecallStatusRow } from "../components/chat/CandyChatMemoryRecallStatusRow";
import { ChatAnalyticsAside } from "../components/chat/ChatAnalyticsAside";
import { ChatHistoryModal } from "../components/chat/ChatHistoryModal";
import { CandyChatConsoleBlock } from "../components/chat/CandyChatConsoleBlock";
import { CandyMarkdownBody } from "../components/chat/CandyMarkdownBody";
import { ChatSessionTabs } from "../components/chat/ChatSessionTabs";
import { ContextFillPanel } from "../components/chat/ContextFillPanel";
import { useChatLayout } from "../shell/ChatLayoutContext";
import { useDesktopSession, type ChatLine } from "../runtime/DesktopSessionContext";
import type { ChatSessionRecordV1, ChatToolDisplayV1 } from "../state/persistedUi";
import { CandyMaterialIcon } from "../shell/CandyMaterialIcon";
import { PermModeModal } from "../components/chat/PermModeModal";
import { ToolApprovalModal } from "../components/chat/ToolApprovalModal";
import { MemoryJournalPanel } from "../components/chat/MemoryJournalPanel";
import { MemoryGraph3DPage } from "./MemoryGraph3DPage";

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
  const [contextOpen, setContextOpen] = React.useState(false);
  const chatScrollRef: React.RefObject<HTMLDivElement | null> = React.useRef<HTMLDivElement | null>(null);
  const splitRef: React.RefObject<HTMLDivElement | null> = React.useRef<HTMLDivElement | null>(null);
  const stickToBottomRef: React.MutableRefObject<boolean> = React.useRef(true);
  const innerObsRef: React.RefObject<HTMLDivElement | null> = React.useRef<HTMLDivElement | null>(null);

  const active: ChatSessionRecordV1 | undefined = s.sessions.find((x) => x.id === s.activeSessionId);
  const subFile: string =
    s.registry.find((e) => s.selectedProjectIds.includes(e.projectId))?.title ?? "—";

  const visibleChatLines: readonly ChatLine[] = React.useMemo((): readonly ChatLine[] => {
    const ordered: ChatLine[] = [...s.chatLines].sort((a, b) => {
      const d: number = a.order - b.order;
      if (d !== 0) {
        return d;
      }
      return a.atIso.localeCompare(b.atIso);
    });
    if (s.toolDisplay === "hidden") {
      return ordered.filter(
        (m) => m.lineKind !== "console" || m.consoleChannel === undefined || m.consoleChannel !== "tool"
      );
    }
    return ordered;
  }, [s.chatLines, s.toolDisplay]);

  const groups = React.useMemo(() => groupMessagesForLayout(visibleChatLines), [visibleChatLines]);
  const chatPercent: number = s.memoryPanelOpen ? Math.round(s.memorySplitRatio * 1000) / 10 : 100;
  const memoryPercent: number = Math.round((100 - chatPercent) * 10) / 10;

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

  const openAnalytics: () => void = React.useCallback((): void => {
    s.setMemoryPanelOpen(false);
    setAside((v) => !v);
  }, [s]);

  const toggleMemoryPanel: () => void = React.useCallback((): void => {
    const next: boolean = !s.memoryPanelOpen;
    if (next) {
      setAside(false);
    }
    s.setMemoryPanelOpen(next);
  }, [s]);

  const startSplitDrag: (e: React.PointerEvent<HTMLButtonElement>) => void = React.useCallback(
    (e) => {
      const host: HTMLDivElement | null = splitRef.current;
      if (!host) {
        return;
      }
      e.preventDefault();
      const rect: DOMRect = host.getBoundingClientRect();
      const pointerId: number = e.pointerId;
      const target = e.currentTarget;
      target.setPointerCapture(pointerId);
      const onMove = (ev: PointerEvent): void => {
        const ratio: number = (ev.clientX - rect.left) / Math.max(1, rect.width);
        s.setMemorySplitRatio(ratio);
      };
      const onDone = (): void => {
        target.releasePointerCapture(pointerId);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onDone);
        window.removeEventListener("pointercancel", onDone);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onDone);
      window.addEventListener("pointercancel", onDone);
    },
    [s]
  );

  return (
    <div className="candyChatRoot" data-candy-chat="1">
      <div className="candyChatTopChrome">
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
            <button className="candyChatHeaderBtn" type="button" onClick={openAnalytics} title="Аналитика">
              <CandyMaterialIcon name="analytics" />
              <span className="candyChatHeaderBtnText">Аналитика</span>
            </button>
            <button
              className={s.memoryPanelOpen ? "candyChatHeaderBtn candyChatHeaderBtnActive" : "candyChatHeaderBtn"}
              type="button"
              onClick={toggleMemoryPanel}
              title={s.memoryPanelOpen ? "Скрыть Memory" : "Показать Memory"}
            >
              <CandyMaterialIcon name="hub" />
              <span className="candyChatHeaderBtnText">Memory</span>
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
      </div>
      <ChatHistoryModal
        activeSessionId={s.activeSessionId}
        onClose={() => setHistoryOpen(false)}
        onSelect={(id) => s.setActiveSessionId(id)}
        open={historyOpen}
        sessions={s.sessions}
        titleFor={(sess) => briefTitle(sess, s.registry)}
      />

      <div
        className={s.memoryPanelOpen ? "candyChatSplit candyChatSplitMemoryOpen" : "candyChatSplit"}
        ref={splitRef}
      >
        <div className="candyChatMainCol" style={{ flexBasis: s.memoryPanelOpen ? `${chatPercent}%` : undefined }}>
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
                      if (m.lineKind === "plan") {
                        return (
                          <div className="candyChatMicroPlan" key={m.id}>
                            <div className="candyChatMicroPlanLabel">План</div>
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
          {s.brokerMemoryRecallPhase.active ? (
            <CandyChatMemoryRecallStatusRow phase={s.brokerMemoryRecallPhase} />
          ) : (
            <CandyChatAgentStatusRow phase={s.brokerAgentThinkingPhase} />
          )}
          <div className="candyChatInputWrap">
            <div className="candyChatInputGlow" />
            <div className="candyChatInputBox">
              {contextOpen ? (
                <div className="candyChatInputContext">
                  <ContextFillPanel state={s.contextFill} />
                </div>
              ) : null}
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
                      if (s.agentTurnInProgress || s.brokerMemoryRecallPhase.active) {
                        return;
                      }
                      const t: string = draft;
                      setDraft("");
                      stickToBottomRef.current = true;
                      void s.sendUserPrompt(t);
                    }
                  }}
                />
                {s.agentTurnInProgress || s.brokerMemoryRecallPhase.active ? (
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
                  {s.permModeLabel ? (
                    <span className="candyPermBadge" title="Режим perm-5 (agent_core)">
                      perm:{s.permModeLabel}
                    </span>
                  ) : null}
                  <button
                    className="candyContextToggle"
                    type="button"
                    disabled={s.contextFill === null}
                    title={contextOpen ? "Скрыть Context" : "Показать Context"}
                    onClick={() => {
                      setContextOpen((v) => !v);
                    }}
                  >
                    <CandyMaterialIcon name={contextOpen ? "visibility_off" : "data_usage"} />
                    <span>{contextOpen ? "Скрыть Context" : "Показать Context"}</span>
                  </button>
                </div>
                <span className="candyChatInputHint">Shift+Enter — новая строка</span>
              </div>
            </div>
          </div>
        </div>
        <PermModeModal
          open={s.permModeGateId !== null}
          onSelect={(mode, remember) => {
            void s.submitPermModeChoice(mode, remember);
          }}
          onDismiss={() => {
            void s.submitPermModeChoice("explore", false);
          }}
        />
        <ToolApprovalModal
          open={s.toolApproval !== null}
          tool={s.toolApproval?.tool ?? ""}
          callId={s.toolApproval?.callId ?? ""}
          onResolve={(approved) => {
            void s.submitToolApproval(approved);
          }}
          onDismiss={() => {
            void s.submitToolApproval(false);
          }}
        />
        {s.memoryPanelOpen ? (
          <>
            <button
              aria-label="Изменить ширину Memory"
              className="candyMemorySplitter"
              onPointerDown={startSplitDrag}
              type="button"
            />
            <aside className="candyMemoryPanel" style={{ flexBasis: `${memoryPercent}%` }}>
              <div className="candyMemoryPanelHead">
                <div className="candyMemoryPanelTitle">
                  <CandyMaterialIcon name="hub" />
                  <span>Memory</span>
                </div>
                <div className="candyMemoryPanelTabs" role="tablist">
                  <button
                    className={s.memoryPanelTab === "3d" ? "pill memToggleOn" : "pill"}
                    type="button"
                    onClick={() => s.setMemoryPanelTab("3d")}
                  >
                    3D
                  </button>
                  <button
                    className={s.memoryPanelTab === "journal" ? "pill memToggleOn" : "pill"}
                    type="button"
                    onClick={() => s.setMemoryPanelTab("journal")}
                  >
                    Журнал
                  </button>
                </div>
              </div>
              <div className="candyMemoryPanelBody">
                {s.memoryPanelTab === "3d" ? (
                  <MemoryGraph3DPage noInitialAutoZoom />
                ) : (
                  <MemoryJournalPanel chatId={s.chatId} />
                )}
              </div>
            </aside>
          </>
        ) : aside ? (
          <ChatAnalyticsAside
            agentMemoryChatLogsFileTargetsEnabled={s.agentMemoryChatLogsFileTargetsEnabled}
            chatId={s.chatId}
            chatLogsRoot={s.chatLogsRoot}
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
