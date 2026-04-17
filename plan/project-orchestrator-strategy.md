# Стратегия верхнего orchestrator-а проектов

## Цель

Зафиксировать стратегию верхнего orchestrator-а, который стоит **над** `ai-multi-agents` и управляет жизненным циклом целого проекта, а не отдельной feature-итерацией.

Этот документ нужен как стратегическая ветка развития. Он не заменяет текущий план по `runtime core`, а описывает следующий уровень системы, к которому можно вернуться позже.

## Главная идея

Нужно строить не "полностью автономного директора разработки", а **semi-autonomous project orchestrator** с обязательными human gates.

То есть orchestrator:

- принимает цель пользователя;
- собирает project brief;
- декомпозирует цель в milestones;
- запускает нужные workflows;
- отправляет execution batches в `ai-multi-agents`;
- собирает статусы, риски и артефакты обратно;
- предлагает следующий шаг;
- останавливается на согласовании там, где это критично.

## Что он НЕ должен делать

На первом этапе orchestrator не должен:

- пытаться сам полностью реализовывать проект;
- заменять `ai-multi-agents`;
- принимать все архитектурные решения без человека;
- бесконтрольно плодить агентов;
- пытаться быть fully autonomous CTO.

Его задача не заменить нижние уровни, а стать **project control plane**.

## Место в общей системе

Итоговая трехуровневая модель должна стать четырехуровневой:

1. `project orchestrator`
2. `ai-multi-agents` как workflow shell
3. `ailit-agent` как runtime core
4. providers and tools

## Роли уровней

### `project orchestrator`

Отвечает за:

- intake пользовательской цели;
- проектный roadmap;
- milestones;
- sequencing между большими блоками работ;
- human approval gates;
- project state;
- перепланирование;
- запуск нужных workflow в `ai-multi-agents`.

### `ai-multi-agents`

Отвечает за:

- analyst workflow;
- architect workflow;
- planner workflow;
- developer workflow;
- review workflow;
- writer workflow;
- исполнение отдельных project batches.

### `ailit-agent`

Отвечает за:

- runtime;
- tools;
- session loop;
- providers;
- local state and events;
- token/cost control;
- runtime substrate для нижних workflow.

## Типовой сценарий работы

Пример пользовательского запроса:

> Нужно реализовать интеграцию с MySQL.

Правильный путь работы orchestrator-а:

1. Принять `ProjectIntent`
2. Построить `ProjectBrief`
3. Запустить analysis/discovery workflow
4. Получить draft ТЗ
5. Остановиться на согласовании ТЗ с пользователем
6. После согласования запустить architecture workflow
7. Построить milestones
8. Разбить milestones на execution batches
9. Передать batches в `ai-multi-agents`
10. Собрать статусы, риски и результаты
11. Обновить roadmap и предложить следующий шаг

## Ключевые сущности

Минимальный набор сущностей:

- `ProjectIntent`
- `ProjectBrief`
- `OpenQuestion`
- `TechnicalSpecification`
- `ArchitectureDecision`
- `Milestone`
- `ExecutionBatch`
- `ApprovalGate`
- `ProjectState`
- `ProjectSnapshot`
- `ProjectRisk`
- `ProjectEvent`

## Предлагаемая модель данных

### `ProjectIntent`

Хранит:

- исходный запрос пользователя;
- ограничения;
- ожидания;
- стек;
- deadline, если есть;
- cost limits, если есть.

### `ProjectBrief`

Хранит:

- краткое описание цели;
- рамки проекта;
- известные ограничения;
- список неизвестных;
- предполагаемый тип работы.

### `Milestone`

Хранит:

- цель milestone;
- expected outputs;
- dependencies;
- approval requirements;
- execution status.

### `ExecutionBatch`

Хранит:

- конкретный workflow task;
- какой workflow запускать;
- какие артефакты нужны на входе;
- какие критерии приемки на выходе;
- кто должен принять результат.

## Локальное хранение

Этот orchestrator должен быть local-first.

Рекомендуемая структура:

```text
projects/
  <project_id>/
    brief.md
    roadmap.md
    state.json
    intent.json
    approvals/
    milestones/
    batches/
    events/
    artifacts/
    snapshots/
```

### Что где хранить

- `brief.md`  
  Человеко-читаемое краткое описание проекта

- `roadmap.md`  
  Актуальный roadmap и milestones

- `state.json`  
  Машинное состояние проекта

- `intent.json`  
  Исходный формализованный запрос

- `approvals/*`  
  Согласования ТЗ, архитектуры, scope changes

- `milestones/*`  
  Отдельные milestone-документы

- `batches/*`  
  Очередь и история execution batches

- `events/*`  
  Project-level event log

- `artifacts/*`  
  Результаты верхнеуровневых workflow

- `snapshots/*`  
  Снимки project state для отладки и resume

## Основные модули верхнего orchestrator-а

### 1. Intake Manager

Отвечает за:

- первичный разбор запроса;
- извлечение явных ограничений;
- постановку clarifying questions;
- создание `ProjectIntent`.

### 2. Brief Builder

Отвечает за:

- преобразование intent в project brief;
- фиксацию unknowns;
- подготовку входа для analyst workflow.

