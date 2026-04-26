import React from "react";

import type { ProjectRegistryEntry } from "@shared/ipc";
import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

type ChatAnalyticsAsideProps = {
  readonly onClose: () => void;
  readonly registry: readonly ProjectRegistryEntry[];
  readonly selectedProjectIds: readonly string[];
  readonly connectionLabel: string;
};

/**
 * Правая панель в духе `#right-sidebar` референса: контекст проектов.
 */
export function ChatAnalyticsAside(p: ChatAnalyticsAsideProps): React.JSX.Element {
  const primary: ProjectRegistryEntry | undefined = p.registry.find((e) => p.selectedProjectIds.includes(e.projectId));
  return (
    <aside className="candyChatAside" aria-label="Аналитика контекста">
      <div className="candyChatAsideHead">
        <h2 className="candyChatAsideTitle">Аналитика контекста</h2>
        <button className="candyChatAsideClose" type="button" onClick={p.onClose} aria-label="Закрыть панель">
          <CandyMaterialIcon name="close" />
        </button>
      </div>
      <div className="candyChatAsideBody">
        <div className="candyChatAsideSection">
          <h3 className="candyChatAsideH3">Текущий проект</h3>
          <div className="candyChatAsideCard">
            {primary ? (
              <>
                <div className="candyChatAsideRow">
                  <CandyMaterialIcon name="developer_board" />
                  <span className="candyChatAsideProjTitle">{primary.title}</span>
                </div>
                <p className="candyChatAsideDesc">{primary.namespace}</p>
              </>
            ) : (
              <p className="candyChatAsideDesc">Проекты не выбраны — создайте диалог с выбором registry.</p>
            )}
          </div>
        </div>
        <div className="candyChatAsideSection">
          <h3 className="candyChatAsideH3">Состояние</h3>
          <div className="candyChatAsidePillRow">
            <span className="candyChatAsidePillLabel">Подключение</span>
            <span className="candyChatAsidePillVal">{p.connectionLabel}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
