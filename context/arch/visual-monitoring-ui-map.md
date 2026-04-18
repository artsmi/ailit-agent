# Visual Monitoring UI Map (Operator-first)

## Назначение

Зафиксировать visual-first требования к operator UI до кодирования runtime.

Этот документ — экранная карта: **что показываем**, **откуда данные**, **какие события обязаны существовать**.

## Главный принцип

Визуализация — core capability: UI не читает ad-hoc stdout логов как источник истины.

Источники данных:

1. `events.jsonl` (канонический поток);
2. `state.json` (быстрая проекция);
3. `snapshots/*` (опционально для тяжелых экранов);
4. `artifacts/index.json` (ключевые результаты).

## Экран A: Run Dashboard

Показывает:

- активные runs (`run.started` без пары `run.finished/failed`);
- workflow/stage/task текущего run;
- blocked state (`workflow.blocked`) и причину;
- последние cost/token сигналы (`telemetry.usage.updated`, `model.usage.recorded`).

Источники:

- `state.json` + последние N событий из `events.jsonl`.

## Экран B: Workflow Graph

Показывает:

- граф stages;
- текущий stage highlight;
- историю transitions;
- human gates.

Источники:

- `workflow.loaded` + `stage.entered/exited` + `human.gate.*`;
- `workflows/resolved.json` как stable layout.

## Экран C: Agents Panel

Показывает:

- какие `agent_id` участвуют;
- какая роль сейчас активна;
- переключения ролей по stage/task.

Источники:

- correlation поля envelope + `task.*` события.

## Экран D: Session / Model Trace

Показывает:

- turns;
- latency;
- usage/tokens;
- provider/model ids (нормализованные).

Источники:

- `session.*`, `model.*`, `telemetry.usage.updated`.

Ограничения UX:

- prompt/user content показывается только если включен explicit operator mode;
- по умолчанию — hashes + короткие выдержки + ссылки на artifacts.

## Экран E: Tools And Permissions

Показывает:

- очередь tool calls;
- approvals;
- результаты и ошибки;
- side-effect класс.

Источники:

- `tool.*`, `permission.*`, `approval.*`.

## Экран F: Artifacts

Показывает:

- последние key artifacts;
- тип, размер, hash;
- связь с producer событием.

Источники:

- `artifact.materialized` + `artifacts/index.json`.

## Экран G: Cost And Budget

Показывает:

- token totals;
- cost estimates;
- пороги/budget signals (когда появятся в runtime).

Источники:

- `telemetry/*` + `model.usage.recorded`.

## Экран H: Context Usage (не путать с `context/*`)

Показывает:

- размер working context;
- compaction events (когда появятся);
- shortlist decisions (когда появятся).

Источники:

- пока через `session.turn.*` + будущие `context.*` runtime события (не файлы `context/*`).

## Экран I: Debug Bundle Export

Показывает:

- выбранный интервал событий;
- snapshot + manifest;
- redaction policy.

Источники:

- `.ailit/runs/<run_id>/*` целиком, но с фильтрами.

## Проверка полноты (тест этапа в терминах UI)

Для каждого блока UI выше должен существовать минимум один `event_type` из `runtime-event-contract.md`, который делает блок самодостаточным без частных логов.

## Связанные документы

- [`runtime-local-storage-model.md`](runtime-local-storage-model.md)
- [`../proto/runtime-event-contract.md`](../proto/runtime-event-contract.md)
- [`../INDEX.md`](../INDEX.md)
