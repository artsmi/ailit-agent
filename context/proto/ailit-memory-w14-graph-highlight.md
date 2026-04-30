# `memory.w14.graph_highlight` — схема v1, наполнение (M1)

## Участники

- **Продюсер:** Python agent memory runtime — `AgentMemoryQueryPipeline` вызывает `W14GraphHighlightPathBuilder` и затем `emit_w14_graph_highlight` (реализация в `subprocess_agents/memory_agent.py`).
- **Схема / поля:** **`ailit_memory_w14_graph_highlight_v1` — поля в задаче 1.2 не менялись.** `node_ids` / `edge_ids` заполняются детерминированно по правилам M1 (см. `context/arch/w14-graph-highlight-m1.md` и `tools/agent_core/runtime/w14_graph_highlight_path.py`).

## D16.1: пустой highlight

Если после построения пути оба списка пусты, **`emit_w14_graph_highlight` не записывает** payload в journal/trace (ранний return).

## Транспорт

Тот же путь, что и для остальных memory/W14 событий агента (журнал / trace для desktop и отладки); **не** путать с отдельным JSON IPC `pag-slice` в desktop renderer (задача 1.1).

## Точки в коде (канон)

- `tools/agent_core/runtime/w14_graph_highlight_path.py` — M1.
- `tools/agent_core/runtime/agent_memory_query_pipeline.py` — эмиты.
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — `emit_w14_graph_highlight` (guard на пустые id).
