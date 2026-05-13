# Feature: plan 18 G3 — OR-012, 2D highlight из снимка

## Что изменилось в продукте (renderer)

- `MemoryGraphPage.tsx`: live glow для активного workspace namespace читает `snap.searchHighlightsByNamespace[ns0]`, как канал side-channel для 3D, без SoT из полного parse `rawTraceRows`.
- `pagGraphSessionStore.ts`: `pagSearchHighlightShallowEqualForGlow` в `emitHighlightChangeDiagnostics` — не эмитить `highlight_recomputed` при shallow-эквивалентном DTO подсветки (см. UC-02 в коде store).
- Новый helper: `pagSearchHighlightShallowEqual.ts`.

## Затронутый канон

- `context/arch/desktop-pag-graph-snapshot.md` — §D-HI-1 (2D/3D), главные файлы.
- `context/algorithms/desktop/graph-3dmvc.md` — §OR-012 и таблица потребителей.

## Проверки

- Автоматические: см. `context/artifacts/test_report.md` (финальный `11`); ручной UC-04 в отчёте `blocked_by_environment`.

## Связанные записи

- [`feature_plan18_g1_d_orphan_b_2026-05-12.md`](feature_plan18_g1_d_orphan_b_2026-05-12.md)

**Оглавление:** [`index.md`](index.md) · [`../INDEX.md`](../INDEX.md)
