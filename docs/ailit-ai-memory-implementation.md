# Реализация AI memory / токен-экономии в ailit (снимок на 2026-04)

Канон планов: [`plan/workflow-token-economy-recipe.md`](../plan/workflow-token-economy-recipe.md) →
[`plan/workflow-hybrid-memory-mcp.md`](../plan/workflow-hybrid-memory-mcp.md) →
[`plan/workflow-memory-3.md`](../plan/workflow-memory-3.md) (**workflow M3 по документации завершён**, см. README и конец `workflow-memory-3`).

Дополнительно: [`plan/m3-governance.md`](../plan/m3-governance.md),
[`plan/m3-acceleration-layer.md`](../plan/m3-acceleration-layer.md),
[`plan/m3-evaluation-suite.md`](../plan/m3-evaluation-suite.md).

---

## 1. Назначение документа

Здесь зафиксировано **что именно сделано в репозитории** (код, CLI, события, отчёты),
**сопоставление с донорами** из `workflow-memory-3` (по плану и ожиданиям; без обязательного line-by-line аудита чужого кода при каждом релизе), и **честные пробелы** относительно идеалов доноров.

Пути к локальным клонам доноров — как в
[`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc) и в `workflow-memory-3` §доноры.

---

## 2. Что реализовано (код и артефакты)

### 2.1. Токен-экономия и «обвязка» сессии (TE / W-TE)

| Механизм | Где в коде | События / заметки |
|----------|------------|-------------------|
| Context pager (страницы вместо простынь tool output) | `agent_core.session.context_pager`, встраивание в `SessionRunner` | `context.pager.page_created`, `context.pager.page_used` |
| Tool output budget / prune | `agent_core.session.tool_output_budget`, `tool_output_prune` | `tool.output_budget.*`, `tool.output_prune.*` |
| Compaction сообщений | `agent_core.session.compaction` | — |
| Selective **tool exposure** (режимы `full` / `read_only` / `fs` и т.д.) | `agent_core.session.tool_exposure` | `tool.exposure.applied` (`schema_chars`, `schema_chars_full`, `schema_savings`) |
| **Unified session summary** (один объект на лог) | `tools/ailit/token_economy_aggregates.build_session_summary`, CLI `ailit session usage summary` | контракт `ailit_session_summary_v1`, поле `subsystems` |
| Прокси-метрики M3-5.2 | `build_m3_eval_signals` | поле `m3_eval_signals` в summary |
| **fs.read_file** наблюдаемость (range) | `SessionRunner._emit_fs_read_file_completed` | `fs.read_file.completed` (`path_tail`, `offset_line`, `limit_line`, `range_read`) |
| **Post-compaction restore** | `agent_core.session.post_compact_restore.RecentFileReadStore` + опции `SessionSettings.post_compact_*` | `compaction.restore_files` |

### 2.2. Локальная KB (hybrid memory, local-first)

| Компонент | Где | Описание |
|-----------|-----|----------|
| SQLite | `agent_core.memory.sqlite_kb.SqliteKb` | Таблица `kb_records`, поля M3: `memory_layer`, `valid_from`/`valid_to`, `supersedes_id`, `source`, `episode_id`, `promotion_status` |
| Инструменты | `agent_core.memory.kb_tools.build_kb_tool_registry` | `kb_search` (LIKE), `kb_fetch`, `kb_write_fact`, **`kb_promote`** |
| Политика promotion | `agent_core.memory.promotion_policy` | Жёсткие переходы `draft` → `reviewed` → `promoted` и т.д. |
| Включение | `AILIT_KB`, `AILIT_KB_DB_PATH`, `AILIT_KB_NAMESPACE` | См. `kb_tools.kb_tools_config_from_env` |

### 2.3. File tools и чтение по range

- `read_file` с `offset` / `limit` (1-based строки): `agent_core.tool_runtime.builtins.builtin_read_file`, `read_file_text_slice` в `workdir_paths.py`.
- Системные подсказки в Streamlit-чате: `ailit/chat_app.py` — фрагменты про `grep` и **не читать гигантские файлы целиком без range** (E2E-M3-01).

### 2.4. События и память в JSONL

- `memory.access` (без полного body; для `kb_*` аргументы в `tool.call_started` редактируются, см. `SessionRunner._safe_arguments_json`).
- `memory.promotion.applied` / `memory.promotion.denied` — после `kb_promote` / отказа write по promotion.
- Счётчики в `ailit.token_economy_aggregates.merge_events_into_cumulative` и **единый** отчёт `build_session_summary` (включая `memory` / `fs` / `tool_exposure` в `subsystems`).

### 2.5. UI

- `ailit chat` (Streamlit): накопление token-economy caption, **unified summary** expander (JSON как `summary --json`), путь к логу, подсказка CLI.
- `ailit session usage …` — подсистемы: `tokens`, `pager`, `budget`, `prune`, `compaction`, `memory`, `exposure`, **`fs`**.

---

## 3. Сопоставление с донорами: реализовано / слабее / сильнее

Ориентиры перечислены в `workflow-memory-3` (Claude Code, OpenCode, context-mode, RuFlo, ai-multi-agents, Graphiti, Hindsight/Letta). Ниже — **содержательное** сравнение к текущему ailit.

### 3.1. Claude Code (`claude-code`)

| Тема донора | В ailit | Оценка |
|-------------|---------|--------|
| Post-compact **restore** недавно прочитанных файлов | `RecentFileReadStore`, system-сообщение с маркерами `path/offset/limit` | **Близко** по идее; **проще** бюджет/эвристики, чем полноразмерный product |
| `readFileInRange` + метрики | `read_file` + `fs.read_file.completed`; метрики в агрегатах / `m3_eval_signals` | **Сопоставимо** по range; **нет** такого же плотного per-read лог-ивента как в FileReadTool.ts без расширения схемы |
| Слойная сборка system prompt (override/…) | project layer + `merge_with_base_system`, фрагменты в `chat_app` | **Слабее** по богатству слоёв, **проще** в поддержке |

### 3.2. OpenCode (`opencode`)

| Тема | В ailit | Оценка |
|------|---------|--------|
| Модульные `.txt` промпты по провайдеру | в основном код/Python | **Слабее** по модульности промптов |
| Typed **event bus** | `SessionRunner._emit` + `event_type` в JSONL; не отдельная библиотечная шина | **Проще**, **слабее** типобезопасностью в compile-time |
| **Плюс:** сессия и `ailit` CLI предсказуемы, логи читаются grep’ом | | |

### 3.3. context-mode

| Тема | В ailit | Оценка |
|------|---------|--------|
| **One unified report** (`FullReport`, «ONE call») | `build_session_summary` + `contract: ailit_session_summary_v1` + `subsystems` + `m3_eval_signals` | **Цель достигнута** в духе «один вызов на файл лога» |
| DB analytics | нет встроенного sidecar-DB в отчёте; есть cumulative из **событий** сессии | **Уже** для TE/M3, **без** отдельного SQL analytics store как у донора (если он отличается) |

### 3.4. RuFlo (`ruflo`)

| Тема | В ailit | Оценка |
|------|---------|--------|
| Пять отдельных **компонентов** governance (BudgetManager, …) | pager/budget/prune/exposure **есть**; **нет** отдельных одноимённых классов-продуктов, логика распределена по `session/*` | **Слабее** как «именованный продуктовый набор»; **сопоставимо** по эффекту в runtime |
| **index → fetch-by-id → full** как политика | KB: `kb_search` → `kb_fetch`; file: list/glob/grep → `read_file` | **Сходство по потоку**; **без** семейного индекса tools (см. ниже) |
| Staged **family index → tool detail** | **Нет** multi-step progressive disclosure: exposure — **режим целиком** (full/ro/fs) | **Слабее** ruflo/claude в части **поэтапного** раскрытия tool-схем (E2E-M3-04: метрика savings **есть**, механика **не** family+invoke) |

### 3.5. ai-multi-agents (`ai-memory.md` и планы)

| Тема | В ailit | Оценка |
|------|---------|--------|
| Файлы = SoT, DB = acceleration | зафиксировано в `plan/m3-acceleration-layer.md` + SQLite KB как ускоритель | **Согласовано** с планом; **не** весь org-scope vault |
| **Плюс:** реализация KB **явная** в `ailit` без зависимости от внешней оболочки | | |

### 3.6. Graphiti

| Тема | В ailit | Оценка |
|------|---------|--------|
| **Temporal** facts, validity, **superseded** | `valid_from`/`valid_to`, `supersedes_id`, статус `superseded` в `SqliteKb` | **Частично** близко; **нет** графа зависимостей и **нет** встроенного **episode graph** уровня Graphiti |
| Hybrid retrieval (vector + graph + …) | `kb_search` = **LIKE** по title/summary/body | **Слабее**; orchestration M3-3.1 **не** реализована в полном виде |

### 3.7. Hindsight / Letta

| Тема | В ailit | Оценка |
|------|---------|--------|
| Обучаемая / блоковая долговременная память | KB + promotion + `m3_eval_signals` (прокси) | **Нет** аналога обучаемой модели Hindsight; **есть** управляемая запись фактов и policy |

---

## 4. Сводка: сильные и слабые стороны ailit (коротко)

**Сильнее / удачно относительно доноров (в рамках repo):**

- Единый **путь отчёта** по сессии (`summary --json`, Streamlit) и явные **счётчики** (TE + memory + fs + exposure savings).
- **Governance promotion в коде** (отдельный `kb_promote`, нельзя «пролезть» reviewed через write) — чёткость, которую не везде дают в примерах.
- **Локальность и воспроизводимость**: pytest, JSONL, без обязательного внешнего MCP для базового сценария.
- **Документация** в `plan/m3-*.md` + этот файл — связка «план — код — метрика».

**Слабее / не сделано в духе полного M3 постановки:**

- **Retrieval orchestration** (несколько стратегий, cost-aware ranker): сейчас **keyword/LIKE** в KB.
- **Progressive tool disclosure** (family → detail): только **селектор режима** exposure, без динамического расширения family по запросу.
- **Typed event bus** и **модульные provider prompts** — не целевой уровень зрелости.
- **Recall/precision/stale rate** — только **offline/ручной** путь; в JSON — **прокси** `m3_eval_signals`, не gold-метрики.
- M3-0.1 **формальная** «gap matrix» по всем донорам в одной таблице-файле — **закрывается** этим документом + планом как **сводом**, а не отдельным `m3-gap-matrix.xlsx`.

---

## 5. Ключевые файлы (навигация)

| Назначение | Путь |
|------------|------|
| Session loop, события, restore, read_file observe | `tools/agent_core/session/loop.py` |
| Post-compact | `tools/agent_core/session/post_compact_restore.py` |
| Tool exposure | `tools/agent_core/session/tool_exposure.py` |
| Кumulative / summary / `m3_eval_signals` | `tools/ailit/token_economy_aggregates.py` |
| CLI session usage | `tools/ailit/session_usage_cli.py` |
| KB + tools | `tools/agent_core/memory/kb_tools.py`, `sqlite_kb.py`, `promotion_policy.py` |
| Streamlit chat, подсказки, unified panel | `tools/ailit/chat_app.py` |

---

## 6. Проверки (что гонять локально)

```bash
PYTHONPATH=tools python3 -m pytest -q --ignore=tests/e2e/
ailit session usage summary /path/to/ailit-*.log --json | head
```

E2E-сценарии M3: см. §5.1 в [`plan/workflow-memory-3.md`](../plan/workflow-memory-3.md) — **ручные** чек-листы.

---

## 7. Что дальше (вне завершения workflow M3)

- Новая **постановка** после [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc): graph/MCP, векторный поиск, progressive tools, org-scope vault — **только** с отдельным plan/workflow, без расширения scope «молча».

---

*Версия документа: 2026-04-22. Согласуется с завершением workflow M3 в README.*
