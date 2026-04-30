# Python runtime: W14 `graph_highlight` — M1 (построение пути)

## Назначение

Перед эмитом события `memory.w14.graph_highlight` (схема `ailit_memory_w14_graph_highlight_v1` **без изменения полей**) **детерминированно** строятся `node_ids` / `edge_ids` по графу PAG. Единая логика — в **`W14GraphHighlightPathBuilder`**; `AgentMemoryQueryPipeline` вызывает builder (`union_to_ends`) в конце `finish_decision` и `plan_traversal` runtime, кладёт результат в **`W14DeferredGraphHighlight`** на `AgentMemoryQueryPipelineResult`; фактический **`emit_w14_graph_highlight`** выполняет **`AgentMemoryWorker`** после записей PAG этого запроса (включая D-digest), чтобы в trace сначала шли `pag.*`, затем одна строка highlight.

**Главный модуль:** `tools/agent_core/runtime/w14_graph_highlight_path.py` (подробный приоритет шагов M1 — в docstring модуля, здесь кратко).

## M1 (сводка)

1. **Containment upwalk** от целевой ноды к `A:{namespace}`: на каждом шаге вверх по рёбрам `containment` / `to_node == current` — если **ровно один** родитель, используется этот путь.
2. **Иначе:** неориентированный **BFS** от `A` к цели; кратчайшая длина; **tie-break** соседей при первом открытии — сортировка по `(neighbor_id, edge_id)`, очередь FIFO.
3. **Иначе:** устойчивый **synthetic** путь: `A` + цепочка `B` по `PagNode.path` (для C-нод — после B-цепи).

Ограничения по обходу: без O(N) полного перебора PAG — `list_edges_touching` (волны BFS или upwalk) и точечные `fetch_node` при fallback.

## Интеграция в pipeline

- **`agent_memory_query_pipeline.py`:** два вызова `union_to_ends` → `w14_graph_highlight_deferred`; W14 runtime-запись PAG под **`store.graph_trace`** до выхода из контекста (materialize, indexer, summarize C/B).
- **`subprocess_agents/memory_agent.py`:** после `maybe_upsert_query_digest` — `emit_w14_graph_highlight` по deferred; при пустых id после trim — **return** (D16.1).

## Типы

- `W14GraphHighlightPath` — `node_ids`, `edge_ids`.
- `W14GraphHighlightPathBuilder.path_to_end` / `union_to_ends`.

## PAG

Используется **`SqlitePagStore`** (`list_edges_touching`, `fetch_node`); новых публичных API PAG в рамках M1 не вводилось.

## Влияние правок

При изменении M1 — править **только** `w14_graph_highlight_path.py` и согласованные тесты; pipeline остаётся тонким вызовом builder.

**Связь с desktop:** в задаче 1.2 **не** менялся; потребитель trace/IPC — по существующим путём.
