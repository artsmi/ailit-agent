# AgentMemory: prompts по состояниям и multi-language

## Current reality

- Планер: system prompt константа `W14_PLAN_TRAVERSAL_SYSTEM` для первого раунда (`agent_memory_query_pipeline.md` F1).
- Summarize C/B: отдельные LLM вызовы через `AgentMemorySummaryService` с strict `agent_memory_command_output.v1` (`pag_kb_memory_state_models.md` F8).
- Repair: отдельные system/user тексты `_w14_repair_system_message` / `_w14_repair_user_instruction` (`agent_memory_query_pipeline.md` F6).
- Verbose chat log при `memory.debug.verbose=1` может содержать полные LLM messages — **не** compact channel (`memory_journal_trace_observability.md` F7).

## Target behavior

### Каталог промптов по состояниям (OR-009)

Каждая строка — **роль промпта**, не дословный текст (тексты живут в коде/репо; здесь контракт требований).

| Runtime state / phase | Prompt role | Обязательные инструкции к LLM |
|----------------------|-------------|-------------------------------|
| `intake` (policy header) | `agent_memory.system` | Разделение ролей runtime vs LLM; запрет CoT в output; запрет filesystem/tools из JSON; запрет absolute/`..` paths; указание caps. |
| `planner_round` | `agent_memory.planner.plan_traversal` | JSON-only; whitelist `actions`; указание, что project memory **не только Python**; требование явного `file_kind` awareness при выборе путей. |
| `summarize_phase` / C | `agent_memory.summarize.c` | Строгая схема `agent_memory_command_output.v1`; вернуть `file_kind`, `language`, `semantic_chunk_kind`, candidates с evidence. |
| `summarize_phase` / B | `agent_memory.summarize.b` | Аналогично; ссылка на дочерние C summaries если применимо. |
| `propose_links` | `agent_memory.links.propose` | Только `agent_memory_link_candidate.v1[]`; запрет hard-write семантики. |
| `finish_assembly` | `agent_memory.finish.decision` | Выбор из candidates; `decision_summary` compact; `recommended_next_step` bounded. |
| `planner_repair` | `agent_memory.planner.repair_format` | Исправить JSON строго под schema; один round. |

### Multi-language и виды файлов (OR-008)

**Обязательная классификация** перед «AST-like» рассуждениями:

- `file_kind`: `source_code` \| `documentation` \| `configuration` \| `build_file` \| `test` \| `unknown_text` (required в C batch output).
- `language`: расширенный enum включая `python`, `go`, `cpp`, `c`, `typescript`, `markdown`, `yaml`, `json`, `dockerfile`, `makefile`, `unknown`.
- `semantic_chunk_kind`: `function`, `class`, `method`, `struct`, `interface`, `heading_section`, `config_section`, `build_target`, `test_case`, `text_window`, …

**Fallback:** для `unknown` — `semantic_chunk_kind=text_window` или `heading_section` с явной маркировкой heuristic; **forbidden** представлять такой chunk как надёжный `calls`/`imports` без evidence.

### Пример output fragment (контрактный, из постановки)

```json
{
  "file_kind": "source_code|documentation|configuration|build_file|test|unknown_text",
  "language": "python|go|cpp|c|typescript|markdown|yaml|json|dockerfile|makefile|unknown",
  "semantic_chunk_kind": "function|class|method|struct|interface|heading_section|config_section|build_target|test_case|text_window",
  "candidates": [
    {
      "stable_name": "string",
      "start_line": 0,
      "end_line": 0,
      "summary": "string, bounded",
      "link_candidates": []
    }
  ]
}
```

### Запреты (все промпты)

- CoT / «рассуждения вне JSON» в machine channel — **forbidden**.
- Выдача секретов, ключей, токенов — **forbidden**.
- Большие raw file dumps — **forbidden**; только выбранные окна + hashes/line ranges.

### Verbose режим

`memory.debug.verbose=1` — **audit-only**; не является broker-facing compact контрактом. Потребители D-OBS не обязаны парсить legacy log.

## Traceability

| ID | Источник |
|----|----------|
| OR-008, OR-009 | `original_user_request.md` §5–6 |
| F-OBS-2, F7 | `current_state/memory_journal_trace_observability.md` |
| Letta donor | идея layered limits — `donor/letta_memory_blocks_compact_pattern.md` (единицы: см. D4 synthesis — UTF-8 символы / counts) |
