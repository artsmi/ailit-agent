# Модули — индекс

Карта пакетов под `tools/` (setuptools `packages.find` с `where=["tools"]`) и отдельного UI-пакета `desktop/`. Процессы P1–P6 и границы — в [`../arch/INDEX.md`](../arch/INDEX.md).

| Документ / элемент | Содержание |
|--------------------|------------|
| `tools/agent_core/` | Runtime broker/supervisor, memory/PAG/KB, session loop, инструменты агента. |
| `tools/ailit/` | CLI (`cli.py`), подкоманды chat/tui/desktop/runtime. |
| `tools/workflow_engine/` | Загрузка и исполнение workflow YAML. |
| `tools/project_layer/` | Модели и бутстрап слоя проекта. |
| `desktop/` | Пакет **ailit-desktop** (Electron + renderer): dev через `npm run dev`, typecheck и vitest — см. [`../tests/INDEX.md`](../tests/INDEX.md). Компакт-наблюдаемость сессии (OR-D6, план 19 / G19.1): `renderer/runtime/desktopSessionDiagnosticLog.ts`, `desktopSessionTraceThroughputWindow.ts`, `desktopSessionRendererBudgetTelemetry.ts`; main — `registerIpc.ts` (pag slice), `pagGraphBridge.ts`. |

**Связанные разделы:** [`../INDEX.md`](../INDEX.md), [`../arch/INDEX.md`](../arch/INDEX.md), [`../start/INDEX.md`](../start/INDEX.md), [`../files/INDEX.md`](../files/INDEX.md).
