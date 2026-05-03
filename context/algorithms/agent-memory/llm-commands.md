<!-- Canonical AgentMemory target algorithm — published after user approval 2026-05-03 -->
**Источник:** черновик `context/artifacts/target_doc/target_algorithm_draft.md` (Produced by: 21_target_doc_author), верификация `context/artifacts/target_doc/verification.md`.

# llm-command-protocol

## llm-command-protocol

### Ownership

| Зона | Владеет runtime | Владеет LLM |
|------|-----------------|------------|
| SQLite PAG/KB access | да | нет |
| Filesystem read bytes | да | нет |
| Валидация путей / node ids | да | нет |
| Retry / caps / events | да | нет |
| Итоговый envelope | да | нет |
| Выбор следующего шага обхода | через JSON команд | да |
| Тексты summary в рамках schema | через JSON | да |
| Link **candidates** | через JSON | да |
| Finish decision полей `status` в рамках schema | через JSON | да |

### Реестр команд (фактический код)

`AgentMemoryCommandName`: `plan_traversal` | `summarize_c` | `summarize_b` | `finish_decision`.

**Gap vs user list:** отдельных enum-значений `propose_links` и `repair_invalid_response` **нет**; ниже `propose_links` описан как **нормативная цель**, `repair_invalid_response` — как имя **режима** поверх `_repair_w14_command_output` (см. текущий снимок в [`synthesis.md`](../../artifacts/target_doc/synthesis.md) D3).

Общие правила **строгого** `agent_memory_command_output.v1` (все команды, где применяется `parse_w14_command_output_text_strict`):

- **Required top-level:** `schema_version`, `command`, `command_id`, `status`, `payload`, `decision_summary`, `violations` (как в рабочих тестах; `violations` — **empty list** по умолчанию).
- **Forbidden top-level:** любые дополнительные ключи → `W14CommandParseError` (`unknown_fields`) — см. `tests/test_g14r2_agent_memory_runtime_contract.py` (`test_command_output_rejects_unknown_top_level_field`).
- **Forbidden в логах (default journal):** raw prompts, CoT, полные дампы файлов (см. [Observability](failure-retry-observability.md#observability)).

---

### Команда: `plan_traversal`

**Purpose:** первичный план обхода и `payload.actions[]` (runtime whitelist действий).

**Happy — минимальный input (логический user JSON в последнем message; фрагмент):**

```json
{
  "goal": "find server entrypoints",
  "namespace": "ns1",
  "explicit_paths": ["src/server.ts"],
  "known_node_ids": []
}
```

**Happy — минимальный output (`agent_memory_command_output.v1`):**

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "plan_traversal",
  "command_id": "cmd-1",
  "status": "ok",
  "payload": {"actions": [{"action": "list_children", "path": "src"}]},
  "decision_summary": "expand src",
  "violations": []
}
```

**Invalid + bounded recovery:**

```json
Here is JSON:
{"schema_version":"agent_memory_command_output.v1", ... }
```

→ `W14CommandParseError` (prose вокруг JSON). Если `_should_repair_w14_error` разрешает — **ровно один** вызов repair; иначе terminal **`partial`** с контрактной причиной (без второго такого же repair).

**Invalid без успешного repair:** top-level `extra_field` → `unknown_fields` → после исчерпания repair — terminal **`partial`** / assembler path с `w14_contract_failure` (не silent `complete`).

**Field rules:** `payload.actions` — **required** array (может быть `[]`); каждый element — object с `action` из whitelist `list_children|get_b_summary|get_c_content|decompose_b_to_c|summarize_b|finish`; неизвестные ключи внутри action-object — **forbidden** для strict parser там, где это проверяется (см. pipeline). `violations` — **default** `[]`, не `null`.

---

### Команда: `summarize_c`

**Purpose:** LLM возвращает строгий envelope для обновления summary C-ноды (`AgentMemorySummaryService.apply_summarize_c`).

**Happy — минимальный input (`build_summarize_c_input_envelope`, фрагмент):**

```json
{
  "schema_version": "agent_memory_command_input.v1",
  "command": "summarize_c",
  "command_id": "cmd-c-1",
  "query_id": "mq-ut1-0",
  "c_node": {
    "c_node_id": "C:src/a.py:1-40",
    "path": "src/a.py",
    "semantic_kind": "function",
    "locator": {"start_line": 1, "end_line": 40},
    "text": "def foo():\n  return 1\n"
  },
  "user_subgoal": "summarize chunk",
  "limits": {"max_summary_chars": 800, "max_claims": 4}
}
```

**Happy — минимальный output:**

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "summarize_c",
  "command_id": "cmd-c-1",
  "status": "ok",
  "payload": {
    "summary": "compact C summary",
    "semantic_tags": [],
    "important_lines": [],
    "claims": [],
    "refusal_reason": ""
  },
  "decision_summary": "c done",
  "violations": []
}
```

**Invalid + recovery:** нарушение strict envelope (лишний top-level ключ) → тот же bounded repair, что для W14, **если** repair разрешён политикой фазы; иначе **`partial`** / отказ записи C без crash.

**Field rules:** `payload.summary` — **required** string для успешной записи при `status: ok`; `semantic_tags`, `important_lines`, `claims` — **default** `[]`; `refusal_reason` — **default** `""`. Полный файл в `summary` — **forbidden** (G14R.7). Normative: для новых chunk-кандидатов в расширениях — `file_kind` / `language` / `semantic_chunk_kind` / `evidence` (см. [prompts.md](prompts.md)); текущий минимальный wire в тестах может не содержать их — **gap** для `start-feature`, если расширяете кандидатов.

---

### Команда: `summarize_b`

**Purpose:** LLM возвращает строгий envelope для B-summary (`apply_summarize_b`).

**Happy — минимальный input (`build_summarize_b_input_envelope`, фрагмент):**

```json
{
  "schema_version": "agent_memory_command_input.v1",
  "command": "summarize_b",
  "command_id": "cmd-b-1",
  "query_id": "mq-ut1-0",
  "b_node": {
    "b_node_id": "B:src/a.py",
    "path": "src/a.py",
    "kind": "file",
    "children": []
  },
  "user_subgoal": "summarize file",
  "limits": {"max_summary_chars": 1200, "max_children": 80}
}
```

**Happy — минимальный output:**

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "summarize_b",
  "command_id": "cmd-b-1",
  "status": "ok",
  "payload": {
    "summary": "compact B summary",
    "child_refs": [],
    "missing_children": [],
    "confidence": 1.0,
    "refusal_reason": ""
  },
  "decision_summary": "b done",
  "violations": []
}
```

**Invalid + terminal path:** `status: ok` и пустой `payload.summary` → `W14CommandParseError` → нет корректного upsert; шаг учитывается как **`partial`** на уровне результата (без падения процесса). `status: refuse` допускается с пустым summary — см. код `apply_summarize_b`.

**Field rules:** `payload.child_refs` / `missing_children` — **default** `[]`; `confidence` — required number в примере; для `refuse` см. attrs `w14_*` в реализации.

---

### Команда: `finish_decision`

**Purpose:** терминальный выбор `selected_results` и статуса AMR.

**Happy — минимальный input (логический контекст в messages; не отдельный публичный JSON для внешних клиентов):**

```json
{"phase": "finish", "query_id": "mq-ut1-0", "candidate_result_kinds": ["c_summary", "b_path"]}
```

**Happy — минимальный output:**

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "finish_decision",
  "command_id": "cmd-f-1",
  "status": "ok",
  "payload": {
    "finish": true,
    "status": "complete",
    "selected_results": [{"kind": "c_summary", "node_id": "C:src/a.py:1-40"}],
    "decision_summary": "done",
    "recommended_next_step": ""
  },
  "decision_summary": "finish ok",
  "violations": []
}
```

