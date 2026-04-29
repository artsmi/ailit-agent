import React from "react";

import {
  agentMemoryChatLogAbsolutePath,
  desktopDiagnosticLogRelativePath,
  joinPosixPath,
  traceJsonlRelativePath
} from "@shared/tracePaths";
import type { ProjectRegistryEntry } from "@shared/ipc";
import { CandyMaterialIcon } from "../../shell/CandyMaterialIcon";

type ChatAnalyticsAsideProps = {
  readonly onClose: () => void;
  readonly registry: readonly ProjectRegistryEntry[];
  readonly selectedProjectIds: readonly string[];
  readonly connectionLabel: string;
  /** Каталог runtime (supervisor / trace). */
  readonly runtimeDir: string | null;
  /** Домашний каталог (для ~/.ailit/agent-memory/chat_logs/…). */
  readonly homeDir: string | null;
  /** Идентификатор чата (файл trace-*.jsonl). */
  readonly chatId: string;
};

/**
 * Правая панель в духе `#right-sidebar` референса: контекст проектов.
 */
export function ChatAnalyticsAside(p: ChatAnalyticsAsideProps): React.JSX.Element {
  const primary: ProjectRegistryEntry | undefined = p.registry.find((e) => p.selectedProjectIds.includes(e.projectId));
  const traceFile: string | null =
    p.runtimeDir && p.chatId
      ? joinPosixPath(p.runtimeDir, traceJsonlRelativePath(p.chatId))
      : null;
  const deskLog: string | null =
    p.runtimeDir && p.chatId
      ? joinPosixPath(p.runtimeDir, desktopDiagnosticLogRelativePath(p.chatId))
      : null;
  const supSock: string | null = p.runtimeDir ? joinPosixPath(p.runtimeDir, "supervisor.sock") : null;
  const agentMemLog: string | null =
    p.homeDir && p.chatId ? agentMemoryChatLogAbsolutePath(p.homeDir, p.chatId) : null;
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
        <div className="candyChatAsideSection">
          <h3 className="candyChatAsideH3">Диагностика (файлы сессии)</h3>
          <p className="candyChatAsideDesc">
            По этим путям — durable trace, журнал десктоп-UI (порядок/проекция событий), сокет supervisor, лог
            AgentMemory (при memory.debug.verbose=1).
          </p>
          {p.runtimeDir ? (
            <ul className="candyChatAsidePathList">
              <li>
                <span className="candyChatAsidePathKey">runtime_dir</span>
                <code className="candyChatAsidePathVal">{p.runtimeDir}</code>
              </li>
              {traceFile ? (
                <li>
                  <span className="candyChatAsidePathKey">trace (JSONL)</span>
                  <code className="candyChatAsidePathVal">{traceFile}</code>
                </li>
              ) : null}
              {deskLog ? (
                <li>
                  <span className="candyChatAsidePathKey">desktop (диагностика чата)</span>
                  <code className="candyChatAsidePathVal">{deskLog}</code>
                </li>
              ) : null}
              {supSock ? (
                <li>
                  <span className="candyChatAsidePathKey">supervisor.sock</span>
                  <code className="candyChatAsidePathVal">{supSock}</code>
                </li>
              ) : null}
            </ul>
          ) : (
            <p className="candyChatAsideDesc">runtime_dir ещё не известен — дождитесь подключения supervisor.</p>
          )}
          {agentMemLog ? (
            <ul className="candyChatAsidePathList">
              <li>
                <span className="candyChatAsidePathKey">agent_memory (LLM, ~/.ailit)</span>
                <code className="candyChatAsidePathVal">{agentMemLog}</code>
              </li>
            </ul>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
