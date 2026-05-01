# Протоколы и каналы — индекс

Канон обмена между CLI, supervisor, broker, desktop и журналами/трассами. Установка как артефакт — перекрёстно с [`../install/INDEX.md`](../install/INDEX.md) и [`install.md`](install.md).

| Документ | Содержание |
|----------|------------|
| [`install.md`](install.md) | Канон ссылок на установку: `scripts/install`, связь со [`../start/repository-launch.md`](../start/repository-launch.md). |
| [`supervisor-json-socket.md`](supervisor-json-socket.md) | Learn: JSON по строкам на `supervisor.sock`; команды `status`, `brokers`, `create_or_get_broker`, `stop_broker`. UC-05 cancel **не** здесь — см. примечание в файле и `desktop-electron-runtime-bridge.md`. |
| [`desktop-electron-runtime-bridge.md`](desktop-electron-runtime-bridge.md) | Electron main ↔ supervisor/broker sockets, `execFile` для `ailit memory pag-slice`, trace JSONL; **UC-05** Cooperative Stop (`runtime.cancel_active_turn`, renderer `envelopeFactory` / `DesktopSessionContext`). |
| [`pag-slice-desktop-renderer.md`](pag-slice-desktop-renderer.md) | Семантика `missing_db` и full load в desktop renderer; транспорт IPC без изменений в 1.1; additive примечание `graph_rev` на корне ответа. |
| [`desktop-memory-3d-observability.md`](desktop-memory-3d-observability.md) | §3.2 / UC-03–06: compact-события `pag_graph_rev_reconciled`, `pag_snapshot_refreshed`, `memory_recall_ui_phase`; D-PROD-1 (renderer-only rev reconcile); D-OBS-HI-1 (whitelist W14 v1); emit-строки в renderer — `pagGraphObservabilityCompact.ts`. |
| [`ailit-memory-w14-graph-highlight.md`](ailit-memory-w14-graph-highlight.md) | W14 `memory.w14.graph_highlight` v1: наполнение через M1 в Python runtime; D16.1; не путать с IPC pag-slice. |
| [`broker-memory-work-inject.md`](broker-memory-work-inject.md) | UC 2.4: trace-тройка Work → Memory → `context.memory_injected` v2; pathless v1; post-pipeline Memory. **W14:** SoT `agent_memory_result`, **`memory_continuation_required`** (`agent_memory_result_v1.py` / AM), continuation gate в Work; **UC-05** `runtime.cancel_active_turn` через broker. |
| [`runtime-event-contract.md`](runtime-event-contract.md) | **D-OBS-1:** whitelist compact-событий AW↔AM + `memory.command.normalized`, `session.cancelled` / `action.cancelled` (UC-05); единый литерал `reason`=`continuation`; проверка `rg` в файле. |

**Связанные разделы:** [`../INDEX.md`](../INDEX.md), [`../install/INDEX.md`](../install/INDEX.md), [`../start/INDEX.md`](../start/INDEX.md), [`../arch/INDEX.md`](../arch/INDEX.md), [`../tests/INDEX.md`](../tests/INDEX.md).
