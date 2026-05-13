# Канон `context/` — индекс

Краткое оглавление knowledge layer. Детальные планы и артефакты итераций — в [`artifacts/`](artifacts/) и [`../plan/`](../plan/), без дублирования сценариев. **Читаемость канона:** для опубликованных target algorithms и для human-facing обновлений в `context/*` (кроме `artifacts/`) действует **CR-CANON** в `.cursor/rules/start-research.mdc`; индексы ниже должны помогать человеку выбрать файл без чтения pipeline-артефактов.

| Раздел | Назначение |
|--------|------------|
| [`install/INDEX.md`](install/INDEX.md) | Установка пользователем: ссылки на SoT `proto/install.md`, `scripts/install`, связь с launch. |
| [`modules/INDEX.md`](modules/INDEX.md) | Логические модули репозитория: пакеты под `tools/` и `desktop/` (npm). |
| [`files/INDEX.md`](files/INDEX.md) | Устойчивые пути: примеры workflow, ключевые пользовательские конфиги `~/.ailit/…`. |
| [`models/INDEX.md`](models/INDEX.md) | Модели/DTO в коде и отсылка к proto-контрактам событий. |
| [`arch/INDEX.md`](arch/INDEX.md) | Процессы и границы: карта P1–P6 (learn), desktop PAG-снимок, W14 M1 и т.д. |
| [`proto/INDEX.md`](proto/INDEX.md) | Каналы: install-ссылки, supervisor socket, desktop↔runtime, pag-slice, W14 highlight, broker Work↔Memory pathless (UC 2.4), D-OBS-1 compact whitelist (`runtime-event-contract.md`); UC-03 CLI `memory init` — [`proto/memory-query-context-init.md`](proto/memory-query-context-init.md); стабильный PAG — [`proto/pag-stable-indexing.md`](proto/pag-stable-indexing.md). |
| [`algorithms/INDEX.md`](algorithms/INDEX.md) | Утверждённые target algorithms: человекочитаемые целевые алгоритмы, которые служат опорой для `start-feature` / `start-fix`. Внутри каталога — пакеты в т.ч. [`agent-memory/`](algorithms/agent-memory/INDEX.md), [`agents/`](algorithms/agents/INDEX.md), [`desktop/`](algorithms/desktop/INDEX.md) (граф памяти в Electron, 3dmvc), [`desktop-stack/`](algorithms/desktop-stack/INDEX.md) (чат, freeze, PAG rev), [`agentwork/`](algorithms/agentwork/index.md) (подпроцесс AgentWork). |
| [`start/INDEX.md`](start/INDEX.md) | Запуск: systemd, dev desktop, pytest/venv, переменные окружения. |
| [`tests/INDEX.md`](tests/INDEX.md) | Точки входа к тестам (pytest, e2e, vitest; W14 UC-05 G14R; финальный gate Memory 3D — отчёты **11** в `artifacts/reports/`). |
| [`memories/index.md`](memories/index.md) | Память итераций feature/learn (index-first). Имя файла — `index.md` (нижний регистр). |
| [`artifacts/`](artifacts/) | Отчёты pipeline, `change_inventory`, задачи. |

**Связанные разделы:** обзор документации репозитория — [`../docs/INDEX.md`](../docs/INDEX.md). Установка и запуск в каноне: [`proto/install.md`](proto/install.md), [`start/repository-launch.md`](start/repository-launch.md).
