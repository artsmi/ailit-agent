# R4.4 (research): инъекция top-K фактов после `memory.retrieval.match`

**Workflow:** `read-6` — задача R4.4 в `6-read-improve-strategy.md`. Реализация **вне** минимального закрытия R4.1–R4.3.

## Зачем

После `memory.retrieval.match` модель по-прежнему может идти в `glob`/`list_dir`, если в контекст шага не попали краткие факты, уже сматченные retrieval. Ориентир: **Letta** — memory blocks, явная инъекция короткого state (см. локальный репозиторий `letta` в правилах workflow).

## Варианты scope

- Только `project` / только фиксированные kind (`repo_entrypoints`, `repo_tree_root`).
- Лимит токенов на ход: 1–3 факта, обрезка summary.

## Риски

- Раздувание system-контекста.
- Дублирование с auto-веткой `kb_search` в `SessionRunner` (см. `session/loop.py` — не плодить два канала).

## Следующий шаг

Согласовать с постановкой: включать ли инъекцию в `6-read-improve-strategy` follow-up или в отдельный `plan/7-…`.
