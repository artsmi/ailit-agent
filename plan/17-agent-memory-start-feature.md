# Рабочий процесс 17: план внедрения AgentMemory (`start-feature` / `start-fix`)

**Идентификатор:** `agent-memory-start-feature-17` (файл `plan/17-agent-memory-start-feature.md`).

**Статус:** план нарезки и дорожная карта внедрения; **не** входит в канон SoT. Целевое поведение и контракты — только в пакете канона по ссылкам ниже.

**Канон (единственный SoT по цели продукта):** [`../context/algorithms/agent-memory/INDEX.md`](../context/algorithms/agent-memory/INDEX.md) и файлы пакета рядом с ним.

Produced by: 106_implementation_plan_author

---

## 1. Цель и границы

### 1.1 Цель

Связать **утверждённый канон** AgentMemory с безопасными **слайсами** работ для `start-feature` / `start-fix`: каждый слайс имеет явные ссылки на разделы канона, запрет на слишком широкий scope и таблицу gaps, не дублируя текст канона.

### 1.2 Вне границ этого плана

- Замена или ослабление формулировок канона «в обход» `start-research` / user approval.
- Новые критерии приёмки или события, которых нет в каноне, без отдельного обновления канона.
- Хранение этого документа внутри `context/algorithms/**` (канон не содержит планов внедрения).

---

## 2. Обязательные требования к плану (норма репозитория)

1. **Каждый этап / слайс** имеет явную **ссылку на раздел(ы) канона** (`../context/algorithms/agent-memory/...`).
2. **Трассировка:** таблица в §3 связывает слайс → файлы канона → что проверяется; нет строк без ссылок на канон.
3. **Канон — источник целевого поведения**; план — порядок, нарезка, зависимости и критерии внедрения; противоречия оформляются как gap с отсылкой к канону.
4. **Критерии приёмки** в §5 ссылаются на канон (раздел «Приёмка», команды, имена тестов в [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md)) без выдуманных новых обязательных полей.
5. **Anti-patterns реализации** — ссылка на раздел «Do not implement» / аналог в соответствующих файлах канона, без копипасты всего канона.

---

## 3. Трассировка: слайсы → канон

| ID | Слайс | Зачем первым | Разделы канона (обязательные ссылки) | Не включать в тот же PR |
|----|--------|--------------|----------------------------------------|---------------------------|
| S1 | Конверт команд LLM + семантика repair + граница `AgentMemoryCommandName` и действий планера; границы payload для `plan_traversal` / `finish_decision` / целевой `propose_links` | Снижает расхождение с контрактом конвейера W14 | [`llm-commands.md`](../context/algorithms/agent-memory/llm-commands.md); фрагменты [`runtime-flow.md`](../context/algorithms/agent-memory/runtime-flow.md), [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md) | Полный движок графа и все тексты промптов |
| S2 | Каталог внешних событий: различение `event_type`, компактный канал vs verbose, долговечные vs эфемерные; маппинг stdout / журнал / compact.log | Развязывает CLI/Desktop от внутренних шагов | [`external-protocol.md`](../context/algorithms/agent-memory/external-protocol.md), [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md) | Полные отдельные JSON-schema на каждый `event_type` в одном PR без утверждённого порядка |
| S3 | Проверка типизированных связей + `agent_memory_link_candidate.v1` vs текущие `pag_edges` / очередь pending | Фиксирует модель данных до масштабной работы над промптами | [`memory-graph-links.md`](../context/algorithms/agent-memory/memory-graph-links.md) | Все варианты текстов промптов |
| S4 | `ailit memory init`: целевой контракт выхода/сводки vs текущий `aborted` | Узкий пользовательский путь | [`external-protocol.md`](../context/algorithms/agent-memory/external-protocol.md) (CLI); при необходимости [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md) | Полный API брокера |
| S5 | Ошибки и повторы, лимиты → partial, правила статуса `agent_memory_result.v1` | Закрывает OR-012/OR-013 до расширения LLM | [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md), [`runtime-flow.md`](../context/algorithms/agent-memory/runtime-flow.md) | Новые провайдеры LLM |

Дополнительные файлы пакета для контекста (ссылки при доработке смежных тем): [`prompts.md`](../context/algorithms/agent-memory/prompts.md), [`desktop-realtime-graph-protocol.md`](../context/algorithms/agent-memory/desktop-realtime-graph-protocol.md), [`glossary.md`](../context/algorithms/agent-memory/glossary.md).