**Invalid + recovery:** невалидный JSON / unknown fields → repair policy как выше; assembler может **понизить** итоговый AMR до `partial` даже при «ok» от LLM, если нет usable results (**FR2**). **`blocked`** на уровне AMR — только LLM infra после bounded retry (матрица [Failure And Retry Rules](failure-retry-observability.md#failure-and-retry-rules)).

**Field rules:** `payload.finish` — **required** bool; `payload.status` внутри payload — строка политики finish; `selected_results` — **default** `[]` допускается только если внешний статус AMR станет **`partial`** с явной причиной, не `complete` с пустыми results.

---

### Нормативная команда: `propose_links` (**target**; enum gap в текущем коде)

**Purpose:** отдельный LLM round только для `agent_memory_link_candidate.v1[]` после стабилизации frontier.

**Happy — минимальный input:**

```json
{
  "schema_version": "agent_memory_command_input.v1",
  "command": "propose_links",
  "command_id": "cmd-pl-1",
  "query_id": "mq-ut1-0",
  "payload": {
    "frontier_node_ids": ["B:src/a.py", "C:src/b.go:Run"],
    "max_candidates": 8
  }
}
```

**Happy — минимальный output:**

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "propose_links",
  "command_id": "cmd-pl-1",
  "status": "ok",
  "payload": {
    "link_candidates": [
      {
        "schema_version": "agent_memory_link_candidate.v1",
        "link_id": "candidate-pl-1",
        "link_type": "references",
        "source_node_id": "C:docs/x.md:Intro",
        "target_node_id": "B:src/a.py",
        "source_path": "docs/x.md",
        "target_path": "src/a.py",
        "evidence": {
          "kind": "heading_text",
          "value": "See server",
          "start_line": null,
          "end_line": null
        },
        "confidence": "medium",
        "created_by": "llm_inferred",
        "reason": "doc pointer"
      }
    ]
  },
  "decision_summary": "links proposed",
  "violations": []
}
```

**Invalid + terminal:** кандидат без обязательного `evidence` для типа связи → runtime **reject** кандидата, событие advisory (см. [external-protocol.md](external-protocol.md)); основной query может завершиться `complete`/`partial` без promote.

**Текущий снимок:** отдельной команды **нет**; кандидаты могут встраиваться в другие JSON — при `start-feature` для wire-разделения реализовать эту команду и enum.

---

### Режим: `repair_invalid_response` (**имя режима**; код: `_repair_w14_command_output`)

**Purpose:** второй LLM-вызов с инструкцией «исправь до строгого `agent_memory_command_output.v1`».

**Happy — минимальный input (смысл последнего user message, не дословный код):**

```json
{
  "repair_of_command_id": "cmd-1",
  "broken_model_text": "{ bad json",
  "instruction": "emit single JSON object only"
}
```

**Happy — минимальный output:** тот же объект, что в **happy** для `plan_traversal` / соответствующей команды.

**Invalid:** repair снова даёт non-parseable или `unknown_fields` → **запрещён** третий round → terminal **`partial`** с причиной контракта / `memory_slice.w14_contract_failure` (см. pipeline tests).

**Field rules:** не более **1** repair на одну исходную ошибку первичного parse; счётчики LLM — учитываются в caps политики провайдера отдельно от «основного» completion.

---
