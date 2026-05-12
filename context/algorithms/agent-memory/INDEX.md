# Пакет целевого алгоритма AgentMemory

Этот каталог — **канон целевого поведения** модуля памяти агента после утверждения человеком. Здесь описано, что система должна делать для пользователя и для разработчиков, которые запускают `start-feature` / `start-fix`, без ссылок на временные артефакты исследовательского pipeline.

**Аннотация:** начните с раздела «Назначение», затем откройте файл по теме (runtime, протокол, граф, команды LLM и т.д.). Расшифровки сокращений — в [`glossary.md`](glossary.md).

## Статус

`approved` — явное подтверждение пользователя в чате Cursor (2026-05-03). Реализация runtime и CLI выравнивалась итерациями feature (slices S1–S5, 2026-05-04); при расхождении кода и текста приоритет у формулировок этого пакета после обновления канона.

## Назначение

Зафиксировать **целевое поведение** AgentMemory: кто инициирует запрос, как рантайм владеет базой и обходом, как LLM работает только в закрытом JSON-протоколе, какие типы рёбер графа допустимы, какие события видят CLI и брокер, и когда допустимы статусы `complete`, `partial`, `blocked`.

## Части пакета

| Файл | Содержание |
|------|------------|
| [`glossary.md`](glossary.md) | Расшифровки OR, W14, SoT, D-OBS и других сокращений. |
| [`runtime-flow.md`](runtime-flow.md) | Целевая машина состояний: intake → БД → LLM → срез → обход → узлы и связи → сводка → завершение и ограниченный partial. |
| [`memory-graph-links.md`](memory-graph-links.md) | Типы связей (`contains`, `imports`, …), доказательства и уверенность, валидация в рантайме и кандидаты от LLM. |
| [`llm-commands.md`](llm-commands.md) | Команды от рантайма к LLM: конверт ответа, действия планера, фаза исправления невалидного JSON, целевая команда `propose_links`. |
| [`prompts.md`](prompts.md) | Роли промптов по фазам, многоязычие и `file_kind`, запреты на CoT и сырые дампы. |
| [`external-protocol.md`](external-protocol.md) | Инициаторы (оболочка агента, CLI, клиент брокера), формат запроса, события на границе, команда `ailit memory init`. |
| [`desktop-realtime-graph-protocol.md`](desktop-realtime-graph-protocol.md) | Desktop (Electron): broker trace, PAG merge, 3D граф, подсветка из trace, целевой конфиг `~/.ailit/desktop`, multi-project и лимиты; **отдельная** матрица desktop OR-001…OR-017 ниже. |
| [`failure-retry-observability.md`](failure-retry-observability.md) | Ошибки и повторы, лимиты и partial, журнал и компактные логи, критерии приёмки и имена тестов pytest. |
| План внедрения | [`../../../plan/17-agent-memory-start-feature.md`](../../../plan/17-agent-memory-start-feature.md) — нарезка `start-feature`, слайсы S1–S5, gaps; **не** часть канона SoT. |

## Исходная постановка (полная матрица OR-001…OR-015)

Ниже — все требования исходного запроса пользователя в сжатом виде. В каждом **отдельном** файле пакета есть раздел «Связь с исходной постановкой» только с теми OR, которые относятся к этому файлу, с чуть более развёрнутой формулировкой.

| ID | Требование | Ожидаемое место в пакете |
|----|------------|---------------------------|
| OR-001 | Канон в `context/algorithms/agent-memory/` с этим `INDEX.md` и разбиением по файлам; обнаруживаемость из [`../INDEX.md`](../INDEX.md) | Этот файл и корневой индекс алгоритмов |
| OR-002 | AgentMemory как модуль с NL-запросами через брокер; `complete` / `partial` или `blocked` только при сбое API LLM или исчерпании ограниченных повторов | `runtime-flow.md`, `failure-retry-observability.md` |
| OR-003 | Обход дерева и связи графа A/B/C/D; типизированные связи с доказательствами; рантайм валидирует, LLM только предлагает кандидатов | `memory-graph-links.md`, `runtime-flow.md` |
| OR-004 | Контракт инициаторов (оболочка агента / CLI / клиент брокера): поля, `query_id`, `user_turn_id`, namespace, корень проекта, лимиты; схемоподобный JSON | `external-protocol.md`, `runtime-flow.md` |
| OR-005 | Целевая машина состояний: intake → проверка БД → шаги → LLM → срез → обход → узлы и связи → сводка → завершение → ограниченный partial | `runtime-flow.md` |
| OR-006 | Протокол команд runtime→LLM: команды, вход/выход, запрещённое и обязательное, примеры восстановления после ошибки; разделение владения рантайм и LLM | `llm-commands.md` |
| OR-007 | Типы связей B/C/D из постановки с confidence и источником | `memory-graph-links.md` |
| OR-008 | Промпты для нескольких языков и не-кода; `file_kind`, сегментация; запреты CoT и сырых дампов | `prompts.md`, `llm-commands.md` |
| OR-009 | Каталог промптов по состояниям/фазам | `prompts.md` |
| OR-010 | Внешние события: heartbeat, progress, выделенные узлы, кандидаты и обновления связей, partial/complete/blocked; схема и правила логов | `external-protocol.md`, `failure-retry-observability.md` |
| OR-011 | CLI `ailit memory init`: запрос по умолчанию, прогресс, логи узлов и связей, семантика выхода | `external-protocol.md`, `failure-retry-observability.md` |
| OR-012 | Конверт результата `agent_memory_result.v1` | `runtime-flow.md`, `external-protocol.md` |
| OR-013 | Ошибки и повторы: невалидный JSON, неверный id узла, отклонение связи, лимиты, отсутствие файла, неизвестный язык | `failure-retry-observability.md` |
| OR-014 | Минимум четыре человекочитаемых сценария (в постановке — пять направлений) | Примеры по файлам и этот индекс |
| OR-015 | Проверяемые критерии приёмки из постановки | `INDEX.md`, `failure-retry-observability.md` |

