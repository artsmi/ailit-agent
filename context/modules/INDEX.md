# Модули — индекс

Карта пакетов под `ailit/` (setuptools `packages.find` с `where=["ailit"]`) и отдельного UI-пакета `desktop/`. Процессы P1–P6 и границы — в [`../arch/INDEX.md`](../arch/INDEX.md).

| Документ / элемент | Содержание |
|--------------------|------------|
| `ailit/ailit_base/` | Модели чата, провайдеры LLM, нормализация потоков, HTTP-транспорт, загрузка конфига, shell-security утилиты. |
| `ailit/agent_work/` | Session loop, perm-режимы, инструменты агента (`tool_runtime`), bash-runner и shell session. |
| `ailit/agent_memory/` | PAG/KB SQLite, индексация, пайплайн AgentMemory, журналы инициализации, W14 graph highlight. Подпакеты: `cli/`, `config/`, `contracts/`, `storage/`, `pag/`, `init/`, `query/`, `services/`, `observability/`, `kb/`; каталог `legacy/` — карантин старых C-extraction модулей. Юнит-тесты подсистемы: `ailit/agent_memory/tests/`. |
| `ailit/ailit_runtime/` | Broker, supervisor, Unix-socket IPC, модели runtime-конвертов, subprocess-агенты (AgentWork / AgentMemory worker). |
| `ailit/ailit_cli/` | CLI `ailit` (`cli.py`), подкоманды memory/kb/runtime/desktop/project и merge пользовательского конфига. |
| `ailit/workflow_engine/` | Загрузка и исполнение workflow YAML. |
| `ailit/project_layer/` | Модели и бутстрап слоя проекта. |
| `ailit/config-example/` | Пример дерева `~/.ailit` и комментированные шаблоны конфигурации (см. `STRUCTURE.md`). |
| `desktop/` | Пакет **ailit-desktop** (Electron + renderer): dev через `npm run dev`, typecheck и vitest — см. [`../tests/INDEX.md`](../tests/INDEX.md). **Trace ingress (G19.4):** `renderer/runtime/traceIngressCoalesce.ts`, `traceTerminalKinds.ts`, wiring в `DesktopSessionContext.tsx` — см. [`../arch/desktop-pag-graph-snapshot.md`](../arch/desktop-pag-graph-snapshot.md#live-trace-ingress-coalesce). Компакт-наблюдаемость сессии (OR-D6, план 19 / G19.1): `renderer/runtime/desktopSessionDiagnosticLog.ts`, `desktopSessionTraceThroughputWindow.ts`, `desktopSessionRendererBudgetTelemetry.ts`; main — `registerIpc.ts` (pag slice), `pagGraphBridge.ts`. |

**Связанные разделы:** [`../INDEX.md`](../INDEX.md), [`../arch/INDEX.md`](../arch/INDEX.md), [`../start/INDEX.md`](../start/INDEX.md), [`../files/INDEX.md`](../files/INDEX.md).
