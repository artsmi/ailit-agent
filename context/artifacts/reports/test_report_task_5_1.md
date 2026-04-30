# test_report_task_5_1

- **Статус:** passed
- **Команды:**
  - `.venv/bin/python -m pytest tests/test_memory_pag_slice.py tests/test_pag_slice_caps_alignment.py tests/test_g13_agent_memory_contract_integration.py -q`
  - `cd desktop && npm test -- --run src/renderer/runtime/pagGraphLimits.test.ts src/renderer/runtime/pagGraphSessionStore.test.ts src/renderer/runtime/loadPagGraphMerged.test.ts`
  - `.venv/bin/flake8 tools/agent_core/memory/pag_slice_caps.py tools/agent_core/memory/sqlite_pag.py tools/ailit/memory_cli.py tests/test_pag_slice_caps_alignment.py`
- **Упавшие тесты:** нет

## Baseline производительности (D-SCL-1)

### A) Синтетический микробенч (main thread, без IPC/SQLite/GPU)

**Стенд:** Linux x86_64, Node **v22.22.0**, скрипт вне репо: эмуляция `loadPagGraphMerged` (те же `MEM3D_PAG_MAX_NODES`/`MEM3D_PAG_MAX_EDGES`, что в `pagGraphLimits.ts`) с мгновенным in-memory `slice`: пагинация как в проде, поля нод/рёбер минимальные. Граф: **N** нод, **2N** рёбер (цепочка). **25** повторов после **3** прогревов; в таблице — **мс**, диапазон **min … max**, отдельно **median** и **p75** времени одного полного merge (от старта до массива `nodes`/`edges` в памяти).

| N нод | Рёбер | Full load (merge) min | median | p75 | max |
|------:|------:|----------------------:|-------:|----:|----:|
| 10 000 | 20 000 | 2.0 | 2.4 | 2.8 | 3.7 |
| 15 000 | 30 000 | 2.6 | 2.9 | 3.4 | 4.9 |
| 20 000 | 40 000 | 4.4 | 5.0 | 5.8 | 7.5 |

**Интерпретация:** это **нижняя граница** чистого JS-слияния страниц; реальный full load в приложении = SQLite + сериализация JSON + IPC + парсинг + React state **существенно выше** (ожидаемо десятки–сотни мс и выше на том же железе — отдельный ручной smoke).

### B) Первый кадр и p75 pan/zoom (продуктовый UI)

| N нод | Первый кадр после готовности графа | p75 интервала кадра при pan/zoom |
|------:|-------------------------------------|----------------------------------|
| 10 000 | **N/A** (нет интерактивного 3D smoke в этом прогоне) | **N/A** |
| 15 000 | **N/A** | **N/A** |
| 20 000 | **N/A** | **N/A** |

**Метод для закрытия B) на dev-машине (architecture §9):** открыть 3D Memory с PAG ≈ **10k / 15k / 20k** нод; зафиксировать время до `loadState === "ready"` после Refresh; первый кадр после `onEngineStop`; p75 интервала между кадрами при pan/zoom (Performance panel или FPS overlay).

- **Ориентир по объёму данных:** полная загрузка в продукте = серия `pag-slice` через `loadPagGraphMerged` (страницы по `MEM3D_PAG_MAX_NODES` / `MEM3D_PAG_MAX_EDGES`); при 20k нод — одна полная страница нод + до двух страниц рёбер при cap 40k. `PAG_GRAPH_SLICE_IPC_MAX_BUFFER` (96 MiB) с запасом под крупный JSON.
- **Контролируемая деградация:** `PAG_3D_HEAVY_GRAPH_NODE_THRESHOLD` (2k) и `PAG_3D_EXTREME_GRAPH_NODE_THRESHOLD` (12k) — меньше warmup/cooldown, реже refresh подсветки при N > 12k.

## Примечания / долг

- Численный baseline для **ветки A** закрывает критерий «диапазон + метод» для **чистого merge**; для **ветки B** числа появятся после ручного smoke на железе с Electron/WebGL (см. таблицу B).

## Изменения по коду

- Единые константы CLI/store: `tools/agent_core/memory/pag_slice_caps.py` (20k / 40k).
- Renderer: `pagGraphLimits.ts`, `MemoryGraph3DPage.tsx`, комментарии в `pagGraphBridge.ts`, `loadPagGraphMerged.ts`.