## Desktop: постановка и трассировка OR-001…OR-017

Таблица ниже относится **только** к протоколу Desktop realtime graph (файл [`desktop-realtime-graph-protocol.md`](desktop-realtime-graph-protocol.md)). ID **не** совпадают с legacy OR-001…OR-015 в разделе «Исходная постановка» выше.

| ID | Требование (сжато) | Где раскрыто в каноне |
|----|--------------------|------------------------|
| OR-001 | Потоки AgentWork/AgentMemory, trace, PAG без смешения процессов | `desktop-realtime-graph-protocol.md` — текущая реализация, целевой flow, каналы |
| OR-002 | 3D memory в realtime, инварианты обновления | Там же — 3D pipeline, PAG merged |
| OR-003 | Временные представления графа (merged/session/дельты, без SQLite) | Там же — PAG, «временность» |
| OR-004 | Подсветка: trace → визуальное состояние | Там же — подсветка из trace, события |
| OR-005 | Структура Desktop main/preload/renderer | Там же — процессы и границы |
| OR-006 | Брендбук → `docs/web-ui-book/` (док репозитория), синхронно с публикацией канона | `desktop-realtime-graph-protocol.md` — раздел web-ui-book; [`../../../docs/web-ui-book/INDEX.md`](../../../docs/web-ui-book/INDEX.md) |
| OR-007 | Desktop vs брокер, сокеты, IPC | Там же — broker, trace subscription |
| OR-008 | Связь с пакетом AgentMemory, этот файл + INDEX | Этот `INDEX.md`, `desktop-realtime-graph-protocol.md` |
| OR-009 | Целевой конфиг `~/.ailit/desktop`, yaml, пути в комментариях | `desktop-realtime-graph-protocol.md` — целевая схема config |
| OR-010 | 1–5 проектов в чате, primary/highlight | Там же — multi-project, backlog `namespaces[0]` |
| OR-011 | Подсветка/ноды без полной перерисовки; target vs remount | Там же — 3D, целевые требования |
| OR-012 | Изолированные проекты, синтетический корень | Там же — проекция, PAG |
| OR-013 | Стабильность после загрузки, freeze, remount | Там же — 3D pipeline, FR |
| OR-014 | Появление ноды: связь к родителю; summary не обязательна | Там же — PAG дельты, placeholder |
| OR-015 | Протокол для внешней интеграции (типы сообщений) | Там же — Target flow, события |
| OR-016 | Абстрактный алгоритм подключения Desktop | Там же — абстрактный алгоритм |
| OR-017 | `max_nodes` 100000 в yaml; mismatch с caps | Там же — конфиг, acceptance |

## Трассировка OR → файлы пакета

| ID | Где раскрыто в каноне |
|----|------------------------|
| OR-001 | Этот `INDEX.md` и [`../INDEX.md`](../INDEX.md) |
| OR-002 | `runtime-flow.md`, `failure-retry-observability.md` |
| OR-003 | `memory-graph-links.md`, `runtime-flow.md` |
| OR-004 | `external-protocol.md`, `runtime-flow.md` |
| OR-005 | `runtime-flow.md` |
| OR-006 | `llm-commands.md` |
| OR-007 | `memory-graph-links.md` |
| OR-008 | `prompts.md`, `llm-commands.md` |
| OR-009 | `prompts.md` |
| OR-010 | `external-protocol.md`, `failure-retry-observability.md` |
| OR-011 | `external-protocol.md`, `failure-retry-observability.md` |
| OR-012 | `runtime-flow.md`, `external-protocol.md` |
| OR-013 | `failure-retry-observability.md` |
| OR-014 | Индекс примеров ниже |
| OR-015 | `failure-retry-observability.md`, этот индекс |

## Индекс примеров (OR-014)

Сценарии сформулированы в каноне по смыслу следующим образом (полные тексты — в соответствующих разделах файлов пакета):

1. Запрос от оболочки агента через брокер — подбор файлов для изменения сервера.
2. CLI `ailit memory init` — цель по умолчанию, прогресс, итог.
3. Несколько языков — Go, C++, TypeScript без допущения «только Python».
4. Документация — связь `references` от заголовка markdown к коду.
5. Ошибка и восстановление — невалидный JSON с одним циклом исправления; отсутствие файла → `partial`.

## Текущая реализация и цель

В каждом крупном файле пакета: краткий блок **«Текущая реализация»** (что уже есть в коде по смыслу), затем **«Целевое поведение»**. Расхождения, которые сознательно оставлены до кода, помечаются как **`implementation_backlog`** до выравнивания реализации.
