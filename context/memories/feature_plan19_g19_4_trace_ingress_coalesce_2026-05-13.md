# Feature: план 19 G19.4 — ingress coalesce live trace (renderer)

## Что изменилось в продукте

- Live trace в Electron renderer: батчинг перед коммитом `rawTraceRows` (`enqueueTraceRows` / flush → единый `mergeRows`), terminal-aware flush, SoT терминальных строк — `traceTerminalKinds.ts`, чистая логика — `traceIngressCoalesce.ts` (`DESKTOP_TRACE_COALESCE_MAX_BUFFER_ROWS`), компактный лог `desktop.session.trace_merge` с опциональным `batch_size` при merge >1 строки.

## Канон (`context/*`)

- Якорь G19.4 — `context/arch/desktop-pag-graph-snapshot.md#live-trace-ingress-coalesce`.
- Алгоритмы: `context/algorithms/desktop/realtime-graph-client.md` (шаг 6b, observability `trace_merge`), `graph-3dmvc.md` (Controller, **D-PERF-1**).
- Индексы: `context/arch/INDEX.md`, `context/modules/INDEX.md`, `context/tests/INDEX.md`, `context/algorithms/desktop/INDEX.md`.

## Проверки

- Evidence: `context/artifacts/test_report.md` (Vitest `traceIngressCoalesce.test.ts`, `chatTraceProjector.test.ts`, typecheck). Полный OR-D6 / live smoke в этом gate не обязательны — см. gaps в том же отчёте.

## Связанные артефакты

- Постановка: `plan/19-desktop-stack-chat-freeze-pag-trace.md` (G19.4), `context/artifacts/tasks/task_19_4.md`.
- Inventory: `context/artifacts/change_inventory.md`.

**Оглавление памяти:** [`index.md`](index.md).
