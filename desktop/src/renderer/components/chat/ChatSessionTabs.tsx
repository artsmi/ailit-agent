import React from "react";

import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";
import type { ChatSessionRecordV1 } from "../../state/persistedUi";

type ChatSessionTabsProps = {
  readonly sessions: readonly ChatSessionRecordV1[];
  readonly activeSessionId: string;
  readonly titleFor: (s: ChatSessionRecordV1) => string;
  readonly onSelect: (sessionId: string) => void;
  readonly onRename: (sessionId: string, label: string) => void;
  readonly onAdd: () => void;
};

/**
 * Вкладки сессий — pill, как в candy minimalist (скролл по горизонтали с overflow hidden у родителя).
 */
export function ChatSessionTabs(p: ChatSessionTabsProps): React.JSX.Element {
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const skipBlurRename: React.MutableRefObject<boolean> = React.useRef(false);
  return (
    <div className="candyChatTabs" role="tablist" aria-label="Сессии чата">
      <div className="candyChatTabsTrack">
        {p.sessions.map((sess) => {
          const active: boolean = sess.id === p.activeSessionId;
          const title: string = p.titleFor(sess);
          const isEdit: boolean = editingId === sess.id;
          return (
            <div
              className={active ? "candyChatTab candyChatTabActive" : "candyChatTab"}
              key={sess.id}
              role="presentation"
            >
              {isEdit ? (
                <input
                  autoFocus
                  className="candyChatTabInput"
                  type="text"
                  value={draft}
                  aria-label="Название чата"
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => {
                    if (skipBlurRename.current) {
                      skipBlurRename.current = false;
                      return;
                    }
                    p.onRename(sess.id, draft);
                    setEditingId(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.currentTarget.blur();
                    }
                    if (e.key === "Escape") {
                      e.preventDefault();
                      skipBlurRename.current = true;
                      setEditingId(null);
                    }
                  }}
                />
              ) : (
                <button
                  className="candyChatTabBtn"
                  role="tab"
                  type="button"
                  aria-selected={active}
                  onClick={() => p.onSelect(sess.id)}
                  onDoubleClick={(e) => {
                    e.preventDefault();
                    setEditingId(sess.id);
                    setDraft(title);
                  }}
                >
                  <span className="candyChatTabLabel">{title}</span>
                </button>
              )}
            </div>
          );
        })}
        <button className="candyChatTabAdd" type="button" aria-label="Новый чат" onClick={p.onAdd} title="Новый чат">
          <CandyMaterialIcon name="add" />
        </button>
      </div>
    </div>
  );
}
