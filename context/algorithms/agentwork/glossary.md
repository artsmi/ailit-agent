# Глоссарий AgentWork

Краткие определения терминов, которые пересекаются с AgentMemory, локальной KB и оркестратором.

| Термин | Смысл |
|--------|--------|
| **AgentWork** | Отдельный процесс-воркер (`work_agent.py`), который выполняет `work.handle_user_prompt`: тянет контекст памяти, выбирает режим инструментов, гоняет LLM через `SessionRunner` и микро-оркестратор. |
| **Broker** | Процесс рантайма, который поднимает сокет, маршрутизирует `service.request` между агентами и пишет trace. AgentWork шлёт в него строки JSON (stdout) как клиент Unix-сокета для вызова AgentMemory. |
| **AgentMemory** | Подпроцесс/актор `AgentMemory:global`, исполняющий `memory.query_context` по контракту W14; возвращает `agent_memory_result` и опционально `memory_slice` с текстом для промпта. |
| **PAG** | Граф памяти проекта в SQLite; AgentMemory его обходит. AgentWork **не** ходит в PAG напрямую в типичном пути — только через RPC к AgentMemory. |
| **Локальная KB (SQLite)** | Файл `kb.sqlite3` (или путь из `AILIT_KB_DB_PATH`), логические записи с namespace; инструменты `kb_search`, `kb_fetch`, `kb_write_fact` в реестре инструментов модели. |
| **KB-first hint** | Дополнительный фрагмент system-подсказки при первом сообщении чата, если в merge-конфиге `memory.enabled: true`: просить модель сначала искать в KB, а не сразу сканировать диск. |
| **Режим perm (perm_tool_mode)** | Один из нормализованных режимов (`explore`, `read`, `edit`, …) — насколько агрессивно разрешены записи и shell. Выбирается классификатором и/или пользователем и KB-политикой проекта. |
| **Namespace KB для perm** | Строка из `build_mode_kb_namespace`: предпочтительно `namespace_for_repo(uri, path, branch)`, иначе fallback на `memory.namespace` из конфига. Разделяет записи решений по репозиторию/ветке. |
| **Micro-plan** | Детерминированный компактный план (`WorkTaskPlan`) из `MicroPlanner`: шаги на русском, без отдельного LLM-планера. |
| **Verify gate** | После успешного `SessionState.FINISHED` для `small_code_change`: запуск `pytest` по затронутым тестам и `flake8` по изменённым `.py`, если политика `python_default`. |
| **Repair** | Один дополнительный прогон `SessionRunner` с system-сообщением оркестратора, если verify провалился и `max_repair_attempts > 0`. |
| **D-level compact** | Восстановление краткого summary-узла контекста при повторном открытии чата (`DLevelCompactService`). |
| **memory.change_feedback** | Сервисный запрос в AgentMemory после записи файлов инструментом: fingerprint, batch id, цель пользователя — для синхронизации графа без «сырых» file_changed. |
