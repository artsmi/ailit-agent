# Python runtime: W14 `graph_highlight` — M1 (построение пути)

## Назначение

Перед эмитом события `memory.w14.graph_highlight` (схема `ailit_memory_w14_graph_highlight_v1` **без изменения полей**) **детерминированно** строятся `node_ids` / `edge_ids` по графу PAG. Единая логика — в **`W14GraphHighlightPathBuilder`**; `AgentMemoryQueryPipeline` вызывает builder (`union_to_ends`) в конце `finish_decision` и `plan_traversal` runtime, кладёт результат в **`W14DeferredGraphHighlight`** на `AgentMemoryQueryPipelineResult`; фактический **`emit_w14_graph_highlight`** выполняет **`AgentMemoryWorker`** после записей PAG этого запроса (включая D-digest), чтобы в trace сначала шли `pag.*`, затем одна строка highlight.

**Главный модуль:** `ailit/agent_memory/pag/w14_graph_highlight_path.py` (подробный приоритет шагов M1 — в docstring модуля, здесь кратко).

## M1 (сводка)

1. **Containment upwalk** от целевой ноды к `A:{namespace}`: на каждом шаге вверх по рёбрам `containment` / `to_node == current` — если **ровно один** родитель, используется этот путь.
2. **Иначе:** неориентированный **BFS** от `A` к цели; кратчайшая длина; **tie-break** соседей при первом открытии — сортировка по `(neighbor_id, edge_id)`, очередь FIFO.
3. **Иначе:** устойчивый **synthetic** путь: `A` + цепочка `B` по `PagNode.path` (для C-нод — после B-цепи).

Ограничения по обходу: без O(N) полного перебора PAG — `list_edges_touching` (волны BFS или upwalk) и точечные `fetch_node` при fallback.

## Интеграция в pipeline

- **`ailit/agent_memory/query/agent_memory_query_pipeline.py`:** два вызова `union_to_ends` → `w14_graph_highlight_deferred`; W14 runtime-запись PAG под **`store.graph_trace`** до выхода из контекста (materialize, indexer, summarize C/B).
- **`subprocess_agents/memory_agent.py`:** после `maybe_upsert_query_digest` — `emit_w14_graph_highlight` по deferred; при пустых id после trim — **return** (D16.1).

## Типы

- `W14GraphHighlightPath` — `node_ids`, `edge_ids`.
- `W14GraphHighlightPathBuilder.path_to_end` / `union_to_ends`.

## PAG

Используется **`SqlitePagStore`** (`list_edges_touching`, `fetch_node`); новых публичных API PAG в рамках M1 не вводилось.

## Влияние правок

При изменении M1 — править **только** `w14_graph_highlight_path.py` и согласованные тесты; pipeline остаётся тонким вызовом builder.

**Связь с desktop:** в задаче 1.2 **не** менялся; потребитель trace/IPC — по существующим путём.

## Минимальные расширения итерации Memory 3D (M1-граница)

- **Схема `ailit_memory_w14_graph_highlight_v1`:** поля **v1 не меняются**; доказательство highlight в trace по-прежнему через событие `memory.w14.graph_highlight` и этот payload (см. задачу **1_2**, D-OBS-HI-1 в proto).
- **M1 builder:** `W14GraphHighlightPathBuilder` и приоритет шагов M1 **не переписываются** под observability; pipeline остаётся тонким вызовом builder, как в разделе «Влияние правок».
- **Дополнительные compact-события** итерации Memory 3D (rev, Refresh, фазы recall UI) — **отдельные** имена вне v1, по [`context/proto/desktop-memory-3d-observability.md`](../proto/desktop-memory-3d-observability.md) после **1_2** (`pag_graph_rev_reconciled`, `pag_snapshot_refreshed`, `memory_recall_ui_phase` или финальное имя из proto); они **не** расширяют и не заменяют поля W14 v1.
- **D-PROD-1 (Python):** в `subprocess_agents/memory_agent.py` и `ailit/agent_memory/pag/pag_graph_trace.py` **не** допускается литерал строки `pag_graph_rev_reconciled` (единственный emit — renderer); регрессия — `test_python_forbids_pag_graph_rev_reconciled_literal` в [`../../tests/runtime/test_pag_graph_trace_w14_highlight.py`](../../tests/runtime/test_pag_graph_trace_w14_highlight.py).
