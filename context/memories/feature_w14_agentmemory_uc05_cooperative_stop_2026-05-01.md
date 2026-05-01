# W14 AgentMemory + UC-05 cooperative Stop (итерация закрыта)

Связано с: [`feature_w14_aw_am_fix_desktop_memory_2026-05-01.md`](feature_w14_aw_am_fix_desktop_memory_2026-05-01.md) (SoT, таймауты, D-OBS-1).

## Что зафиксировано в каноне

- **SoT:** `payload.agent_memory_result` v1, поле **`memory_continuation_required`** — вычисление `resolve_memory_continuation_required` (`agent_memory_result_v1.py`), публикация из AM; continuation gate в AW читает SoT, не только `memory_slice`.
- **W14 envelope:** каноникализация без лишнего repair (`validate_or_canonicalize_w14_command_envelope_object` и связка pipeline); compact **`memory.command.normalized`** — whitelist в `runtime-event-contract.md`.
- **UC-05:** broker JSON **`runtime.cancel_active_turn`** (`broker.py`, `work_agent.py`); Desktop — `ailit:brokerRequest`, `envelopeFactory.ts`, `DesktopSessionContext.tsx`; **не** supervisor JSON socket.
- **Тесты:** `test_g14r_uc05_cooperative_cancel_trace_ordering.py`, Vitest `envelopeFactory.cancel.test.ts`; финальный **11** зелёный по отчётам wave/final.

## Пробел

- Ручной полный Desktop smoke (Stop во время live `memory.query_context`) в wave4 task_5_1 Command **6** не выполнялся — остаётся опциональный human follow-up при приёмке продукта.

## Куда смотреть при изменениях

- `context/proto/broker-memory-work-inject.md`, `runtime-event-contract.md`, `desktop-electron-runtime-bridge.md`, `supervisor-json-socket.md` (N/A для cancel).
- `context/arch/system-elements.md` (P3).

**Оглавление:** [`../INDEX.md`](../INDEX.md) · [`index.md`](index.md)
