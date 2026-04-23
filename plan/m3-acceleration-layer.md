# M3-5.1: acceleration layer и source of truth (канон ailit)

Связано с [`workflow-memory-3.md`](workflow-memory-3.md) (M3-5.1) и
[`m3-governance.md`](m3-governance.md). Без копипаста доноров; ориентир по разделению
«файл vs индекс»: `ai-memory.md` в
`/home/artem/reps/ai-multi-agents/plans/ai-memory.md` (≈ `180–199`).

## 1. Source of truth (канон)

| Слой | Примеры в ailit | Роль |
|------|------------------|------|
| Файлы в рабочем дереве | то, что читает `read_file` | исходный код, markdown-проекты, локальные заметки |
| Явные записи в KB (SQLite) | `kb_records` через `kb_write_fact` / `kb_promote` | нормализованные **факты** с provenance / temporal, не сырой чат |

Каноничность факта в сессии — запись в KB с `promotion_status` в соответствии с
`promotion_policy`, а не повтор веб-куска в `messages`.

## 2. Acceleration layer (производные)

| Компонент | Смысл | Rebuild |
|-----------|--------|---------|
| Локальный **SQLite KB** (`.ailit` / `AILIT_KB_DB_PATH`) | быстрый search/fetch, LIKE-поиск | **Дамп и пересборка** из внешнего источника, если SoT вынесен; при SoT=сама БД — бэкап + миграции схемы. |
| **Context pager** (`page_id`, превью) | сокращение токенов в истории | Пересобирается из **текущих** tool results в сессии; не «истина». |
| Будущие: BM25/эмбеддинги над KB | ускорение retrieval | Индекс пересобрать с нуля от записей KB; **не** заменять `kb.fetch` на «угадайку» без id. |

Правило: **если acceleration и канон разошлись, побеждает канон** (путь/запись KB),
а индекс помечается к пересборке.

## 3. Ограничения в prompt assembly

- В промпт **не** подмешивать весь derived index: только `top_k` + `kb_fetch(id)` / сниппеты.
- Pager-страница — **не** замена `read_file` для правки файла: перед патчем сверяться с
  актуальным FS или явным `fetch`.
- Post-compact restore (см. `post_compact_restore.py`) — **не** SoT, а
  **continuity** в пределах бюджета.

## 4. Следующие шаги (out of scope этого файла)

- Синхрон «vault markdown» ↔ KB как отдельный ingest job.
- Векторный слой: только как acceleration с явным `rebuild_index` в CLI/доке.
