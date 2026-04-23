# M3-4.2: governance памяти (черновик к канону)

Связано с [`workflow-memory-3.md`](workflow-memory-3.md) (этап M3-4), реализацией
`kb_*`, `kb_promote`, `promotion_policy`, `SqliteKb`, событиями
`memory.promotion.*` / `memory.access` в `agent_core`. Документ задаёт
**правила владения и операций** до расширения PII-политики в отдельных workflow.

## 1. Границы

| Концепт | Смысл |
|--------|--------|
| `namespace` (KB) | Логическое пространство имён записей; изоляция по умолчанию между `AILIT_KB_NAMESPACE` и путями в UI. |
| `scope` | `org\|workspace\|project\|agent\|run` — **область жизни** смысла, не путайте с Unix path. |
| `promotion_status` | Жизненный цикл: `draft` → `reviewed` → `promoted` (только `semantic`/`procedural`); `deprecated`; терминал `superseded`. |

## 2. Кто что может

| Операция | Канал | Ограничения |
|----------|--------|-------------|
| Создать/править тело факта | `kb_write_fact` | Только `promotion_status=draft`; смена стадий **запрещена** (см. `promotion_via_kb_promote_only`). |
| Сменить promotion | `kb_promote` | Правила в `agent_core.memory.promotion_policy` (переходы, source, body, layer). |
| Суперсессия | `kb_write_fact` + `supersedes_id` | Старая запись получает `superseded` системой; с таких записей write запрещён. |

**Роли (целевое, не весь UI обязан быть реализован):** человек-оператор при необходимости
через approve-политику tools; агент — только `draft` write и запрос `kb_promote` по
правилам; CI/отдельный job может вызывать `kb_promote` с той же политикой, если
поднят headless-режим (вне scope текущего CLI).

## 3. PII / секреты

- **Не класть** в `body`/`summary` сырой секрет; предпочитать ссылку (путь, commit,
  `episode_id`) в `source` / `provenance`.
- **Логи JSONL:** `memory.access` — без полного текста; `tool.call_started` для
  `kb_*` — аргументы редактируются. Диагностика `read_file` в событиях
  `fs.read_file.*` — только `path_tail` / счётчики, не полные пути при
  публикации в общие логи (локально path может быть в `arguments_json` read_file,
  не в `fs` event).

## 4. Соответствие коду

- Политика переходов: `tools/agent_core/memory/promotion_policy.py`
- Write + immutable superseded: `SqliteKb.write`, `kb_tools._kb_write_fact`
- События: `SessionRunner._emit_memory_promotion`, `memory.access`
- **Ускоряющий слой vs истина** (M3-5): KB SQLite = локальный first-class store для
  фактов в этой ветке; каноном для «файл = истина» остаётся отдельная постановка
  в M3-5, здесь — только **не** считать raw чатовый дамп причиной `reviewed+`.

## 5. Следующие уточнения (deferred)

- Матрица `bank_id` / мульти-тенант.
- Явные TTL/архив для `deprecated` (не автомат, пока нет планировщика).
- Подпись reviewera в записи (поле `provenance` / внешний id).

Правило workflow: при закрытии M3-4.2 **обновить** статус в
[`plan/workflow-memory-3.md`](workflow-memory-3.md) и при необходимости ссылку в
корневом README по [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).