### 3. Planning Controller

Отвечает за:

- milestones;
- sequencing;
- dependencies;
- следующую рекомендуемую фазу работ.

### 4. Workflow Router

Отвечает за:

- выбор, какой workflow запускать;
- передачу задачи в `ai-multi-agents`;
- контроль статуса batch execution.

### 5. Approval Manager

Отвечает за:

- обязательные human gates;
- фиксацию approved/rejected/needs_changes;
- запрет движения дальше без обязательного согласования.

### 6. Project State Store

Отвечает за:

- project lifecycle state;
- snapshots;
- event log;
- resume and recovery.

### 7. Status Synthesizer

Отвечает за:

- сбор статусов по milestones;
- список открытых рисков;
- понятный "что дальше" для пользователя.

## Human gates

Это обязательная часть архитектуры.

На первой версии нельзя пропускать подтверждение пользователя на:

- итоговое ТЗ;
- выбор архитектурного варианта;
- рискованные миграции;
- изменения scope;
- rollout decisions;
- budget exceptions.

## Как делегировать в `ai-multi-agents`

Верхний orchestrator не должен сам исполнять analyst/architect/developer роли.

Он должен:

1. Сформировать `ExecutionBatch`
2. Определить, какой workflow нужен
3. Передать batch в `ai-multi-agents`
4. Получить результат
5. Обновить `ProjectState`
6. Принять решение:
   - следующий batch;
   - согласование;
   - перепланирование;
   - завершение

## Типы workflow-запусков

Минимально нужны такие типы:

- `discovery`
- `analysis`
- `architecture`
- `planning`
- `implementation_batch`
- `review_batch`
- `verification_batch`
- `documentation_sync`
- `project_replan`

## Реалистичный MVP

Ниже то, что реально делать первым.

### MVP scope

Сделать orchestrator, который умеет:

1. принять запрос;
2. собрать brief;
3. прогнать analysis;
4. вынести draft ТЗ на согласование;
5. после согласования построить milestones;
6. запускать execution batches по одной штуке;
7. собирать project status;
8. показывать пользователю следующий рекомендуемый шаг.

### Что НЕ входит в MVP

- полностью автономная архитектура без человека;
- автоматическое ведение десятков команд одновременно;
- self-healing project program manager;
- free-form swarm orchestration большого масштаба;
- fully dynamic internet-derived agent ecosystem.

## Этапы реализации

### Этап 1. Project intake and brief

**Что сделать**

- ввести `ProjectIntent` и `ProjectBrief`;
- научиться собирать входные данные проекта;
- фиксировать open questions.

**Критерии приемки**

- любой запрос превращается в структурированный brief;
- есть список неизвестных;
- можно остановиться и задать вопросы пользователю.

**Тесты**

- smoke test на 3-5 разных проектных запросов;
- test на корректную фиксацию unknowns.

### Этап 2. Approval-aware specification flow

**Что сделать**

- запуск analyst workflow;
- фиксация draft ТЗ;
- human approval gate.

**Критерии приемки**

- orchestrator не идет дальше без согласования ТЗ;
- история согласований сохраняется;
- есть явный approved/rejected state.

**Тесты**

- approve path test;
- reject and revise path test.

### Этап 3. Milestone planner

**Что сделать**

- построение roadmap;
- milestones;
- sequencing и dependencies.

**Критерии приемки**

- после утвержденного ТЗ есть milestones;
- milestones пригодны для деления на execution batches;
- roadmap читаем и человеком, и системой.

**Тесты**

- roadmap generation test;
- dependency validation test.

### Этап 4. Batch router to `ai-multi-agents`

**Что сделать**

- передача milestone parts в `ai-multi-agents`;
- возврат статусов и артефактов;
- фиксация batch lifecycle.

**Критерии приемки**

- orchestrator умеет запускать batches;
- умеет получать результаты обратно;
- умеет определять следующий шаг.

**Тесты**

- batch submission smoke test;
- batch result ingestion test.

### Этап 5. Project status and replan

**Что сделать**

- project snapshots;
- risks;
- next-step recommendations;
- controlled replan.

**Критерии приемки**

- пользователь может увидеть текущее состояние проекта;
- при проблеме orchestrator умеет предложить replan;
- история проекта не теряется.

**Тесты**

- snapshot generation test;
- replan trigger test;
- blocked milestone test.

## Acceptance vision

Система будет считаться успешной на этом направлении, если пользователь сможет сказать:

> Реализуй интеграцию с MySQL

и получить управляемый процесс:

1. brief;
2. draft ТЗ;
3. согласование;
4. milestones;
5. последовательный запуск execution batches;
6. статусы;
7. следующий шаг.

Без иллюзии полной автономии, но с реальной полезностью.

## Честный вывод

Это не "нереально". Это реально, если:

- делать это как верхний orchestrator;
- оставлять human gates;
- делегировать реализацию вниз;
- строить local-first state;
- запускать workflow поэтапно;
- не пытаться сразу построить fully autonomous software company.

Правильная цель:

**не автономный бог-оркестратор, а управляемый project orchestrator поверх `ai-multi-agents` и `ailit-agent`.**
