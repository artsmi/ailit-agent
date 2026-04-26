import React from "react";

import type { ProjectRegistryEntry } from "@shared/ipc";

import rawModalStyles from "./NewDialogModal.module.css";

const M: Record<string, string> = rawModalStyles as unknown as Record<string, string>;

type Props = {
  readonly open: boolean;
  readonly onClose: () => void;
  /** Не пусто: минимум одна отметка. */
  readonly onCreate: (projectIds: readonly string[]) => void;
  readonly projects: readonly ProjectRegistryEntry[];
};

/**
 * «Новый диалог» — мультивыбор проектов, затем новая сессия.
 */
export function NewDialogModal(p: Props): React.JSX.Element | null {
  const [sel, setSel] = React.useState<Set<string>>(() => new Set());
  React.useEffect(() => {
    if (p.open && p.projects.length > 0) {
      const first: string = p.projects[0]!.projectId;
      setSel((prev) => {
        if (prev.size > 0) {
          return new Set(
            [...prev].filter((id) => p.projects.some((e) => e.projectId === id))
          );
        }
        return new Set([first]);
      });
    }
  }, [p.open, p.projects]);

  if (!p.open) {
    return null;
  }

  function flip(id: string): void {
    setSel((s) => {
      const n: Set<string> = new Set(s);
      if (n.has(id)) {
        if (n.size <= 1) {
          return n;
        }
        n.delete(id);
      } else {
        n.add(id);
      }
      return n;
    });
  }

  return (
    <div aria-modal className={M["scrim"]} onClick={p.onClose} role="presentation">
      <div
        className={M["card"]}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={() => {
          /* handled by form */
        }}
        role="dialog"
      >
        <div className={M["t"]}>Новый диалог</div>
        <p className={M["sub"]}>Проекты</p>
        <ul className={M["list"]}>
          {p.projects.map((e) => {
            const on: boolean = sel.has(e.projectId);
            return (
              <li key={e.projectId} className={M["row"]}>
                <label className={M["label"]}>
                  <input checked={on} onChange={() => flip(e.projectId)} type="checkbox" />
                  <span className={M["name"]}>{e.title}</span>
                  <span className={M["ns"]}>{e.namespace}</span>
                </label>
              </li>
            );
          })}
        </ul>
        {p.projects.length === 0 ? <div className={M["hint"]}>Нет проектов</div> : null}
        <div className={M["actions"]}>
          <button className="secondaryButton" type="button" onClick={p.onClose}>
            Отмена
          </button>
          <button
            className="primaryButton"
            disabled={sel.size === 0}
            type="button"
            onClick={() => {
              if (sel.size === 0) {
                return;
              }
              p.onCreate([...sel]);
            }}
          >
            Открыть чат
          </button>
        </div>
      </div>
    </div>
  );
}
