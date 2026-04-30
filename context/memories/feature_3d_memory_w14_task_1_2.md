# Память итерации: `feature_3d_memory_w14_task_1_2`

**Связь:** feature 1.2, W14 graph highlight (M1) в Python runtime. См. также: [`feature_3d_memory_pag_task_1_1.md`](feature_3d_memory_pag_task_1_1.md) (PAG/desktop 1.1). Канон: [`../INDEX.md`](../INDEX.md). Источник фактов: `context/artifacts/change_inventory.md` (12).

## Задача

M1: детерминированное построение `node_ids` / `edge_ids` для `memory.w14.graph_highlight` при неизменной схеме v1; единый `W14GraphHighlightPathBuilder`; все эмиты из `AgentMemoryQueryPipeline` через builder; D16.1 — пустые списки не эмитятся.

## Процессы и модули

- **`w14_graph_highlight_path.py`:** M1 (upwalk → BFS + tie-break → fallback по `PagNode.path`); `W14GraphHighlightPath`, `W14GraphHighlightPathBuilder`.
- **`agent_memory_query_pipeline.py`:** четыре места `union_to_ends` / `path_to_end` + `emit_w14_graph_highlight`.
- **`memory_agent.py` — `emit_w14_graph_highlight`:** no-op при пустых `node_ids` и `edge_ids`.

## Поведение (зафиксировано)

- Схема `ailit_memory_w14_graph_highlight_v1` без изменения полей.
- Эвристики пути **не** дублируются в pipeline; точка смены логики M1 — один модуль builder.
- Пустой highlight не попадает в trace (guard в emit + D16.1).

## Протоколы

- W14 graph highlight: [`../proto/ailit-memory-w14-graph-highlight.md`](../proto/ailit-memory-w14-graph-highlight.md).

## Тесты

- `tests/runtime/test_w14_graph_highlight_path.py` (M1, union).
- `tests/runtime/test_pag_graph_trace_w14_highlight.py` (trace/shape, путь не «один лист», пустой end).
- Команда и статус: `context/artifacts/reports/test_report_pipeline_task_1_2.md`. Desktop vitest в DoD 1.2 не обязателен (09).

## Риски / дальше

- Полный vitest ветки — по согласованию DoD (см. change_inventory).

## Обновлённые разделы context

- `context/arch/w14-graph-highlight-m1.md`, `context/proto/ailit-memory-w14-graph-highlight.md`, `context/tests/INDEX.md`, индексы `arch`/`proto`, `context/memories/index.md`, этот файл.
