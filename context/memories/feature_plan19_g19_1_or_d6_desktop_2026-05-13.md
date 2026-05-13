# Feature: план 19, G19.1 — OR-D6 в коде Desktop

## Задача

Слайс **G19.1**: инструментация compact-наблюдаемости **OR-D6** в пакете `desktop/` (renderer + main).

## Что зафиксировано в каноне

- `context/algorithms/desktop-stack/INDEX.md` § Observability: таблица OR-D6 согласована с реализацией; добавлены подразделы «Где в коде», граница с **D-OBS-1**, уточнение **Default** для постмортема.
- `context/modules/INDEX.md`, `context/tests/INDEX.md` — навигация к исходникам и Vitest вне gate §5.0.

## Поведение / контракт (по коду)

- Renderer: `desktop.session.broker_request`, `desktop.session.trace_merge` — `desktopSessionDiagnosticLog.ts`, окно throughput, renderer budget telemetry, вызовы из `DesktopSessionContext.tsx`.
- Main: `desktop.pag_slice.requested|completed|error` — `registerIpc.ts`; скаляр `stdoutByteLength` — `pagGraphBridge.ts`.

## Проверки (по артефактам **11**, не перезапускались ролью **13**)

- Desktop: `npm run test`, `typecheck`, `lint` — passed (`context/artifacts/test_report.md`).
- TC-SMOKE-01: `blocked_by_environment` в автопрогоне; repo-wide `pytest` в том же final **11** — not_run (см. Verification Gaps в том же отчёте).

## Связанные артефакты и план

- `context/artifacts/change_inventory.md` (producer `12_change_inventory`).
- План внедрения: `plan/19-desktop-stack-chat-freeze-pag-trace.md`.

## Риски / внимание

- Не смешивать **D-OBS-1** (`runtime-event-contract.md`, журнал AW↔AM) с console FC-3 OR-D6.
- До ручного smoke и отдельного Python-gate нельзя расширять формулировки «полная продуктовая верификация репозитория».

## Оглавление

- [`index.md`](index.md) — память итераций.
- [`../INDEX.md`](../INDEX.md) — вход в `context/`.
