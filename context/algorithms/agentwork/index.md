# Пакет: AgentWork (рабочий агент десктоп-рантайма)

Каноническое **описание поведения** подпроцесса AgentWork: исполнение пользовательского промпта, инъекция контекста AgentMemory, локальная KB, perm-5, микро-оркестрация плана и verify. Документы согласованы с кодом в `ailit/ailit_runtime/subprocess_agents/` и смежными модулями на дату подготовки пакета.

**Аннотация:** начните с [`runtime-flow.md`](runtime-flow.md), затем [`kb-and-memory-layers.md`](kb-and-memory-layers.md) (разделение PAG/AgentMemory, SQLite KB и perm-KB), затем [`micro-orchestration.md`](micro-orchestration.md). Расшифровки терминов — в [`glossary.md`](glossary.md).

## Статус

`draft` — пакет создан как **документация по факту кода** (engineering canon), без отдельного target-doc approval pipeline. Для продуктовых изменений поведения используйте `start-feature` и сверку с этим пакетом; при существенном расхождении код ↔ текст правьте соответствующий файл пакета в том же изменении или оформляйте backlog в [`strengthening-and-config.md`](strengthening-and-config.md).

## Назначение

- Объяснить человеку и разработчику **цепочку от stdin JSON до ответа и trace-событий**.
- Явно развести **три слоя памяти** вокруг AgentWork (см. [`kb-and-memory-layers.md`](kb-and-memory-layers.md)).
- Зафиксировать **детерминированное планирование** микро-оркестратора и границы ответственности `SessionRunner`.
- Собрать **рычаги усиления** агента в одном месте ([`strengthening-and-config.md`](strengthening-and-config.md)).

## Ограничения пакета

- **Не** дублирует полный W14-протокол AgentMemory: за деталями графа, LLM-команд и `agent_memory_result.v1` идите в [`../agent-memory/INDEX.md`](../agent-memory/INDEX.md).
- **Не** описывает развёртывание Electron; см. [`../desktop-stack/INDEX.md`](../desktop-stack/INDEX.md) при необходимости UI-инвариантов.

## Состав пакета

| Файл | Содержание |
|------|------------|
| [`glossary.md`](glossary.md) | Термины: AgentMemory vs KB vs perm-KB, micro-plan, verify gate. |
| [`runtime-flow.md`](runtime-flow.md) | Spawn, stdin loop, `run_user_prompt`, threading, отмена. |
| [`kb-and-memory-layers.md`](kb-and-memory-layers.md) | Три слоя: RPC памяти, kb_* инструменты, KB решений perm. |
| [`micro-orchestration.md`](micro-orchestration.md) | `WorkTaskOrchestrator`: classify → plan → execute → verify → repair. |
| [`strengthening-and-config.md`](strengthening-and-config.md) | Конфиг, env, operational playbook, backlog идей. |
| [`events-and-integrations.md`](events-and-integrations.md) | События trace и ожидания для Desktop. |
| [`donors/INDEX.md`](donors/INDEX.md) | Учёт donor-идей (сейчас заглушка). |

## Якоря в коде (implementation anchors)

| Тема | Файл | Символ / область |
|------|------|------------------|
| Точка входа процесса | `work_agent.py` | `main`, `AgentWorkWorker.handle` |
| Сессия и память | `work_agent.py` | `_WorkChatSession.run_user_prompt`, `_request_memory_slice` |
| Реестр инструментов | `work_agent.py` | `_RegistryAssembler.build` |
| Оркестратор | `work_orchestrator.py` | `WorkTaskOrchestrator`, `TaskClassifier`, `MicroPlanner`, `RuntimeVerifier` |
| Perm + KB namespace | `perm_turn.py` | `PermModeTurnCoordinator`, `build_mode_kb_namespace` |
| KB tools | `kb_tools.py` | `build_kb_tool_registry`, `kb_tools_config_from_env` |
| Подсказки | `tool_system_hints.py` | `memory_kb_first_enabled`, `inject_tool_hints_before_first_user` |

## Примеры сценариев

1. **Успешный малый фикс:** пользователь просит поправить тест → классификация `small_code_change` → slice памяти (если доступен) → execute с планом → pytest/flake8 зелёные → ответ с строкой «Проверка пройдена».
2. **Крупная задача:** текст с маркером «архитектура» → `large_code_change` → ответ только с декомпозицией, без массовых правок файлов.
3. **Память недоступна:** нет сокета брокера → событие `memory.actor_unavailable` → ход продолжается без `agent_memory_slice`; модель должна опираться на инструменты (и KB, если включена).

## Трассировка на смежные алгоритмы

| Вопрос | Куда |
|--------|------|
| Граф PAG, W14, `agent_memory_result` | [`../agent-memory/`](../agent-memory/INDEX.md) |
| Отображение графа в UI | [`../desktop/`](../desktop/INDEX.md) |
| Чат, freeze, trace | [`../desktop-stack/`](../desktop-stack/INDEX.md) |
