# KB и память: три слоя вокруг AgentWork

У AgentWork **три разных механизма**, которые называют «памятью» в разговоре, но не взаимозаменяемы. Путаница между ними — частая причина неверных ожиданий при настройке.

## Слой 1: AgentMemory (PAG, W14) — до первого токена ответа модели

**Назначение:** дать в промпт **сжатый срез графа** по текущей подзадаче (`subgoal`), не заставляя основную модель самостоятельно обходить PAG.

**Как вызывается:** `_WorkChatSession._request_memory_slice` формирует `service.request` с `service: memory.query_context`, `schema_version: agent_work_memory_query.v1`, полями `project_root`, `namespace`, `known_paths`, `known_node_ids`, `stop_condition` и т.д. Запрос идёт синхронно в брокер по Unix-сокету с таймаутом из merge-конфига памяти (`agent_memory_rpc_timeout_s`).

**Цикл continuation:** если `agent_memory_result.status == partial` и классификатор `_MemoryPathTurnClassifier` решает, что нужно продолжить (расширение refs, `memory_continuation_required`, partial_reasons с «continuation» и т.п.), AgentWork **увеличивает** `known_paths` / `known_node_ids`, подменяет `subgoal` на `recommended_next_step` (если есть) и делает следующий RPC, пока не исчерпан лимит `max_memory_queries_per_user_turn` (дефолт в merge-конфиге часто 6).

**Инъекция в чат:** при успешном завершении цикла строится `ChatMessage` с `role=system`, `name=agent_memory_slice` и текстом из `memory_slice.injected_text`. Если текста нет — событие `memory.actor_slice_skipped`. Итоговый slice **не сохраняется** в долговременной истории чата: перед возвратом из хода сообщения с `name=agent_memory_slice` вырезаются (`_strip_transient_memory`).

**События для наблюдаемости:** среди прочих публикуются `memory.query.budget_exceeded`, `memory.query.timeout`, `memory.query_context.continuation`, `memory.actor_slice_used`, `context.memory_injected` (payload через `memory_injected_v2_payload`).

**Связь с KB-first:** это **разные вещи**. AgentMemory не использует SQLite KB напрямую в этом пути; KB-first — это подсказка модели **после** того, как slice уже мог быть добавлен.

## Слой 2: Локальная SQLite KB — инструменты в основной сессии

**Назначение:** хранить **короткие факты** (точки входа, заметки о репо), искать по ним без полного сканирования дерева.

**Включение в реестр:** в `_RegistryAssembler.build` читается merge-конфиг; если `memory.enabled`, выставляется `os.environ["AILIT_KB_NAMESPACE"]` из `memory.namespace` и в реестр мержится `build_kb_tool_registry(kb_tools_config_from_env())`.

**Конфигурация окружения инструментов** (`kb_tools_config_from_env`): по умолчанию KB **включена** (`AILIT_KB=0` отключает); путь к файлу БД — `AILIT_KB_DB_PATH` или `~/.ailit/kb.sqlite3`; логический namespace — `AILIT_KB_NAMESPACE` (по умолчанию `default`).

**Имена инструментов:** `kb_search`, `kb_fetch`, `kb_write_fact` (без точек в имени — ограничение некоторых провайдеров).

**KB-first подсказка:** при **первом** user-сообщении в сессии AgentWork, если `memory.enabled` в конфиге, в system подмешивается блок из `tool_system_hints` (`_KB_FIRST_AFTER_WRITE_HINT`): сначала поиск по KB для вопросов уровня «как устроен проект», затем обход диска при нехватке сигнала.

## Слой 3: KB записей режима инструментов (perm-5)

**Назначение:** помнить **решения о режиме** `perm_tool_mode` между ходами: история для LLM-классификатора и опциональный «project default» после «remember always».

**Тот же файл SQLite**, что и слой 2, но **другой вид записей** (`MODE_DECISION_KIND`), namespace строится через `build_mode_kb_namespace(memory_namespace, project_root)` — предпочтительно привязка к `repo_uri` + ветке, иначе fallback на namespace из конфига памяти.

**Поток:** `PermModeTurnCoordinator` открывает KB; если есть project default из KB — режим берётся без LLM; иначе читается история последних решений, вызывается `LlmPermModeClassifier`, при уверенном режиме запись в KB; при `not_sure` — UI gate и затем `record_user_choice` с возможной записью policy.

## Сводная таблица

| Вопрос | Слой 1 (AgentMemory) | Слой 2 (kb_* tools) | Слой 3 (perm KB) |
|--------|----------------------|---------------------|------------------|
| Кто пишет в хранилище? | AgentMemory worker, не AgentWork напрямую | Модель через `kb_write_fact` / авто-наблюдатели вне этого файла | Классификатор perm и UI выбора |
| Когда участвует? | До основного LLM-цикла | Во время tool-calls основной модели | До основного LLM-цикла (perm path) |
| Namespace | `identity.namespace` из envelope | `AILIT_KB_NAMESPACE` из env при сборке реестра | `build_mode_kb_namespace(...)` |

## Типичные ошибки конфигурации

- Включили только `memory.enabled` для slice, но не подняли AgentMemory или нет сокета брокера — получите события `memory.actor_unavailable`, ход пойдёт без графа.
- Ожидали perm-историю по проекту, но `AILIT_KB=0` или неверный путь к БД — координатор откроет `kb is None` и будет только LLM без истории.
- Namespace AgentMemory (`default`) не совпадает с тем, куда пишет индексация — slice пустой или нерелевантный.
