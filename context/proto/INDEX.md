# Протоколы и каналы — индекс

| Документ | Содержание |
|----------|------------|
| [`install.md`](install.md) | Канон ссылок на установку: `scripts/install`, связь со [`../start/repository-launch.md`](../start/repository-launch.md). |
| [`supervisor-json-socket.md`](supervisor-json-socket.md) | Learn: JSON по строкам на `supervisor.sock`; команды `status`, `brokers`, `create_or_get_broker`, `stop_broker`. |
| [`desktop-electron-runtime-bridge.md`](desktop-electron-runtime-bridge.md) | Learn: Electron main ↔ supervisor/broker sockets, `execFile` для `ailit memory pag-slice`, trace JSONL. |
| [`pag-slice-desktop-renderer.md`](pag-slice-desktop-renderer.md) | Семантика `missing_db` и full load в desktop renderer; транспорт IPC без изменений в 1.1; additive примечание `graph_rev` на корне ответа. |
| [`desktop-memory-3d-observability.md`](desktop-memory-3d-observability.md) | §3.2 / UC-03–06: compact-события `pag_graph_rev_reconciled`, `pag_snapshot_refreshed`, `memory_recall_ui_phase`; D-PROD-1 (renderer-only rev reconcile); D-OBS-HI-1 (whitelist W14 v1); emit-строки в renderer — `pagGraphObservabilityCompact.ts`. |
| [`ailit-memory-w14-graph-highlight.md`](ailit-memory-w14-graph-highlight.md) | W14 `memory.w14.graph_highlight` v1: наполнение через M1 в Python runtime; D16.1; не путать с IPC pag-slice. |
| [`broker-memory-work-inject.md`](broker-memory-work-inject.md) | UC 2.4: trace-тройка Work → Memory → `context.memory_injected` v2; pathless v1; post-pipeline Memory (merge stub, запрет path-fallback при `w14_command_output_invalid`). |
