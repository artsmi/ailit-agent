# Desktop: канон графа памяти и 3dmvc

> **Аннотация:** частичный канон для Electron-клиента `desktop/`: как данные AilitMemory и PAG попадают в слой Model/Controller, как во View попадает только подготовленный граф (паттерн **3dmvc**), инварианты производительности и отображения, связь с протоколом памяти на границе агента. Полный Electron-стек здесь **не** описывается.

## Статус

`approved` — явное подтверждение пользователя в чате Cursor (**2026-05-12**).

## Зачем этот пакет

Канон нужен, чтобы `start-feature` / `start-fix` и ревью не расходились с фактами кода по путям trace → merged → 3D: отдельно от пакета [`../agent-memory/`](../agent-memory/INDEX.md) фиксируются **границы UI**, **лимиты slice/UI**, **политика remount** и **представление графа во View**.

## Связь с исходной постановкой (Cycle C)

Ниже — требования постановки пользователя для **этого** пакета (ID **OR-001…OR-012** в формулировках пакета `context/algorithms/desktop/`, не путать с legacy desktop OR-001…OR-017 в архивном оглавлении [`../agent-memory/INDEX.md`](../agent-memory/INDEX.md)).

| ID | Суть требования |
|----|-----------------|
| **OR-001** | Канон Desktop для AilitMemory: UI↔память, границы; не полное описание Electron. |
| **OR-002** | Явный **3dmvc:** вход памяти → Model/Controller → структура графа → View. |
| **OR-003** | View не показывает изолированные узлы (степень 0) в scene graph при **target default D-ORPHAN-B**; waiver **D-ORPHAN-C** только с named approval. |
| **OR-004** | Стабильность View: анти-мигание, ограничение лишних refresh/remount. |
| **OR-005** | Канон размещён в **`context/algorithms/desktop/`** (частичный scope). |
| **OR-006** | Не планировать рефакторинг Python runtime AgentMemory без явного согласования. |
| **OR-007** | Материал перенесён из legacy-файла `../agent-memory/desktop-realtime-graph-protocol.md` (теперь stub); SoT — этот пакет. |
| **OR-008** | Паттерны доноров (плотный граф, ссылки, инкремент) — идеи, не копипаст. |
| **OR-009** | Целевое поведение согласовано с проверяемой current reality (см. разделы в [`graph-3dmvc.md`](graph-3dmvc.md) и [`realtime-graph-client.md`](realtime-graph-client.md)). |
| **OR-010** | Лимиты узлов/рёбер в каноне = SoT кода: **100 000** узлов / **200 000** рёбер (`pagGraphLimits`, `pag_slice_caps`, pytest выравнивания). |
| **OR-011** | Ключ данных графа согласован с `computeMemoryGraphDataKey` (**без** `graphRevByNamespace` в сериализации ключа); регрессия **`TC-3D-UC04-03`**. |
| **OR-012** | Единый контроллер подсветки для 2D и 3D: на View обе панели читают `searchHighlightsByNamespace` снимка (**G3** для 2D); arch [`../../arch/desktop-pag-graph-snapshot.md`](../../arch/desktop-pag-graph-snapshot.md) согласован с кодом `MemoryGraphPage` / `MemoryGraph3DPage`. |

## Scope

### In scope

- Паттерн 3dmvc, инварианты View, политика orphan/highlight, performance-классы — [`graph-3dmvc.md`](graph-3dmvc.md).
- Target flow, state lifecycle, observability, примеры, команды приёмки, killer-feature как паттерны — [`realtime-graph-client.md`](realtime-graph-client.md).
- Расшифровки — [`glossary.md`](glossary.md).

### Out of scope

- Полное описание оболочки Electron, брендбук — [`../../../docs/web-ui-book/INDEX.md`](../../../docs/web-ui-book/INDEX.md).
- Изменения producer AgentMemory / схемы PAG в Python — только с отдельным согласованием (**OR-006**).

## Навигация по пакету

| Файл | Для кого | Содержание |
|------|-----------|------------|
| [`graph-3dmvc.md`](graph-3dmvc.md) | Автор фичи по 3D/графу | Роли M/C/View, DTO сцены, OR-003 (D-ORPHAN-A/B/C), highlight policy, performance (**D-PERF-1**, класс G19.4 ingress), anti-patterns. |
| [`realtime-graph-client.md`](realtime-graph-client.md) | Автор IPC/trace/slice | Поток от сессии до сцены, фазы state lifecycle, события observability (в т.ч. `desktop.session.trace_merge` + `batch_size` при батче), шаг **6b** G19.4 ingress coalesce, примеры, команды, acceptance. |
| [`glossary.md`](glossary.md) | Все читатели пакета | Минимум терминов и сокращений. |
| [`donors/INDEX.md`](donors/INDEX.md) | Авторы target-doc и фич | Taken / Rejected / Not researched по внешним идеям (без pipeline-артефактов). |

## Связанные каноны и планы

- Чат, trace, PAG rev, freeze и диагностика (отдельный пакет): [`../desktop-stack/INDEX.md`](../desktop-stack/INDEX.md).
- Память на границе агента: [`../agent-memory/external-protocol.md`](../agent-memory/external-protocol.md).
- Снимок PAG для Desktop: [`../../arch/desktop-pag-graph-snapshot.md`](../../arch/desktop-pag-graph-snapshot.md).
- План внедрения (не часть канона SoT): [`../../../plan/18-desktop-memory-graph-3dmvc.md`](../../../plan/18-desktop-memory-graph-3dmvc.md).
- Legacy-файл протокола в пакете agent-memory: [`../agent-memory/desktop-realtime-graph-protocol.md`](../agent-memory/desktop-realtime-graph-protocol.md) — **только redirect** на этот пакет.

## Миграция

Нормативный текст и числа, ранее лежавшие в `desktop-realtime-graph-protocol.md`, перенесены сюда. В старом пути остаётся stub: не использовать его как SoT для лимитов, remount и конфигурации.
