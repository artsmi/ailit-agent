# Workflow: read-improve (#6) — progressive disclosure чтения + эффективность памяти (M4)

Документ — **целевой workflow** для итераций по репозиторию `ailit-agent`: этапы → задачи → **критерии приёмки** → проверки. Закрывает две связанные цели:

1. **Чтение кода:** не весь файл, а **нужные диапазоны строк**; **index-first** (`grep` → номера строк → `read_file(offset, limit)`), измеримость и защита от регресса.
2. **Память (KB / M4):** модель и рантайм должны **сначала** использовать уже записанные факты (`kb_search` / `kb_fetch`), а обход диска (`list_dir` / `glob_file` / полные `read_file`) — когда индекса недостаточно; **между сессиями** — стабильный namespace и осмысленный retrieval.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc). Перед итерацией агент **открывает** соответствующий этап и фиксирует закрываемые подзадачи; после логического блока — **отдельный коммит** (префикс `R0`…`R4` или `read-6/…`).

## Положение в графе планов

| Зависимость | Документ |
|-------------|----------|
| Токены, сырой дамп | [`plan/workflow-token-economy-recipe.md`](workflow-token-economy-recipe.md) |
| M3/M4 runtime-память (уже в коде) | [`plan/workflow-memory-4.md`](workflow-memory-4.md) |
| Режимы tools | [`plan/5-workflow-perm.md`](5-workflow-perm.md) |

**Идентификатор workflow:** `read-6` (файл `plan/6-read-improve-strategy.md`).

---

## Наблюдения из логов (якорь для R4)

Реальные прогоны `ailit chat` на одном workdir (`not_git`, namespace по path) показали:

- После **auto-write** в KB (`repo_entrypoints`, `repo_tree_root`, …) вторая сессия с тем же вопросом («точки входа») всё равно ушла в **`list_dir` + много `glob_file`** вместо **`kb_fetch`** по id факта — **лишние токены** и низкий «сигнал KB» в метриках.
- Оценка **«Память (M3/M4): N/100»** в UI — **эвристика** `build_memory_efficiency_score` в `tools/ailit/token_economy_aggregates.py`: сильно штрафует отсутствие **`fs_read_file_range_calls`** (при нуле range-read вклад `read_range_discipline` падает до ~14/28) и поощряет частые `memory.access` по **`kb_*`**. Низкий балл **не** означает «KB сломана», но означает «дисциплина чтения и плотность обращения к инструментам памяти слабые».
- Репозиторий **без git**: `default_branch_source: not_git` — match остаётся **path-namespace**; **branch/commit** для политик retrieval нет (ожидаемо слабее, чем в клоне с `origin`).

Эти пункты **не дублируют** постановку M4 в `workflow-memory-4.md`, а задают **продуктовые фиксы** (подсказки, UI-прозрачность, приоритеты), чтобы поведение модели совпадало с уже записанной памятью.

---

## Доноры (без копипаста; только ориентиры)

### Чтение диапазонов и индекс

| Репозиторий | Путь (локально) | Что взять |
|---------------|-----------------|-----------|
| Claude Code | `/home/artem/reps/claude-code` | `FileReadTool` / `readFileInRange`, вложения `@file#L10-20` — см. ссылки в §ниже. |
| OpenCode | `/home/artem/reps/opencode` | Документация `read` с line ranges, API find с `line_number` — см. ссылки в §ниже. |

### Память между сессиями (идеи, не копипаста)

| Репозиторий | Путь (локально) | Что взять |
|---------------|-----------------|-----------|
| Letta | `/home/artem/reps/letta` | **Memory blocks** / явная инъекция краткого state в контекст шага. |
| Graphiti | `/home/artem/reps/graphiti` | Временные графы + **hybrid retrieval** (сущности ↔ текст). |
| Hindsight | `/home/artem/reps/hindsight` | Долговременная память с API (не только чат). |
| obsidian-memory-mcp | `/home/artem/reps/obsidian-memory-mcp` | Vault, `[[links]]`, **навигация** по знаниям как внешняя «память». |
| ruflo / context-mode | `/home/artem/reps/ruflo`, `/home/artem/reps/context-mode` | Сжатие контекста, вынос фактов. |

**Вывод для `ailit`:** «между сессиями» у нас уже есть **Sqlite KB + namespace repo**. Улучшения: (1) **сборка** фактов при старте хода из уже сматченных `memory.retrieval.match`; (2) **промпты** «если вопрос совпадает с типом авто-факта (entrypoints) — сначала `kb_search`/`kb_fetch`»; (3) опционально **git** в проекте пользователя — для `repo_uri` / branch в namespace.

