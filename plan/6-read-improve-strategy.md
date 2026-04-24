# Workflow: read-improve-strategy (progressive disclosure чтения кода)

Документ задаёт **этапы → задачи → критерии приёмки → проверки** для улучшения стратегии чтения файлов в `ailit`, чтобы:

- читать **не весь файл**, а **ровно нужные диапазоны строк** (как в Claude Code);
- опираться на **index-first** (grep → номера строк → `read_file(offset, limit)`), а не на raw-dump;
- иметь измеримость (диагностика/метрики) и защиту от регресса.

Канон процесса разработки репозитория: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Контекст: что уже есть в `ailit`

### 1) `read_file` уже поддерживает range read

`read_file` принимает `offset` (1-based) и `limit` (строки). Это уже экономит контекст, если модель выбирает чтение чанками.

Реализация:

```57:94:tools/agent_core/tool_runtime/builtins.py
def builtin_read_file(arguments: Mapping[str, Any]) -> str:
    ...
    offset_line = int(arguments.get("offset", 1) or 1)
    raw_limit = arguments.get("limit")
    ...
    text = read_file_text_slice(
        path,
        max_bytes=MAX_READ_BYTES,
        offset_line=offset_line,
        limit_line=limit_line,
    )
```

Слайсер и лимиты:

```146:176:tools/agent_core/tool_runtime/workdir_paths.py
def read_file_text_slice(
    path: Path,
    *,
    max_bytes: int = MAX_READ_BYTES,
    offset_line: int = 1,
    limit_line: int | None = None,
) -> str:
    ...
    start = max(1, offset_line) - 1
    ...
    if len(chunk) > MAX_READ_LINES:
        msg = f"line slice too large; max {MAX_READ_LINES} lines per read"
        raise ValueError(msg)
```

Схема инструмента (поля `offset`/`limit` задокументированы):

```406:437:tools/agent_core/tool_runtime/builtins.py
"read_file": ToolSpec(
    ...
    "offset": {
        "type": "integer",
        "description": (
            "1-based starting line (optional). "
            "With limit, reads at most "
            f"{MAX_READ_LINES} lines per call."
        ),
    },
    "limit": {"type": "integer", "description": "Max lines from offset (optional)."},
)
```

### 2) Дедупликация повторных чтений уже есть

Если файл и диапазон строк не менялись, `read_file` возвращает stub (в пределах процесса).

```28:94:tools/agent_core/tool_runtime/builtins.py
_READ_DEDUP: dict[tuple[str, int, int | None], tuple[float, str]] = {}
...
if prev is not None and prev[0] == mtime_ns:
    return _FILE_UNCHANGED_STUB
```

### 3) Чего не хватает

Сейчас диапазоны строк выбирает **сама модель** по эвристике; в `ailit chat` есть общие подсказки про file tools, но нет явного протокола “grep → range read → расширять только при необходимости”.

---

## Доноры (как устроено у них)

### Claude Code

1) FileReadTool читает **в диапазоне** (`readFileInRange`) и пишет аналитику offset/limit:

```1019:1055:/home/artem/reps/claude-code/tools/FileReadTool/FileReadTool.ts
// --- Text file (single async read via readFileInRange) ---
const lineOffset = offset === 0 ? 0 : offset - 1
const { content, lineCount, totalLines, totalBytes, readBytes, mtimeMs } =
  await readFileInRange(
    resolvedFilePath,
    lineOffset,
    limit,
    limit === undefined ? maxSizeBytes : undefined,
    context.abortController.signal,
  )
...
const data = {
  type: 'text' as const,
  file: {
    filePath: file_path,
    content,
    numLines: lineCount,
    startLine: offset,
    totalLines,
  },
}
```

2) Claude Code поддерживает синтаксис упоминания файла с диапазоном строк в тексте (UI/парсер): `@file.txt#L10-20`.

```2757:2765:/home/artem/reps/claude-code/utils/attachments.ts
// Extract filenames mentioned with @ symbol, including line range syntax: @file.txt#L10-20
```

### OpenCode

В документации явно заявлено, что tool read поддерживает **line ranges**:

```103:117:/home/artem/reps/opencode/packages/web/src/content/docs/tools.mdx
### read
Read file contents from your codebase.
...
This tool reads files and returns their contents. It supports reading specific line ranges for large files.
```

OpenCode также предоставляет file/find API, которое отдаёт `line_number` и `lines` в match-объектах, что поддерживает паттерн “find → read range”.

```192:201:/home/artem/reps/opencode/packages/web/src/content/docs/server.mdx
### Files
...
| `GET`  | `/find?pattern=<pat>`    | Search for text in files           | Array of match objects with `path`, `lines`, `line_number`, `absolute_offset`, `submatches` |
| `GET`  | `/file/content?path=<p>` | Read a file                        | FileContent |
```

