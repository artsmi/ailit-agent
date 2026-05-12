# Desktop realtime graph protocol (redirect)

> **Аннотация:** этот путь в пакете **agent-memory** сохранён для обратной совместимости ссылок. **Нормативный** текст протокола Desktop (Electron): trace, PAG slice, merged, 3D, подсветка, лимиты, remount, observability и приёмка — перенесён в пакет **`context/algorithms/desktop/`**.

## Status

`redirect` — с **2026-05-12**. Не использовать этот файл как SoT для лимитов, remount, конфигурации или матрицы постановки: там оставались устаревшие формулировки (в т.ч. 20k/40k и ключ с `graphRev`).

## Куда смотреть

- **Хаб канона:** [`../desktop/INDEX.md`](../desktop/INDEX.md)
- **3dmvc и инварианты View:** [`../desktop/graph-3dmvc.md`](../desktop/graph-3dmvc.md)
- **Поток клиента, фазы, команды:** [`../desktop/realtime-graph-client.md`](../desktop/realtime-graph-client.md)
- **Глоссарий пакета desktop:** [`../desktop/glossary.md`](../desktop/glossary.md)
- **Память на границе агента (общий контракт):** [`external-protocol.md`](external-protocol.md)
- **План внедрения (не канон SoT):** [`../../../plan/18-desktop-memory-graph-3dmvc.md`](../../../plan/18-desktop-memory-graph-3dmvc.md)

## Запрещено

- Копировать сюда обновлённые числа, шаги алгоритма или acceptance без синхронизации с **`context/algorithms/desktop/`** — дублирование создаёт второй SoT.
- Ссылаться на этот файл в новых постановках как на полнотекстовый канон Desktop-graph.
