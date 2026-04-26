import React from "react";

import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";
import type { ChatSessionRecordV1 } from "../../state/persistedUi";

type ChatSessionTabsProps = {
  readonly sessions: readonly ChatSessionRecordV1[];
  readonly activeSessionId: string;
  readonly titleFor: (s: ChatSessionRecordV1) => string;
  readonly onSelect: (sessionId: string) => void;
  readonly onRename: (sessionId: string, label: string) => void;
  readonly onRemove: (sessionId: string) => void;
  readonly onAdd: () => void;
  readonly onOpenHistory: () => void;
};

type MenuState = { readonly x: number; readonly y: number; readonly sessionId: string } | null;

/**
 * Вкладки сессий — pill, как в candy minimalist (скролл по горизонтали с overflow hidden у родителя).
 */
export function ChatSessionTabs(p: ChatSessionTabsProps): React.JSX.Element {
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const [menu, setMenu] = React.useState<MenuState>(null);
  const skipBlurRename: React.MutableRefObject<boolean> = React.useRef(false);

  React.useEffect((): (() => void) | void => {
    if (menu === null) {
      return;
    }
    let onDoc: (() => void) | null = null;
    const t: number = window.setTimeout((): void => {
      onDoc = (): void => {
        setMenu(null);
      };
      globalThis.document.addEventListener("click", onDoc);
    }, 0);
    return () => {
      window.clearTimeout(t);
      if (onDoc) {
        globalThis.document.removeEventListener("click", onDoc);
      }
    };
  }, [menu]);

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
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setMenu({ x: e.clientX, y: e.clientY, sessionId: sess.id });
                  }}
                >
                  <span className="candyChatTabLabel">{title}</span>
                </button>
              )}
            </div>
          );
        })}
        <button
          className="candyChatTabAdd candyChatTabHistory"
          type="button"
          aria-label="История чатов"
          onClick={p.onOpenHistory}
          title="История чатов"
        >
          <CandyMaterialIcon name="history" />
        </button>
        <button className="candyChatTabAdd" type="button" aria-label="Новый чат" onClick={p.onAdd} title="Новый чат">
          <CandyMaterialIcon name="add" />
        </button>
      </div>
      {menu ? (
        <ul
          className="candyChatCtxMenu"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          <li>
            <button
              className="candyChatCtxItem"
              type="button"
              onClick={() => {
                const s: ChatSessionRecordV1 | undefined = p.sessions.find((x) => x.id === menu.sessionId);
                if (s) {
                  setEditingId(s.id);
                  setDraft(p.titleFor(s));
                }
                setMenu(null);
              }}
            >
              Переименовать
            </button>
          </li>
          <li>
            <button
              className="candyChatCtxItem"
              type="button"
              onClick={() => {
                p.onRemove(menu.sessionId);
                setMenu(null);
              }}
            >
              Удалить чат
            </button>
          </li>
        </ul>
      ) : null}
    </div>
  );
}
