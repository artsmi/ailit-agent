# Промпты по фазам рантайма и многоязычие (Prompts)

**Аннотация:** здесь не дословные тексты промптов из кода, а **контракт требований**: какую роль выполняет каждый промпт, что обязано быть в инструкциях к модели, и как классифицируются файлы. Дословные строки живут в репозитории продукта.

**CoT**, **D-OBS** — см. [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-008 | Промпты для нескольких языков программирования и для не-кода; поле `file_kind`, сегментация; запреты на вывод рассуждений вне JSON и на сырые дампы. |
| OR-009 | Каталог промптов, привязанный к состояниям/фазам рантайма (таблица ниже). |

## Текущая реализация

- Планер: для первого раунда используется константа **`W14_PLAN_TRAVERSAL_SYSTEM`** в `agent_memory_query_pipeline.py` (роль «только JSON, `plan_traversal`, whitelist действий»); это соответствует строке таблицы ниже для фазы `planner_round`, а не отдельному файлу `agent_memory.system` с именем фазы `intake`.
- Сводки C/B: отдельные вызовы LLM через `AgentMemorySummaryService` со строгой схемой `agent_memory_command_output.v1` и внутренними фазами repair (`summarize_c_repair` / `summarize_b_repair` в журнале).
- Repair планера: `_w14_repair_system_message` / `_w14_repair_user_instruction`, в т.ч. спец-ветка UC-03 для legacy top-level `in_progress` → канонизация в `ok` при валидном payload.
- Режим отладки с подробным логом чата (`AgentMemoryChatDebugLog`) может содержать полные сообщения LLM — это **не** компактный канал для внешних потребителей.

## Целевое поведение

### Каталог промптов по фазам (OR-009)

Каждая строка — **роль промпта**, не дословный текст.

| Состояние / фаза рантайма | Роль промпта | Обязательные инструкции к LLM |
|---------------------------|--------------|-------------------------------|
| `intake` (заголовок политики) | `agent_memory.system` | Разделение ролей рантайм vs LLM; запрет CoT в выходе; запрет filesystem/tools из JSON; запрет absolute/`..` paths; указание лимитов. |
| `planner_round` | `agent_memory.planner.plan_traversal` | Только JSON; whitelist `actions`; память проекта **не только Python**; явное учёт `file_kind` при выборе путей. |
| `summarize_phase` / C | `agent_memory.summarize.c` | Строгая схема `agent_memory_command_output.v1`; вернуть `file_kind`, `language`, `semantic_chunk_kind`, кандидаты с доказательством. |
| `summarize_phase` / B | `agent_memory.summarize.b` | Аналогично; ссылка на дочерние сводки C при необходимости. |
| `propose_links` | `agent_memory.links.propose` | Инструкции к модели задают **содержимое `payload`** внутри полного конверта W14 `agent_memory_command_output.v1`: `command` = **`propose_links`**, `schema_version` конверта, `command_id`, top-level `status` ∈ {`ok`,`partial`,`refuse`}, поле **`payload.candidates`** или **`payload.link_batch.candidates`** — массив `agent_memory_link_candidate.v1[]` (см. D-PROPOSE-LINKS-1 в [`llm-commands.md`](llm-commands.md)). **Запрещено** описывать успешный ответ как корневой JSON «только массив кандидатов» без envelope. Запрет семантики прямой записи в SQLite из ответа модели — без изменений. |
| `finish_assembly` | `agent_memory.finish.decision` | Выбор из кандидатов; `decision_summary` компактно; `recommended_next_step` с лимитом. |
| `planner_repair` | `agent_memory.planner.repair_format` | Исправить JSON строго под схему; один раунд. |

### Классификация языка и вида файла (OR-008)

**Обязательная классификация** до «рассуждений в стиле AST»:

- `file_kind`: `source_code` \| `documentation` \| `configuration` \| `build_file` \| `test` \| `unknown_text` (обязательно в batch-выходе C).
- `language`: расширенный перечень, включая `python`, `go`, `cpp`, `c`, `typescript`, `markdown`, `yaml`, `json`, `dockerfile`, `makefile`, `unknown`.
- `semantic_chunk_kind`: `function`, `class`, `method`, `struct`, `interface`, `heading_section`, `config_section`, `build_target`, `test_case`, `text_window`, …

**Fallback:** для `unknown` — `semantic_chunk_kind=text_window` или `heading_section` с явной пометкой эвристики; **запрещено** выдавать такой фрагмент как надёжный `calls`/`imports` без доказательства.

### Фрагмент контрактного примера структуры выхода

```json
{
  "file_kind": "source_code|documentation|configuration|build_file|test|unknown_text",
  "language": "python|go|cpp|c|typescript|markdown|yaml|json|dockerfile|makefile|unknown",
  "semantic_chunk_kind": "function|class|method|struct|interface|heading_section|config_section|build_target|test_case|text_window",
  "candidates": [
    {
      "stable_name": "string",
      "start_line": 0,
      "end_line": 0,
      "summary": "string, bounded",
      "link_candidates": []
    }
  ]
}
```

### Запреты (все промпты)

- Цепочка рассуждений / текст вне JSON в машинном канале — **запрещено**.
- Секреты, ключи, токены — **запрещено**.
- Большие сырые дампы файлов — **запрещено**; только выбранные окна строк, хэши, диапазоны.

### Подробный лог (verbose)

Флаг вроде `memory.debug.verbose=1` — **только для аудита**; потребители подмножества D-OBS не обязаны разбирать этот поток.

### Лимиты размера полей

Строковые поля и счётчики в публичных схемах событий и результатов ограничиваются в **символах UTF-8** и/или в количестве узлов/рёбер с флагом `truncated` (единая политика с [`failure-retry-observability.md`](failure-retry-observability.md)); не смешивать с токенами токенизатора в обязательных полях публичной схемы.

## How start-feature / start-fix must use this

- **`02_analyst`:** при задачах, затрагивающих промпты, многоязычие или `file_kind`, брать **требования к тексту инструкций** из этого файла и не смешивать их с wire-схемой W14 из `llm-commands.md` (роль промпта ≠ автономный JSON без конверта).
- **`06_planner`:** трассировать work на строки таблицы фаз (`intake`, `planner_round`, `summarize_*`, `propose_links`, `finish_assembly`, `planner_repair`) и на OR-008 / OR-009; слайсы и порядок внедрения — только в `plan/*`, не в этом каноне.
- **`11_test_runner`:** проверять согласованность «промпт говорит модели X» с тестами на запрет CoT/прозы и на схему вывода там, где тесты уже существуют для W14 / summary; новые имена тестов не выдумывать из этого файла без плана.
- **`13_tech_writer`:** при изменении реальных строк промптов или фаз в коде обновить блоки «Текущая реализация» и таблицу каталога здесь так, чтобы они оставались согласованы с `llm-commands.md` и `failure-retry-observability.md`.
