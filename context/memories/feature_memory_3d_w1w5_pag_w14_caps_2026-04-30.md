# Feature: Memory 3D, PAG snapshot, graph_rev warnings, W14, caps (W1–W6)

**Дата:** 2026-04-30  
**План:** `context/artifacts/plan.md`, волны W1–W6 (в т.ч. observability compact + pytest guard **D-PROD-1**); ветка `fix/desktop_memory`.  
**Верификация:** финальный gate §5.0 — Vitest **12** файлов / **80** тестов (`context/tests/INDEX.md`); pytest `test_w14_graph_highlight_path` + `test_pag_graph_trace_w14_highlight` — **7** passed (в т.ч. запрет literal `pag_graph_rev_reconciled` в Python). Сводный артефакт `11` — `context/artifacts/reports/test_run_11_final.md`, если присутствует в клоне.

## Процессы и модули

- **P3 Desktop (renderer):** `pagGraphSessionStore`, `pagGraphObservabilityCompact`, `pagGraphTraceDeltas`, `pagHighlightFromTrace`, `loadPagGraphMerged`, `memoryGraphDataKey`, `memoryGraphState`, `memoryGraph3DResolvedColors` / `memoryGraph3DLineStyle`, `pagGraphLimits`, `chatTraceAmPhase`, `DesktopSessionContext`, `MemoryGraph3DPage` / `MemoryGraphPage`, стили.
- **Модуль предупреждений rev:** `desktop/src/renderer/runtime/pagGraphRevWarningFormat.ts` — `formatPagGraphRevMismatchWarning`, `dedupePagGraphSnapshotWarnings`, ключи/парсинг; импорты из `pagGraphSessionStore.ts`, `pagGraphTraceDeltas.ts`, косвенные проверки в `pagGraphSessionStore.test.ts`.
- **Desktop main:** `pagGraphBridge.ts` — минимальные правки.
- **Python:** `pag_slice_caps.py`, `sqlite_pag.py`, `agent_memory_query_pipeline.py`, `memory_agent.py`, `memory_cli.py`; тесты `test_g14r11_w14_integration.py`, `test_pag_slice_caps_alignment.py`.

## Поведение и контракты

- UC 2.1–2.7 (план): стабильный ключ 3D без `n{count}`, дедуп rev-warnings, один канал highlight из trace (D-HI-1), фаза «вспоминает» по broker trace, визуал рёбер, лимиты 20k/40k нод/рёбер (D-SCL-1), extreme LOD.
- W14: порядок emit относительно PAG trace; pathless inject UC 2.4 без некорректного path-fallback при `w14_command_output_invalid`.

## Протоколы (канон)

- `context/arch/desktop-pag-graph-snapshot.md`, `context/arch/w14-graph-highlight-m1.md`
- `context/proto/desktop-memory-3d-observability.md`, `context/proto/ailit-memory-w14-graph-highlight.md`, `context/proto/broker-memory-work-inject.md`, `context/proto/pag-slice-desktop-renderer.md` (при работе с missing/full load)

## Тесты

- Сводка и команды — `context/tests/INDEX.md`, отчёт **11** выше.

## Риски и ограничения

- E2E/integration desktop в финальном 11 не запускались.
- `prompts/startf.txt` и прочий локальный шум вне постановки — не часть канона итерации.
- Отдельный артефакт `test_report_fix_pytest_five.md` в статусе удаления — не блокер контекста.

## Связанные записи

- [`feature_uc2_4_broker_memory_inject_task_2_1_2026-04-30.md`](feature_uc2_4_broker_memory_inject_task_2_1_2026-04-30.md)  
- [`feature_3d_memory_layout_task_1_3.md`](feature_3d_memory_layout_task_1_3.md)  

**Оглавление:** [`index.md`](index.md) · [`../INDEX.md`](../INDEX.md)
