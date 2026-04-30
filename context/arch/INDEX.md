# Архитектура — индекс

| Документ | Содержание |
|----------|------------|
| [`system-elements.md`](system-elements.md) | Learn: процессы P1–P6 (CLI, supervisor, broker/workers, desktop, TUI, Streamlit), точки входа и ключевые пути; P3 — ссылка на UC 2.4 broker pathless в proto. |
| [`desktop-pag-graph-snapshot.md`](desktop-pag-graph-snapshot.md) | Снимок PAG-графа в renderer, `pagDatabasePresent`, full load, поллер ожидания sqlite, 3D UI; **warnings / graph_rev** — `pagGraphRevWarningFormat.ts` + trace deltas; **1.3** — `graphDataKey` (без `n` по числу нод), merge с сохранением `x..fz`, G16.4; gate Vitest — `artifacts/reports/test_run_11_final.md`. |
| [`w14-graph-highlight-m1.md`](w14-graph-highlight-m1.md) | Python: W14 `graph_highlight`, M1 builder (`W14GraphHighlightPathBuilder`), интеграция в `AgentMemoryQueryPipeline`, D16.1. |
