import React from "react";

import {
  agentMemoryChatLogSessionDirPosix,
  agentMemoryVerboseLogAbsolutePathPosix,
  desktopAilitCompactLogAbsolutePathPosix,
  desktopAilitFullLogAbsolutePathPosix,
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
  /** Корень AgentMemory chat_logs (main: AILIT_AGENT_MEMORY_CHAT_LOG_DIR или ~/.ailit/agent-memory/chat_logs). */
  readonly chatLogsRoot: string | null;
  /** ``null`` пока нет ответа IPC; ``false`` — запись в chat_logs отключена в agent-memory config. */
  readonly agentMemoryChatLogsFileTargetsEnabled: boolean | null;
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
  const supSock: string | null = p.runtimeDir ? joinPosixPath(p.runtimeDir, "supervisor.sock") : null;
  const sessionDir: string | null =
    p.chatLogsRoot && p.chatId ? agentMemoryChatLogSessionDirPosix(p.chatLogsRoot, p.chatId) : null;
  const deskFullLog: string | null =
    p.chatLogsRoot && p.chatId ? desktopAilitFullLogAbsolutePathPosix(p.chatLogsRoot, p.chatId) : null;
  const deskCompactLog: string | null =
    p.chatLogsRoot && p.chatId ? desktopAilitCompactLogAbsolutePathPosix(p.chatLogsRoot, p.chatId) : null;
  const agentMemLog: string | null =
    p.chatLogsRoot && p.chatId ? agentMemoryVerboseLogAbsolutePathPosix(p.chatLogsRoot, p.chatId) : null;
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
            Под runtime_dir — durable trace и supervisor; под chat_logs — каталог чата (пара логов Desktop для графа
            и verbose AgentMemory при memory.debug.verbose=1).
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
          {p.chatLogsRoot && sessionDir && deskFullLog && deskCompactLog && agentMemLog ? (
            <ul className="candyChatAsidePathList">
              <li>
                <span className="candyChatAsidePathKey">chat_logs_root</span>
                <code className="candyChatAsidePathVal">{p.chatLogsRoot}</code>
              </li>
              <li>
                <span className="candyChatAsidePathKey">chat_session_dir</span>
                <code className="candyChatAsidePathVal">{sessionDir}</code>
              </li>
              <li>
                <span className="candyChatAsidePathKey">desktop graph full</span>
                <code className="candyChatAsidePathVal">{deskFullLog}</code>
              </li>
              <li>
                <span className="candyChatAsidePathKey">desktop graph compact</span>
                <code className="candyChatAsidePathVal">{deskCompactLog}</code>
              </li>
              <li>
                <span className="candyChatAsidePathKey">agent_memory verbose</span>
                <code className="candyChatAsidePathVal">{agentMemLog}</code>
              </li>
            </ul>
          ) : p.agentMemoryChatLogsFileTargetsEnabled === false ? (
            <p className="candyChatAsideDesc">
              Запись в chat_logs отключена в ~/.ailit/agent-memory/config.yaml (memory.debug.chat_logs_enabled: false).
              Перезапустите Desktop после изменения файла.
            </p>
          ) : (
            <p className="candyChatAsideDesc">Корень chat_logs недоступен из main — перезапустите Desktop.</p>
          )}
        </div>
      </div>
    </aside>
  );
}
