<!-- Canonical AgentMemory target algorithm — published after user approval 2026-05-03 -->
**Источник:** черновик `context/artifacts/target_doc/target_algorithm_draft.md` (Produced by: 21_target_doc_author), верификация `context/artifacts/target_doc/verification.md`.

# prompts

## prompts

### Роли (required prompt roles)

| Роль | Назначение | Где в коде (якорь) |
|------|------------|-------------------|
| system AgentMemory | глобальные инварианты модуля | константы в `memory_agent.py` / policy |
| traversal / plan (`W14_PLAN_TRAVERSAL_SYSTEM`) | первый planner round | `agent_memory_query_pipeline.py` |
| summarize B | обзор файла | `agent_memory_summary_service.py` |
| summarize C | семантика chunk | `agent_memory_summary_service.py` |
| link proposal | **нормативно** отдельный prompt слой; **сейчас** может быть совмещён | gap / future |
| finish decision | терминальный выбор | assembler + pipeline |
| repair format | repair round | `_repair_w14_command_output` instruction |

### Нормативные ограничения на промпты и вывод

- **Forbidden в model output:** chain-of-thought, свободный текст вне JSON для строгого W14 path, вызовы tools, абсолютные пути, сегменты `..`, секреты, большие дампы файлов.
- **Required:** для chunk кандидатов — `file_kind`, `language`, `semantic_chunk_kind`, `evidence` с line/symbol/heading где применимо.
- **Hypothesis separation:** если поле смешивает факт и гипотезу — помечать confidence; runtime demotes low confidence.

---
