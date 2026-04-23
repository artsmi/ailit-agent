# M3-5.2: evaluation suite (память + токены)

Связано с [`workflow-memory-3.md`](workflow-memory-3.md) (M3-5.2),
[`workflow-token-economy-recipe.md`](workflow-token-economy-recipe.md) (TE benchmark),
unified summary (см. `ailit session usage summary`, реализация
[`session_usage_cli.py`](../tools/ailit/session_usage_cli.py)) и
блоком **`m3_eval_signals`** в JSON отчёта (прокси по JSONL, без gold labels в рантайме).

## 1. Метрики качества (целевые; часть — offline)

| Метрика | Смысл | В рантайне по JSONL (прокси) | Полная оценка |
|---------|--------|-----------------------------|----------------|
| **Token savings** | input/tool chars vs baseline | `synthetic_est`, pager/budget/prune (TE) | A/B сценарий из recipe |
| **Fetch cost** | дешёвые обращения к знаниям | `memory.access` count, KB tool calls | Разбор по id vs blind search |
| **Promotion correctness** | допустимые только переходы | `memory.promotion.*`, denied rules | Сверка с политикой/ручной разметкой |
| **Recall / Precision** (KB) | релевантные факты | — | Нужен labeled set/эксперт (offline) |
| **Stale fact rate** | устаревший факт в ответе | `supersedes` / `valid_to` в KB (офлайн) | Time-travel тесты |
| **Continuity** | сессия без лестницы ошибок | `resume_ready`, `compaction.restore` | E2E-M3-02/03 |

## 2. Автоматизуемо без gold labels

- Парсинг `ailit-*.log` → `build_session_summary` → поля **`cumulative`**, **`resume`**, **`m3_eval_signals`**.
- `m3_eval_signals` агрегирует: доля range-read (`fs`), доля успешных `promotion` vs `denied`, `resume_ready`, накопленные `schema_savings` (exposure).

## 3. Ручные сценарии (E2E из M3)

- E2E-M3-01 … M3-04 — см. §5.1 в `workflow-memory-3.md`.
- «Regression»: один и тот же `task` + провайдер mock, сравнить JSON `summary` до/после
  изменения (по полям `m3_eval_*`, `usage`).

## 4. Согласованность с TE-benchmark

- M3-метрики **добавляют** слой памяти/промоушен/continuity, **не заменяют** pager/budget
  baseline из `workflow-token-economy-recipe.md`.
- Отчёт: одна точка `build_session_summary` / `--json` (E2E-M3-02).

## 5. Ссылки на доноров (эвристика, не копипаст)

- `context-mode` — unified report / continuity.
- `hindsight` / offline learning — идея отложенного scoring вне сессии.
