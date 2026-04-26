import React from "react";

import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";
import type { ChatSessionRecordV1 } from "../../state/persistedUi";

type ChatHistoryModalProps = {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly sessions: readonly ChatSessionRecordV1[];
  readonly activeSessionId: string;
  readonly titleFor: (s: ChatSessionRecordV1) => string;
  readonly onSelect: (sessionId: string) => void;
};

/**
 * Список всех диалогов для переключения (тот же набор, что и вкладки).
 */
export function ChatHistoryModal(p: ChatHistoryModalProps): React.JSX.Element | null {
  if (!p.open) {
    return null;
  }
  return (
    <div
      className="candyChatModalOverlay"
      role="dialog"
      aria-modal="true"
      aria-label="История чатов"
      onClick={p.onClose}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          p.onClose();
        }
      }}
    >
      <div
        className="candyChatModal"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        <div className="candyChatModalHead">
          <h2 className="candyChatModalTitle">История чатов</h2>
          <button className="candyChatModalClose" type="button" onClick={p.onClose} aria-label="Закрыть">
            <CandyMaterialIcon name="close" />
          </button>
        </div>
        <p className="candyChatModalHint">Выберите диалог — откроется в области чата.</p>
        <ul className="candyChatModalList">
          {p.sessions.map((s) => {
            const title: string = p.titleFor(s);
            const active: boolean = s.id === p.activeSessionId;
            return (
              <li key={s.id}>
                <button
                  className={active ? "candyChatModalRow candyChatModalRowActive" : "candyChatModalRow"}
                  type="button"
                  onClick={() => {
                    p.onSelect(s.id);
                    p.onClose();
                  }}
                >
                  <span className="candyChatModalRowTitle">{title}</span>
                  <span className="candyChatModalRowMeta">
                    {new Date(s.createdAt).toLocaleString()}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
