# Передача в start-feature: пакет AgentMemory (start-feature handoff)

**Аннотация:** как нарезать реализацию после утверждения канона, чего не делать за один раз, и какие артефакты считать доказательством. Полный канон — в [`INDEX.md`](INDEX.md) и соседних файлах; сокращения — в [`glossary.md`](glossary.md).

## Связь с исходной постановкой

Этот файл не дублирует таблицу OR; он переводит **утверждённый канон** в безопасные **слайсы** работы для `start-feature`. Все требования OR уже разложены по файлам пакета в [`INDEX.md`](INDEX.md).

## Рекомендуемые первые слайсы

| ID | Слайс | Зачем первым | Разделы канона | Не включать в тот же PR |
|----|-------|--------------|----------------|-------------------------|
| S1 | Конверт команд LLM + семантика repair + граница `AgentMemoryCommandName` и действий планера; границы payload для `plan_traversal` / `finish_decision` / целевой `propose_links` | Снижает расхождение с контрактом конвейера W14 | [`llm-commands.md`](llm-commands.md); фрагменты [`runtime-flow.md`](runtime-flow.md), [`failure-retry-observability.md`](failure-retry-observability.md) | Полный движок графа и все тексты промптов |
| S2 | Каталог внешних событий: различение `event_type`, компактный канал vs verbose, долговечные vs эфемерные; маппинг stdout / журнал / compact.log | Развязывает CLI/Desktop от внутренних шагов | [`external-protocol.md`](external-protocol.md), [`failure-retry-observability.md`](failure-retry-observability.md) | Полные отдельные JSON-schema на каждый `event_type` в одном PR без утверждённого порядка |
| S3 | Проверка типизированных связей + `agent_memory_link_candidate.v1` vs текущие `pag_edges` / очередь pending | Фиксирует модель данных до масштабной работы над промптами | [`memory-graph-links.md`](memory-graph-links.md) | Все варианты текстов промптов |
| S4 | `ailit memory init`: целевой контракт выхода/сводки vs текущий `aborted` | Узкий пользовательский путь | [`external-protocol.md`](external-protocol.md) (CLI); при необходимости [`failure-retry-observability.md`](failure-retry-observability.md) | Полный API брокера |
| S5 | Ошибки и повторы, лимиты → partial, правила статуса `agent_memory_result.v1` | Закрывает OR-012/OR-013 до расширения LLM | [`failure-retry-observability.md`](failure-retry-observability.md) | Новые провайдеры LLM |

## Запрещённый слишком широкий scope

- Одна задача «реализовать весь AgentMemory» или «выровнять весь граф, все события, CLI и grants» без нарезки S1–S5.
- Подмена канона: старый монолитный план в `plan/` вместо пакета `context/algorithms/agent-memory/` как **источника целевого поведения** (SoT для цели продукта — этот пакет после утверждения).
- Добавление сырых промптов или CoT в компактный брокер-facing канал (нарушает [`prompts.md`](prompts.md) и анти-паттерны канона).

## Что нужно для start-feature

- Канон: [`INDEX.md`](INDEX.md) и связанные файлы в этом каталоге.

## Ожидаемые доказательства в конце

- Pytest: имена из раздела «Приёмка» в [`failure-retry-observability.md`](failure-retry-observability.md) (интерпретатор из venv репозитория).
- Журнал/compact: отсутствие сырых промптов в компактном канале там, где канон это требует.
- Ручной smoke (после реализации целевого UX): `ailit memory init ./` — ожидаемые `complete` / `partial` / целевой `blocked` и маркер `memory.result.returned` по тексту канона.

## Известные пробелы (gaps) для планирования

| ID | Пробел | Тип | Важность | Можно утвердить канон без кода? | Нужен waiver? | Следующий шаг |
|----|--------|-----|----------|----------------------------------|---------------|---------------|
| G-IMPL-1 | CLI: целевой видимый `blocked` vs текущий `aborted` / код выхода | implementation_backlog | major | да (цель ≠ текущее явно) | нет | Слайс S4 + код CLI |
| G-IMPL-2 | `grants` в ответе не подключены к проверке чтения в оболочке агента | implementation_backlog | major | да | нет | Слайс S2/S5 + интеграция AgentWork |
| G-IMPL-3 | Два шаблона id узла A (индексатор vs W14) | implementation_backlog | major | да | нет | Отдельная миграция / канон A-id |
| G-IMPL-4 | Целевой конверт `propose_links` и строгая валидация vs текущий реестр команд | implementation_backlog | major | да | нет | Слайс S1/S3 |
| G-IMPL-5 | Каталог D-OBS vs полный внутренний перечень журнала | implementation_backlog | minor | да | нет | Слайс S2 |
| G-DOC-1 | Нет полноформатных отдельных JSON-примеров на каждую envelope-команду (`finish_decision`, `propose_links`) | doc_incomplete | minor | да | нет | Слайс S1 или доработка после утверждения |
| G-DOC-2 | Нет отдельного полного schema-like блока payload на каждый `event_type` | doc_incomplete | minor | да | нет | Слайс S2 |
| G-NAMING-1 | В постановке встречается `user_request` как источник; в кандидате связи три значения `created_by` — уточнить при первом UX-слайсе связей | naming_tbd | minor | да | нет | Уточнить enum при реализации |
| G-VERIFY-1 | Ручной smoke end-to-end только после целевого UX CLI | verification_gap | info | да | нет | `11_test_runner` + ручная проверка |