---

## Что уже есть в коде (коротко)

`read_file` с `offset`/`limit`, дедуп, схема `ToolSpec` — см. в документе зафиксированные ссылки (актуальные пути в репозитории `ailit-agent`):

```57:70:tools/agent_core/tool_runtime/builtins.py
def builtin_read_file(arguments: Mapping[str, Any]) -> str:
    ...
```

```146:176:tools/agent_core/tool_runtime/workdir_paths.py
def read_file_text_slice(
```

Событие `fs.read_file.completed` с `range_read` уже пишет диагностику; агрегат **`fs_read_file_range_calls`** влияет на оценку в `build_memory_efficiency_score` (см. `tools/ailit/token_economy_aggregates.py`).

---

## Доноры: ссылки на строки (как в M4-стиле)

### Claude Code: чтение в диапазоне

```1019:1055:/home/artem/reps/claude-code/tools/FileReadTool/FileReadTool.ts
// readFileInRange, lineOffset, data.numLines, startLine ...
```

```2757:2765:/home/artem/reps/claude-code/utils/attachments.ts
// @file.txt#L10-20
```

### OpenCode: read + find

```103:117:/home/artem/reps/opencode/packages/web/src/content/docs/tools.mdx
### read ... line ranges
```

```192:201:/home/artem/reps/opencode/packages/web/src/content/docs/server.mdx
// GET /find?pattern= ... line_number
```

---

## Целевая формула (read + memory)

1. **Progressive disclosure (файлы):** index/grep → `read_file` коротким окном → расширение при необходимости.
2. **Progressive disclosure (память):** если auto-KB или прошлая сессия уже положили **entrypoints/tree** — **сначала** `kb_search` / `kb_fetch` по namespace, **потом** тяжёлый glob.
3. **Повторное чтение избегать:** дедуп, телеметрия дубликатов.
4. **Измеримость:** range vs full read; обращения к `kb_*`; **не** путать оценку UI с «качеством» KB без пояснения (см. R4.3).
5. **not_git / git:** для dev-проектов documentировать выгоду `git init` + remote для **ветки** в namespace.

---

## Этап R0. Протокол чтения (policy) и подсказки модели

### Задача R0.1 — Явный протокол «grep → range read»

**Содержание:** 6–10 пунктов для system-hints (как у доноров): `list_dir`/`glob_file` для **грубой** структуры, `grep` для поиска, `read_file` **с** `offset`/`limit` для содержимого; первое чтение ≤ N строк (например 120–200).

**Критерии приёмки:** протокол согласован с [`plan/workflow-token-economy-recipe.md`](workflow-token-economy-recipe.md) (анти-raw-dump); явное правило «функция/класс → диапазон вокруг сигнатуры или структурный tool, если появится (R2)».

**Проверки:** ревью текста; при изменении — `flake8` + `pytest` по затронутым модулям.

### Задача R0.2 — Обновить `ailit chat` system-hints

**Содержание:** расширить подсказки в `tools/ailit/chat_app.py` (и при паритете в TUI, если применимо): явно `read_file` + `offset`/`limit`.

**Критерии приёмки:** подсказка не конфликтует с perm-5, pager, budget, prune.

**Проверки:** smoke mock-provider; `pytest` + `flake8` по файлам.

---

## Этап R1. Телеметрия и диагностика range-read

### Задача R1.1 — Событие / агрегаты «сколько прочитано»

**Содержание:** нынешнее `fs.read_file.completed` использовать как канон; при необходимости **дополнить** JSONL-полями, не дублируя body. По JSONL строится метрика range-read vs full-read (уже завязана на `range_read` / счётчики в агрегатах).

**Критерии приёмки:** по логу однозначно видна доля `range_read: true`.

**Проверки:** `pytest` на сценарий `read_file` с и без `limit`.

### Задача R1.2 — Метрика повторных чтений (duplicate reads)

**Содержание:** счётчик одинакового `(path, offset, limit)` при неизменном mtime (на базе существующего дедупа в `builtin_read_file`).

**Критерии приёмки:** на синтетике счётчик растёт; не ломает happy-path.

**Проверки:** unit-тест (по согласованию с владельцем — не создавать тесты без запроса в workflow; **здесь** критерий приёмки включает тест — выполнить).

---

## Этап R2. Структурное чтение (опционально)

### Задача R2.1 — `read_symbol` (LSP / tree-sitter)

**Содержание:** tool `(path, symbol) → start_line, end_line, signature, фрагмент тела с лимитом` минимум для Python.

