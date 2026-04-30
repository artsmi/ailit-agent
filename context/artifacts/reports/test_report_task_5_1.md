# test_report_task_5_1

- **Статус:** passed
- **Команды:**
  - `.venv/bin/python -m pytest tests/test_memory_pag_slice.py tests/test_pag_slice_caps_alignment.py tests/test_g13_agent_memory_contract_integration.py -q`
  - `cd desktop && npm test -- --run src/renderer/runtime/pagGraphLimits.test.ts src/renderer/runtime/pagGraphSessionStore.test.ts src/renderer/runtime/loadPagGraphMerged.test.ts`
  - `.venv/bin/flake8 tools/agent_core/memory/pag_slice_caps.py tools/agent_core/memory/sqlite_pag.py tools/ailit/memory_cli.py tests/test_pag_slice_caps_alignment.py`
- **Упавшие тесты:** нет

## Baseline производительности (D-SCL-1)

Измерения **не** выполнялись в этом прогоне (нет GPU/интерактивного smoke в CI).

- **Метод (для ручного smoke по architecture §9):** открыть 3D Memory с синтетическим или реальным PAG около **10k / 15k / 20k** нод; зафиксировать: время до `loadState === "ready"` после Refresh; первый кадр после `onEngineStop`; p75 интервала между кадрами при pan/zoom (Performance panel или встроенный FPS overlay).
- **Ориентир после изменения caps:** полная загрузка = серия вызовов `pag-slice` через `loadPagGraphMerged` (страницы по `MEM3D_PAG_MAX_NODES` / `MEM3D_PAG_MAX_EDGES`); при 20k нод минимум одна полная страница нод + до двух страниц рёбер при 40k cap. `PAG_GRAPH_SLICE_IPC_MAX_BUFFER` (96 MiB) оставлен с запасом под крупный JSON.
- **Контролируемая деградация:** пороги `PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD` (2k) и `PAG_3D_EXTREME_GRAPH_NODE_THRESHOLD` (12k) — меньше warmup/cooldown, реже refresh подсветки при N > 12k.

## Примечания / долг

- **После ручного smoke:** зафиксировать численные пороги FPS и p75 pan/zoom для выборок **10k / 15k / 20k** нод (сейчас в отчёте задан только метод измерения; целевые числа — по чеклисту и бюджетам из architecture §9 после первого профилирования на железе).

## Изменения по коду

- Единые константы CLI/store: `tools/agent_core/memory/pag_slice_caps.py` (20k / 40k).
- Renderer: `pagGraphLimits.ts`, `MemoryGraph3DPage.tsx`, комментарии в `pagGraphBridge.ts`, `loadPagGraphMerged.ts`.
