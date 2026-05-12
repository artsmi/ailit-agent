# Feature: plan 18 G1 — D-ORPHAN-B и 3D highlight

## Что изменилось в продукте (renderer)

- `MemoryGraphForceGraphProjector.project`: нормализация концов → UC-04A → `filterDegreeZeroNodesDOrphanB` (**N_scene** для `ForceGraph3D`).
- `PagGraphSessionSnapshot.merged` остаётся суперсетом для merge/2D; **N_scene** для 3D только из выхода проектора.
- `MemoryGraph3DPage`: подсветка из `snap.searchHighlightsByNamespace`, не из полного trace на странице как SoT.

## Затронутый канон

- `context/algorithms/desktop/graph-3dmvc.md` — §OR-003 и highlight policy после G1.
- `context/arch/desktop-pag-graph-snapshot.md` — блок 3D-проекции и D-HI-1.

## Проверки

- Автотесты: см. `context/artifacts/test_report.md` (финальный `11`, слайс G1).
- Ручной smoke плана §6 (Electron): не закрыт в этой фазе; см. `context/artifacts/escalation_pending.md` Resolution.

## Связанные записи

- [`feature_memory_3d_w1w5_pag_w14_caps_2026-04-30.md`](feature_memory_3d_w1w5_pag_w14_caps_2026-04-30.md)
- [`feature_3d_memory_layout_task_1_3.md`](feature_3d_memory_layout_task_1_3.md)

**Оглавление:** [`index.md`](index.md) · [`../INDEX.md`](../INDEX.md)