---

## 4. Запрещённый слишком широкий scope

- Одна задача «реализовать весь AgentMemory» или «выровнять весь граф, все события, CLI и grants» без нарезки S1–S5.
- Подмена канона старым монолитным текстом в `plan/` вместо пакета [`agent-memory/INDEX.md`](../context/algorithms/agent-memory/INDEX.md) как SoT.
- Добавление сырых промптов или CoT в компактный брокер-facing канал (см. [`prompts.md`](../context/algorithms/agent-memory/prompts.md) и анти-паттерны канона).

---

## 5. Входы для `start-feature`

- Канон: [`../context/algorithms/agent-memory/INDEX.md`](../context/algorithms/agent-memory/INDEX.md) и связанные файлы.
- Артефакты target-doc pipeline (при необходимости): `context/artifacts/target_doc/human_review_packet.md`, `source_request_coverage.md`, `target_doc_quality_matrix.md`, `open_gaps_and_waivers.md` — **не** смешивать с каноном в `context/algorithms/**`.

---

## 6. Ожидаемые доказательства (из канона)

- Pytest: имена и группы из раздела приёмки в [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md) (интерпретатор из venv репозитория — см. [`context/start/repository-launch.md`](../context/start/repository-launch.md)).
- Журнал / compact: отсутствие сырых промптов там, где канон это требует ([`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md), [`external-protocol.md`](../context/algorithms/agent-memory/external-protocol.md)).
- Ручной smoke (после целевого UX): `ailit memory init ./` — ожидаемые `complete` / `partial` / целевой `blocked` и маркер `memory.result.returned` по тексту канона ([`external-protocol.md`](../context/algorithms/agent-memory/external-protocol.md)).

---

## 7. Известные gaps для планирования

| ID | Пробел | Тип | Важность | Ссылка на канон / следствие | Следующий шаг |
|----|--------|-----|----------|-----------------------------|---------------|
| G-IMPL-1 | CLI: целевой видимый `blocked` vs текущий `aborted` / код выхода | implementation_backlog | major | [`external-protocol.md`](../context/algorithms/agent-memory/external-protocol.md) | Слайс S4 + код CLI |
| G-IMPL-2 | `grants` в ответе не подключены к проверке чтения в оболочке агента | implementation_backlog | major | [`external-protocol.md`](../context/algorithms/agent-memory/external-protocol.md), [`runtime-flow.md`](../context/algorithms/agent-memory/runtime-flow.md) | Слайс S2/S5 + интеграция AgentWork |
| G-IMPL-3 | Два шаблона id узла A (индексатор vs W14) | implementation_backlog | major | [`memory-graph-links.md`](../context/algorithms/agent-memory/memory-graph-links.md) | Отдельная миграция / согласование A-id в каноне |
| G-IMPL-4 | Целевой конверт `propose_links` и строгая валидация vs текущий реестр команд | implementation_backlog | major | [`llm-commands.md`](../context/algorithms/agent-memory/llm-commands.md) | Слайс S1/S3 |
| G-IMPL-5 | Каталог D-OBS vs полный внутренний перечень журнала | implementation_backlog | minor | [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md) | Слайс S2 |
| G-DOC-1 | Нет полноформатных отдельных JSON-примеров на каждую envelope-команду | doc_incomplete | minor | [`llm-commands.md`](../context/algorithms/agent-memory/llm-commands.md) | Слайс S1 или доработка канона после согласования |
| G-DOC-2 | Нет отдельного полного schema-like блока payload на каждый `event_type` | doc_incomplete | minor | [`external-protocol.md`](../context/algorithms/agent-memory/external-protocol.md) | Слайс S2 |
| G-NAMING-1 | `user_request` как источник; несколько значений `created_by` у кандидата связи | naming_tbd | minor | [`memory-graph-links.md`](../context/algorithms/agent-memory/memory-graph-links.md) | Уточнить enum при реализации S3 |
| G-VERIFY-1 | Ручной smoke end-to-end только после целевого UX CLI | verification_gap | info | [`failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md) | `11_test_runner` + ручная проверка |

---

## 8. Связь с эталоном оформления планов

Структура жёстких границ, этапов и якорей в коде — по образцу [`plan/14-agent-memory-runtime.md`](14-agent-memory-runtime.md) (идентификатор процесса, цель, research/аудит, этапы G\*, критерии закрытия).