**Критерии приёмки:** интеграция с протоколом R0; `pytest` + `flake8`.

---

## Этап R3. Ручной gate (пользователь)

### Задача R3.1 — Три сценария в `ailit chat`

1. «Найди определение по имени» → `grep` → `read_file(offset, limit)`.
2. «Исправь баг в одной функции» → `read_symbol` или range вокруг сигнатуры.
3. «Сравни два использования» → два range-read.

**Критерии приёмки:** в JSONL нет массового full read больших файлов без причины; при необходимости снять copy-paste логов в issue.

---

## Этап R4. Память (M4) и **между** сессиями — эффективность

Связано с наблюдениями выше и с `build_memory_diagnosis` / `memory_full_report` в `chat_app`.

### Задача R4.1 — Протокол «KB-first после auto-write»

**Содержание:** в system-hints (или узком слое, подмешиваемом при `memory.policy.enabled` и известных kind’ах: `repo_entrypoints`, `repo_tree_root`) зафиксировать: для вопросов уровня «как устроен проект / точки входа / дерево» — **сначала** `kb_search` / `kb_fetch` по id/summary, **затем** `glob_file` / полные обходы.

**Критерии приёмки:** на одном и том же workdir второй сценарий «точки входа» **не** обязан** дублировать 6× `glob` до обращения к KB (допустима эвристика: минимум один `kb_search` или `kb_fetch` до широкого glob в acceptance-тесте или e2e по логу — выбрать устойчивый вариант при реализации).

**Проверки:** ручной сценарий + по возможности e2e на JSONL-инварианты; `pytest` + `flake8`.

### Задача R4.2 — Стабильность идентичности репо (path vs git)

**Содержание:** задокументировать в `docs` или в этом плане для пользователей: **not_git** → namespace только от path; для стабильной **ветки/URI** — `git init` + `origin`. Опциональная **подсказка в UI** (одна строка) при `not_git` в `memory.policy`.

**Критерии приёмки:** README или `docs/INDEX` ссылается кратко; нет дублирования простыни M4.

**Проверки:** ревью; при изменении UI — ручной прогон `ailit chat`.

### Задача R4.3 — Прозрачность оценки «N/100» в панели памяти

**Содержание:** в подписи к `build_memory_efficiency_score` (Streamlit) явно: оценка отражает **дисциплину range-read + плотность kb_* + promotion + pager/exposure**, а **не** «успел ли ответ быть правильным». Опционально: лёгкая **коррекция весов** (например, отдельный бонус за успешный `kb_fetch` с ненулевым id) — **только** с мини-регрессией в `test_token_economy` / аналоге.

**Критерии приёмки:** пользователь видит, **почему** 38 и 45 отличаются в ваших прогонах; изменение весов (если делали) с тестом.

**Проверки:** `pytest` по `token_economy_aggregates` при изменении формул; `flake8`.

### Задача R4.4 — (Research) Инъекция top-K фактов в контекст хода

**Содержание:** исследование по образцу Letta **memory blocks**: после `memory.retrieval.match` подмешивать 1–3 **коротких** факта в system (с лимитом токенов). Отдельное согласование scope (только `project`? только `repo_entrypoints`?).

**Критерии приёмки:** design note в `plan/` или issue; реализация **не** входит в минимальное закрытие R4.1–R4.3.

**Проверки:** н/д (research).

---

## Конец workflow

1. Пока **не** закрыты согласованные задачи R0–R3 и **минимум R4.1 + R4.3** (протокол KB-first + прозрачность оценки), **не** считать read-6 завершённым для обновления «закрыто» в [`README.md`](../README.md).
2. Закрытие этапов: **коротко** обновить таблицу статуса в `README.md` (строка про read-6) и **не** расширять scope без нового фрагмента плана.
3. Если R4.1–R4.3 сделаны, R4.2 в доке сделан, R4.4 исследован — workflow **исчерпан** по read-6 → по [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc) запросить **research** и **постановку** следующей цели (например отдельный `plan/7-…` или ветка в M5).

**Коммиты (правило):** по этапам: `read-6/R0`, `read-6/R1`, …; в теле ссылки на задачу (R0.1, …). Перед коммитом: `pytest` + `flake8` по изменённым пакетам.

---

## Приложение. Соответствие ранних секций текущему коду

Фрагменты из прежней версии документа (builtins, workdir_paths, `ToolSpec` для `read_file`) остаются в силе; пути: `tools/agent_core/tool_runtime/builtins.py`, `tools/agent_core/tool_runtime/workdir_paths.py` — **при существенных рефакторингах** обновить номера строк в этом файле.