---

## Целевая формула (best practices → улучшения в `ailit`)

1) **Progressive disclosure**: сначала index/grep, потом `read_file` коротким окном, потом расширение диапазона.
2) **Структурные границы по возможности**: когда нужно “вся функция/класс”, лучше иметь tool уровня “read_symbol” (AST/LSP), чем вручную угадывать offset/limit.
3) **Повторное чтение избегать**: дедуп, кеш state (в процессе) и явная телеметрия “duplicate reads”.
4) **Политика по умолчанию** в system-hints: “не читай целиком, если не требуется”.
5) **Измеримость**: события/метрики “сколько строк/байт прочитано”, “сколько range-read vs full-read”, “сколько повторов”.

---

## Этап R0. Протокол чтения (policy) и подсказки модели

### Задача R0.1 — Явный протокол “grep → range read”

**Содержание:** сформулировать 6–10 пунктов протокола чтения для агента (в стиле Claude Code / OpenCode), который можно вставлять в system-hints.

**Критерии приёмки:**

- протокол требует: `list_dir/glob_file` для структуры, `grep` для поиска, `read_file` только диапазонами;
- есть правило “первое чтение ≤ N строк (например 120–200), расширение только по необходимости”;
- есть правило “если нужна вся функция/класс — предпочесть структурный tool (если включён) или читать диапазон вокруг сигнатуры”.

**Проверки:**

- ручная ревью-проверка текста на согласованность с `workflow-token-economy-recipe.md` (запрет raw dump).

### Задача R0.2 — Обновить `ailit chat` system-hints под протокол

**Содержание:** расширить подсказку из `tools/ailit/chat_app.py` так, чтобы модель регулярно выбирала `offset/limit`.

**Критерии приёмки:**

- подсказка явно упоминает `read_file(offset, limit)` и рекомендуемый стартовый лимит;
- подсказка не конфликтует с pager/budget/prune и не обещает невозможное.

**Тесты / проверки:**

- unit test на composer/hints (если есть подходящая инфраструктура), либо smoke через mock-provider.

---

## Этап R1. Телеметрия и диагностика range-read

### Задача R1.1 — Событие `file.read` (сколько прочитано)

**Содержание:** добавить диагностическое событие `file.read` с полями: `path`, `offset`, `limit`, `read_lines`, `total_bytes`, `read_bytes`, `mtime`.

**Критерии приёмки:**

- событие не раскрывает лишние данные (не дублирует body в лог);
- по JSONL можно построить метрику “range-read vs full-read”.

**Проверки:**

- pytest на наличие события при вызове `read_file`.

### Задача R1.2 — Метрика повторных чтений (duplicate reads)

**Содержание:** фиксировать в диагностике/агрегатах, сколько раз модель читает один и тот же `(path, offset, limit)` без изменений.

**Критерии приёмки:**

- есть счётчик и он растёт на синтетическом сценарии;
- подсказки/протокол не провоцируют лишние повторения.

---

## Этап R2. Структурное чтение (опционально, но целевая “киллер-фича”)

### Задача R2.1 — `read_symbol` (LSP/tree-sitter) как tool

**Содержание:** добавить инструмент, который по `(path, symbol)` возвращает:

- `start_line`, `end_line`, `signature`;
- и только фрагмент тела (с лимитом).

**Критерии приёмки:**

- работает как минимум для Python/TS (минимальный набор);
- в prompt попадает только тело нужного символа, а не весь файл;
- интегрируется с протоколом R0 (модель знает, когда выбирать `read_symbol`).

**Проверки:**

- pytest на корректный диапазон по тестовому файлу;
- flake8 по новым модулям.

---

## Этап R3. Ручной пользовательский тест (gate)

### Задача R3.1 — Сценарий проверки в `ailit chat`

**Содержание:** 3 ручных сценария:

1) “Найди определение функции по имени” → ожидать `grep` → `read_file(offset, limit)` (а не full file).
2) “Исправь баг в одной функции” → ожидать `read_symbol` (если включён) или чтение вокруг сигнатуры.
3) “Сравни два места использования” → два точечных range-read.

**Критерии приёмки:**

- в JSONL видны `read_file` с `offset/limit` и событие `file.read`;
- нет массовых чтений целых больших файлов без причины;
- экономия токенов проявляется в меньшем числе `context.pager.page_created` из-за `read_file` по всему файлу.

---

## Конец workflow

Если этапы R0–R2 закрыты и ручной gate R3 пройден, обновить статус в `README.md` (коротко) и не расширять scope без следующего утверждённого документа (см. [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc)).

