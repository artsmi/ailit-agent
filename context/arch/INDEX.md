# Архитектура — индекс

Процессы ОС, границы подсистем desktop/runtime и точки интеграции. Протоколы обмена — в [`../proto/INDEX.md`](../proto/INDEX.md). **UC-03:** observability CLI `memory init` (`ailit-cli-*` / compact на stderr vs desktop flat) — [`../proto/memory-query-context-init.md`](../proto/memory-query-context-init.md).

| Документ | Содержание |
|----------|------------|
| [`system-elements.md`](system-elements.md) | Процессы P1–P6; P3 — broker/workers, UC 2.4, W14 канон envelope / `memory.command.normalized`, **UC-05** (`runtime.cancel_active_turn`, `chat_id`/`user_turn_id`), SoT `memory_continuation_required`, D-OBS-1 (proto). |
| [`desktop-pag-graph-snapshot.md`](desktop-pag-graph-snapshot.md) | Снимок PAG-графа в renderer, `pagDatabasePresent`, full load, поллер ожидания sqlite, 3D UI; **UC-04 A**, **D-TRACE-CONN-1** (`ailit:trace-conn-root:{namespace}`, корень при >1 компоненте после фильтра рёбер), порядок **X→Y** (§5.2 `architecture.md`), Refresh → `pag_snapshot_refreshed` / `pag_graph_rev_reconciled` (`pagGraphObservabilityCompact.ts`, proto 1_2); **warnings / graph_rev** — `pagGraphRevWarningFormat.ts` + trace deltas; **1.3** — `graphDataKey` (без `n` по числу нод), merge с сохранением `x..fz`, G16.4; gate Vitest §5.0 — `context/tests/INDEX.md` (12 файлов / 80 тестов), отчёт `11` — `artifacts/reports/test_run_11_final.md` при наличии. |
| [`w14-graph-highlight-m1.md`](w14-graph-highlight-m1.md) | Python: W14 `graph_highlight`, M1 builder (`W14GraphHighlightPathBuilder`), интеграция в `AgentMemoryQueryPipeline`, D16.1; граница M1 и итерации Memory 3D (v1 поля без изменений, отдельные compact-события по proto 1_2). |

**Связанные разделы:** [`../INDEX.md`](../INDEX.md), [`../proto/INDEX.md`](../proto/INDEX.md), [`../start/INDEX.md`](../start/INDEX.md), [`../tests/INDEX.md`](../tests/INDEX.md), [`../modules/INDEX.md`](../modules/INDEX.md).
