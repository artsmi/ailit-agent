# Workflow 14: AgentMemory runtime contract + LLM command protocol

**Идентификатор:** `agent-memory-runtime-14` (файл `plan/14-agent-memory-runtime.md`).

**Статус:** **открыт**. Это не MVP и не точечная правка старого planner prompt. Это план рефакторинга AgentMemory runtime и реализации ключевой фичи: LLM-направляемая память проекта с жёсткими командами, машиной состояний и проверяемым контрактом результата.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc). Исторический источник проблемы: [`plan/14-agent-memory-planner-command-contract.md`](14-agent-memory-planner-command-contract.md) — считать примером недостаточно строгой постановки, а не целевым контрактом.

---

## 1. Цель и границы

### 1.1 Цель

Workflow 14 должен заменить текущий слабый путь:

```text
LLM свободно пишет requested_reads -> runtime угадывает пути -> эвристики goal_terms/entrypoint -> частичный PAG slice
```

на жёсткий runtime:

```text
AgentWork subgoal
  -> one or more AgentMemory queries
  -> runtime_step state machine
  -> AM calls LLM commands with strict JSON
  -> deterministic AM actions over A/B/C/D
  -> final memory result: C summaries and/or exact read_lines from C
  -> AgentWork decides next work step
```

### 1.2 Ноды памяти

| Нода | Нормативное значение |
|------|----------------------|
| **A** | Корень проекта. Один `A` на проектный `namespace`/`project_root`. A не хранит сырой код; A связывает B первого уровня. |
| **B** | Файл или папка. Содержание B считается зафиксированным только через содержание дочерних элементов: для папки через B/C-потомков, для файла через C-потомков. Summary B **всегда** создаётся отдельным LLM-запросом `summarize_b`. |
| **C** | Смысловая часть файла B: функция/класс для кода, heading section/абзац для текста, line window только как fallback boundary. Summary C **всегда** создаётся LLM-запросом `summarize_c`. |
| **D** | Резюме ответа по конкретному пользовательскому запросу. D не подменяет A/B/C и создаётся только после финального AM result для этого запроса. |

### 1.3 Конечный результат AgentMemory

Ответ AM на один запрос от AgentWork обязан содержать:

```json
{
  "schema_version": "agent_memory_result.v1",
  "query_id": "string",
  "status": "complete|partial|blocked",
  "results": [
    {
      "kind": "c_summary|read_lines|b_path",
      "path": "relative/posix/path",
      "c_node_id": "C:...",
      "summary": "string|null",
      "read_lines": [
        { "start_line": 1, "end_line": 20, "text": "..." }
      ],
      "reason": "string"
    }
  ],
  "decision_summary": "string",
  "recommended_next_step": "string",
  "runtime_trace": {
    "steps_executed": 1,
    "final_step": "finish",
    "partial_reasons": []
  }
}
```

Правила:

- `results[].kind="c_summary"` — `summary` обязателен, `read_lines` равен `[]`.
- `results[].kind="read_lines"` — `read_lines` содержит один или больше диапазонов, `summary` равен `null`.
- `results[].kind="b_path"` — разрешён только когда AgentWork нужно создать/изменить файл и AM должен вернуть релевантный B-путь или папку; `c_node_id` равен `null`.
- Финальное решение о достаточности результата для пользовательской задачи принимает LLM AgentWork. AgentMemory завершает только свой query и явно помечает `status`.

### 1.4 Вне scope W14

- Менять провайдера LLM или обучать модель.
- Разрешать LLM исполнять shell/Python или произвольные file tools.
- Возвращать raw prompt, chain-of-thought, секреты, полный текст больших файлов в journal/trace.
- Считать успешным полный обход проекта без C-summary/read_lines результата.

---

## 2. Research / аудит текущего состояния

| ID | Находка | Source of truth |
|----|---------|-----------------|
| **A14R.1** | Текущий `PLANNER_SYSTEM` просит свободные поля `requested_reads`, `c_upserts`, `link_claims`; нет закрытого enum команд и нет state machine. | `tools/agent_core/runtime/agent_memory_query_pipeline.py`, `PLANNER_SYSTEM`. |
| **A14R.2** | `AgentMemoryQueryPipeline.run()` после JSON берёт `requested_reads[].path` как relpath; namespace может попасть в path и дальше runtime начинает угадывать. | `tools/agent_core/runtime/agent_memory_query_pipeline.py`, разбор `req_reads` и вызов `_grow_pag_for_query`. |
| **A14R.3** | `MemoryExplorationPlanner.select_paths()` при промахе explicit path переходит к `goal_terms`, затем к `_ENTRYPOINT_NAMES`; это полезный fallback для старого режима, но в новом runtime он не должен маскировать невалидные команды LLM. | `tools/agent_core/runtime/memory_growth.py`, `PATH_SEL_EXPLICIT`, `PATH_SEL_GOAL_TERMS`, `PATH_SEL_ENTRYPOINT`. |
| **A14R.4** | `PagIndexer` уже умеет строить A/B дерево и механические C для Python, но B summaries сейчас заглушки `"Directory"` / `"File"` и не являются LLM-сводкой. | `tools/agent_core/memory/pag_indexer.py`, `_upsert_dir_b_node`, `_upsert_file_b_node`, `_index_python_files`. |
| **A14R.5** | C segmentation имеет механический каталог чанков и source boundary policy, но не является единым runtime_step с обязательным LLM `summarize_c`. | `tools/agent_core/runtime/memory_c_segmentation.py`, `MechanicalChunkCatalogBuilder`, `FullBIngestionPolicy`. |
| **A14R.6** | D создаётся через `DCreationPolicy` из goal и node_ids; в W14 D должен создаваться после AM result, а не заменять C/B summaries. | `tools/agent_core/runtime/d_creation_policy.py`, `maybe_upsert_query_digest`. |
| **A14R.7** | `AgentMemoryWorker.handle()` уже возвращает `memory_slice`, grants, `partial`, `recommended_next_step`, `decision_summary`; это anchor для нового AM result envelope. | `tools/agent_core/runtime/subprocess_agents/memory_agent.py`, обработка `memory.query_context`. |
| **A14R.8** | `MemoryGrantChecker` уже проверяет path+lines, значит read_lines из C должны материализоваться как grants/read ranges, а не как произвольный полный файл. | `tools/agent_core/tool_runtime/memory_grants.py`. |
| **A14R.9** | `multi_root_paths.py` уже фиксирует root boundary; новый контракт path должен использовать тот же принцип: relpath под work root, без `..`, без абсолютных путей от LLM. | `tools/agent_core/tool_runtime/multi_root_paths.py`. |
| **A14R.10** | В `opencode` typed event registry показывает полезный паттерн: тип события и payload schema регистрируются вместе. W14 должен держать один registry команд AM. | `/home/artem/reps/opencode/packages/opencode/src/bus/bus-event.ts:6-31`. |
| **A14R.11** | В `opencode` session events типизированы через schema classes с literal `type`; это референс для `runtime_step.type`/`command.name`, без копирования кода. | `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:92-140`. |
| **A14R.12** | В `claude-code` agent memory явно разделяет scopes и path ownership; W14 должен так же отделить AgentWork request от AM-owned memory writes. | `/home/artem/reps/claude-code/tools/AgentTool/agentMemory.ts:12-64`. |
| **A14R.13** | В `letta` memory blocks рендерятся с metadata и лимитами; W14 должен возвращать компактный результат с лимитами, а не большой сырой контекст. | `/home/artem/reps/letta/letta/schemas/memory.py:68-80`, `/home/artem/reps/letta/letta/schemas/memory.py:142-173`. |

---

## 3. Целевые контракты

### C14R.1 AgentWork ↔ AgentMemory policy

AgentWork имеет право выполнить несколько запросов к AgentMemory на один пользовательский запрос, если собственная декомпозиция задачи требует разные memory goals.

Норматив:

1. Один пользовательский turn получает `user_turn_id`.
2. AgentWork создаёт один или больше `memory_query` с `query_id`.
3. Каждый `memory_query` обязан иметь `subgoal`, `expected_result_kind` и `stop_condition`.
4. AgentMemory не решает пользовательскую задачу целиком. AM возвращает `agent_memory_result.v1` по конкретному `subgoal`.
5. AgentWork может вызвать следующий AM query только если предыдущее AM result:
   - `status="partial"` и `recommended_next_step` указывает на memory continuation;
   - или AgentWork decomposition требует другой B/C участок;
   - или результат содержит `b_path`, после чего AgentWork должен запросить C/read_lines для проверки перед изменением, если изменение зависит от существующего содержания.
6. Запрещено вызывать AM в цикле без нового `subgoal` или без уменьшения неопределённости. Runtime обязан иметь cap `max_memory_queries_per_user_turn`.

Input AgentWork → AM:

```json
{
  "schema_version": "agent_work_memory_query.v1",
  "user_turn_id": "string",
  "query_id": "string",
  "subgoal": "string",
  "expected_result_kind": "c_summary|read_lines|b_path|mixed",
  "project_root": "absolute path from runtime, not from LLM",
  "namespace": "string",
  "known_paths": ["relative/path.py"],
  "known_node_ids": ["A:...", "B:...", "C:..."],
  "stop_condition": {
    "max_runtime_steps": 12,
    "max_llm_commands": 20,
    "must_finish_explicitly": true
  }
}
```

Output AM → AgentWork: `agent_memory_result.v1` из §1.3.

### C14R.2 Summary policy for B/C/D

#### C summary

`summarize_c` обязателен для каждого C, который попадает в итоговый `c_summary`.

Input:

```json
{
  "schema_version": "agent_memory_command_input.v1",
  "command": "summarize_c",
  "command_id": "cmd-...",
  "query_id": "string",
  "c_node": {
    "c_node_id": "C:...",
    "path": "relative/path.py",
    "semantic_kind": "function|class|method|paragraph|section|line_window",
    "locator": {
      "start_line": 1,
      "end_line": 20,
      "symbol": "name|null"
    },
    "text": "bounded source text"
  },
  "user_subgoal": "string",
  "limits": {
    "max_summary_chars": 700,
    "max_claims": 8
  }
}
```

Output:

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "summarize_c",
  "command_id": "cmd-...",
  "status": "ok|refuse|partial",
  "summary": "string",
  "semantic_tags": ["string"],
  "important_lines": [
    { "start_line": 1, "end_line": 5, "reason": "string" }
  ],
  "claims": [
    {
      "claim": "string",
      "confidence": 0.0,
      "source_lines": { "start_line": 1, "end_line": 5 }
    }
  ],
  "refusal_reason": ""
}
```

Prompt restrictions:

```text
You are AgentMemory summarize_c.
Return ONLY JSON matching agent_memory_command_output.v1.
Do not include markdown, chain-of-thought, hidden reasoning, secrets, or text outside JSON.
Summarize only the supplied C text. Do not infer from files not supplied.
Every claim must be grounded in source_lines within the C locator.
If the text is insufficient, return status="partial" and explain in refusal_reason.
important_lines must be minimal and must not cover the whole C unless the C has <= 20 lines.
```

#### B summary

B summary **всегда** создаётся через LLM `summarize_b`, но входом является не произвольный полный файл, а уже зафиксированные children.

Правила:

- B-folder summary создаётся из child B summaries and/or child C summaries.
- B-file summary создаётся из C summaries этого файла.
- Если C для B ещё не построены, `summarize_b` запрещён; runtime_step обязан сначала перейти в `decompose_b_to_c` или вернуть `partial`.
- B summary invalidated, если изменился fingerprint любого child C или child B.
- B summary не может содержать claims без ссылки на child node id.

Input:

```json
{
  "schema_version": "agent_memory_command_input.v1",
  "command": "summarize_b",
  "command_id": "cmd-...",
  "query_id": "string",
  "b_node": {
    "b_node_id": "B:relative/path",
    "path": "relative/path",
    "kind": "file|directory",
    "children": [
      {
        "node_id": "C:...",
        "level": "C",
        "title": "string",
        "summary": "string",
        "fingerprint": "string"
      }
    ]
  },
  "user_subgoal": "string",
  "limits": {
    "max_summary_chars": 900,
    "max_children": 80
  }
}
```

Output:

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "summarize_b",
  "command_id": "cmd-...",
  "status": "ok|partial|refuse",
  "summary": "string",
  "child_refs": ["C:...", "B:..."],
  "missing_children": ["B:..."],
  "confidence": 0.0,
  "refusal_reason": ""
}
```

Prompt restrictions:

```text
You are AgentMemory summarize_b.
Return ONLY JSON matching agent_memory_command_output.v1.
Use only provided child summaries. Do not invent file content.
For a file B, summarize what the C children say. For a directory B, summarize what child B/C nodes say.
If required children are missing or stale, return status="partial" with missing_children.
Do not output raw source code.
Do not reveal chain-of-thought.
```

#### D summary

D summary создаётся после AM result для конкретного `query_id`.

Rules:

- D input = `subgoal`, final `results`, selected node ids, compact decision summary.
- D must not be used as source for B/C summary.
- D fingerprint = normalized summary + linked A/B/C ids, compatible with existing `DCreationPolicy`.

### C14R.3 Command protocol

`command` — это запрос AgentMemory к LLM. Одна команда имеет один prompt, один input JSON, один output JSON и один deterministic parser.

Envelope input:

```json
{
  "schema_version": "agent_memory_command_input.v1",
  "command": "plan_traversal|summarize_c|summarize_b|finish_decision",
  "command_id": "cmd-uuid-or-counter",
  "query_id": "string",
  "runtime_step": {
    "step_id": "rt-...",
    "state": "start|list_frontier|plan_traversal|materialize_b|decompose_b_to_c|summarize_c|summarize_b|collect_result|finish|blocked",
    "remaining_budget": {
      "runtime_steps": 10,
      "llm_commands": 8,
      "read_lines": 40
    }
  },
  "payload": {}
}
```

Envelope output:

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "string",
  "command_id": "string",
  "status": "ok|partial|refuse",
  "payload": {},
  "decision_summary": "string",
  "violations": []
}
```

Global prompt restrictions for every command:

```text
You are a strict AgentMemory command executor.
Return ONLY valid JSON. No markdown. No prose outside JSON.
Never reveal chain-of-thought or hidden reasoning.
Use only data provided in the input JSON.
Do not invent paths, node ids, line numbers, or file contents.
All paths must be relative POSIX paths under project_root. Absolute paths and ".." are forbidden.
If information is missing, return status="partial" or "refuse" with a machine-readable reason.
The final task completion decision must be explicit via finish_decision.
```

### C14R.4 `plan_traversal` command

Purpose: decide next AM actions using the current frontier. This is the only command that may choose traversal actions. It does not read files and does not write PAG.

Input payload:

```json
{
  "user_subgoal": "string",
  "frontier": {
    "a_node": {
      "node_id": "A:...",
      "path": ".",
      "summary": "string|null"
    },
    "first_level_b": [
      {
        "node_id": "B:src",
        "path": "src",
        "kind": "directory|file",
        "summary": "string|null",
        "has_children": true,
        "staleness_state": "fresh|stale|missing"
      }
    ],
    "first_level_c": [
      {
        "node_id": "C:...",
        "path": "README.md",
        "title": "string",
        "summary": "string|null",
        "line_range": { "start_line": 1, "end_line": 20 }
      }
    ]
  },
  "allowed_actions": [
    "list_children",
    "get_b_summary",
    "get_c_content",
    "decompose_b_to_c",
    "summarize_b",
    "finish"
  ],
  "limits": {
    "max_actions": 6,
    "max_paths": 20
  }
}
```

Output payload:

```json
{
  "actions": [
    {
      "action": "list_children|get_b_summary|get_c_content|decompose_b_to_c|summarize_b|finish",
      "path": "relative/path-or-.",
      "node_id": "A:...|B:...|C:...|null",
      "reason": "string"
    }
  ],
  "is_final": false,
  "final_answer_basis": []
}
```

Hard rules:

- `list_children` allowed for A and B.
- `get_b_summary` allowed for B only and returns summary+path, not raw file.
- `get_c_content` allowed for C only and may produce C summary and/or read_lines in final result.
- `decompose_b_to_c` allowed for B only; it is a runtime request to materialize C nodes.
- `summarize_b` allowed only when runtime knows B children summaries are present and fresh.
- `finish` must be the only action when `is_final=true`.

Prompt:

```text
You are AgentMemory plan_traversal.
Choose the next bounded memory actions for the current user_subgoal.
Return ONLY JSON with payload.actions.
You may ask for list_children on A or B.
You may ask for get_b_summary on B, but this returns only summary + path.
You may ask for get_c_content on C to use C summaries or bounded read_lines.
You may ask for decompose_b_to_c or summarize_b when required.
Do not invent paths that are not present in frontier.
Do not request raw B content. Raw content is only reachable through C read_lines.
If enough C summaries/read_lines are available, return exactly one finish action with is_final=true.
```

### C14R.5 `finish_decision` command

Purpose: LLM explicitly tells AM whether the AM query can finish and which C summaries/read_lines/B paths form the result. This is not AgentWork final answer to the user.

Input payload:

```json
{
  "user_subgoal": "string",
  "candidate_results": [
    {
      "kind": "c_summary|read_lines|b_path",
      "path": "relative/path",
      "node_id": "C:...|B:...",
      "summary": "string|null",
      "read_lines": []
    }
  ],
  "missing_or_stale": [
    {
      "node_id": "B:...",
      "reason": "string"
    }
  ]
}
```

Output payload:

```json
{
  "finish": true,
  "status": "complete|partial|blocked",
  "selected_results": [
    {
      "kind": "c_summary|read_lines|b_path",
      "path": "relative/path",
      "node_id": "C:...|B:...",
      "reason": "string"
    }
  ],
  "decision_summary": "string",
  "recommended_next_step": "string"
}
```

Prompt:

```text
You are AgentMemory finish_decision.
Decide whether this AgentMemory query has enough memory evidence for the user_subgoal.
Return ONLY JSON.
You must select only candidate_results that were provided.
For answer/explanation subgoals prefer C summaries. For exact verification prefer read_lines.
For create-file subgoals, B paths are allowed only as target locations; they are not evidence about existing code.
If evidence is incomplete, set status="partial" and recommended_next_step to the next memory query subgoal.
```

### C14R.6 `runtime_step` schema

`runtime_step` — machine-readable description of AM runtime position. Every AM query is a finite state machine.

```json
{
  "schema_version": "agent_memory_runtime_step.v1",
  "step_id": "rt-0001",
  "query_id": "string",
  "state": "start|list_frontier|plan_traversal|materialize_b|decompose_b_to_c|summarize_c|summarize_b|collect_result|finish_decision|finish|blocked",
  "input_refs": {
    "paths": ["relative/path"],
    "node_ids": ["A:...", "B:...", "C:..."]
  },
  "action": {
    "kind": "llm_command|pag_read|pag_write|file_listing|read_lines|noop",
    "command": "plan_traversal|summarize_c|summarize_b|finish_decision|null"
  },
  "output_refs": {
    "paths": [],
    "node_ids": [],
    "result_ids": []
  },
  "transition": {
    "next_state": "string",
    "reason": "string"
  },
  "limits": {
    "max_runtime_steps": 12,
    "runtime_steps_used": 1,
    "max_llm_commands": 20,
    "llm_commands_used": 1,
    "max_read_line_ranges": 40,
    "read_line_ranges_used": 0
  },
  "observability": {
    "journal_event": "memory.runtime_step",
    "trace_topic": "memory.runtime.step",
    "redaction": "compact_no_raw_prompt"
  }
}
```

Allowed transitions:

| From | Allowed next | Required condition |
|------|--------------|--------------------|
| `start` | `list_frontier` | Query envelope valid. |
| `list_frontier` | `plan_traversal` | First-level A-B and A-C frontier prepared. |
| `plan_traversal` | `materialize_b` | LLM requested `list_children`, `get_b_summary`, or path materialization. |
| `plan_traversal` | `decompose_b_to_c` | LLM requested `decompose_b_to_c`. |
| `plan_traversal` | `summarize_b` | LLM requested `summarize_b` and child summaries fresh. |
| `plan_traversal` | `finish_decision` | LLM requested `finish`. |
| `materialize_b` | `list_frontier` | New B children available. |
| `decompose_b_to_c` | `summarize_c` | C boundaries created and text is allowed by source boundary policy. |
| `summarize_c` | `collect_result` | At least one C summary or read_lines candidate created. |
| `summarize_b` | `collect_result` | B summary created/updated. |
| `collect_result` | `plan_traversal` | More traversal needed and budget remains. |
| `collect_result` | `finish_decision` | Candidate results satisfy expected_result_kind or budget is exhausted. |
| `finish_decision` | `finish` | LLM returns `finish=true`. |
| any non-final | `blocked` | Validation failed, cap exceeded, forbidden path/content, or no progress. |

Do not implement as:

- implicit booleans like `partial` driving hidden loops;
- free-form `recommended_next_step` as executable instruction;
- direct `requested_reads` path execution without `runtime_step`.

### C14R.7 Config source of truth

Primary config: merged ailit config loaded through `load_merged_ailit_config_for_memory()` plus AgentMemory YAML from `load_or_create_agent_memory_config()`.

Required keys:

| Key | Default | Rule |
|-----|---------|------|
| `memory.runtime.max_memory_queries_per_user_turn` | `6` | AgentWork cap; exceeding returns `blocked` with `too_many_memory_queries`. |
| `memory.runtime.max_runtime_steps_per_query` | `12` | AM cap; every transition increments counter. |
| `memory.runtime.max_llm_commands_per_query` | `20` | Includes `plan_traversal`, `summarize_c`, `summarize_b`, `finish_decision`. |
| `memory.runtime.max_frontier_items` | `200` | Listing sent to `plan_traversal` is truncated deterministically with `truncated=true`. |
| `memory.runtime.max_c_text_chars` | `12000` | Per `summarize_c` input. Larger C is split into smaller C boundaries or returns partial. |
| `memory.runtime.max_read_line_ranges` | `40` | Per AM query. |
| `memory.runtime.strict_command_json` | `true` | Parser rejects non-JSON or unknown fields with journal event. |

Test isolation must use existing `tests/conftest.py` environment isolation (`AILIT_*`, tmp HOME, tmp PAG/KB/journal). Subprocess tests must pass the same env explicitly.

### C14R.8 Observability contract

Required journal/trace events:

| Event/topic | When | Compact payload |
|-------------|------|-----------------|
| `memory.query.accepted` | AM accepted AgentWork query | `query_id`, `user_turn_id`, `expected_result_kind`, budgets |
| `memory.runtime.step` | Every `runtime_step` transition | `step_id`, `state`, `next_state`, action kind, counts |
| `memory.command.requested` | Before LLM command | `command`, `command_id`, `query_id`, compact input stats |
| `memory.command.parsed` | Valid LLM JSON | `command`, `status`, result counts |
| `memory.command.rejected` | Invalid JSON/schema/unknown action | `command`, `error_code`, `command_id` |
| `memory.node.decomposed` | B -> C boundaries materialized | `b_node_id`, `c_count`, `strategy` |
| `memory.summary.created` | C or B summary written | `level`, `node_id`, `summary_fingerprint` |
| `memory.result.returned` | AM returns result to AgentWork | `query_id`, `status`, result kinds/counts |

Forbidden payload fields: raw full prompt, chain-of-thought, secrets, full file contents, full repo listing above cap. `read_lines` may appear in the AM response payload only when selected as result; journal stores hashes/counts, not raw text.

---

## 4. Общий алгоритм AgentMemory

1. **Accept query.** Validate `agent_work_memory_query.v1`; assign `query_id`; load budgets.
2. **Build first frontier.** AM sends to LLM only A-B and A-C first-level listing:
   - A root metadata;
   - B children directly under A;
   - C children directly under first-level B when already materialized and fresh;
   - summaries only, no raw B content.
3. **Call `plan_traversal`.** LLM returns bounded actions from the whitelist.
4. **Execute runtime action deterministically.**
   - `list_children` for A/B reads PAG/index/listing and updates frontier.
   - `get_b_summary` returns B summary+path only.
   - `get_c_content` adds C summary or bounded read_lines candidates.
   - `decompose_b_to_c` runs C boundary creation for a B file.
   - `summarize_c` creates/updates C summary via LLM.
   - `summarize_b` creates/updates B summary via LLM from child summaries.
5. **Repeat within budget.** Runtime loops through `runtime_step` transitions until candidate result is enough, blocked, or budget exhausted.
6. **Call `finish_decision`.** LLM explicitly chooses final selected_results and status.
7. **Create D summary.** If policy allows, create D from final AM result and linked node ids.
8. **Return AM result to AgentWork.** AgentWork may ask another AM query for another subgoal; this is the only allowed multi-query path.

Important invariant:

```text
AM never returns raw B content.
AM final result is C summaries and/or read_lines from C, plus B paths only for creation/location tasks.
```

---

## 5. Таблица трассировки ID -> этап

| ID | Этап-исполнитель |
|----|------------------|
| A14R.1, A14R.2, A14R.3 | G14R.2, G14R.3 |
| A14R.4, C14R.2 | G14R.4, G14R.5 |
| A14R.5 | G14R.4 |
| A14R.6 | G14R.7 |
| A14R.7, C14R.1, C14R.6 | G14R.1, G14R.2, G14R.8 |
| A14R.8, A14R.9 | G14R.6 |
| A14R.10, A14R.11 | G14R.2 |
| A14R.12 | G14R.1 |
| A14R.13 | G14R.8 |
| C14R.3, C14R.4, C14R.5 | G14R.3 |
| C14R.7 | G14R.2, G14R.9 |
| C14R.8 | G14R.8, G14R.9 |

---

## 6. Этапы реализации

### G14R.1 — AgentWork memory query policy

**Обязательные описания/выводы:** C14R.1, A14R.7, A14R.12.

Implementation anchors:

- `tools/agent_core/runtime/subprocess_agents/work_agent.py` — найти место, где AgentWork запрашивает `memory.query_context`; ввести `user_turn_id`, `query_id`, `subgoal`.
- `tools/agent_core/runtime/models.py` — DTO/envelope для `agent_work_memory_query.v1`, если текущие generic payload недостаточны.
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — принимать новый query envelope без потери backward compatibility только на один workflow-релиз.

Acceptance tests:

- `test_agentwork_can_issue_multiple_memory_queries_for_one_turn`
- `test_agentwork_memory_query_loop_stops_at_config_cap`
- `test_memory_query_requires_subgoal_and_stop_condition`

Static checks:

- `rg "max_memory_queries_per_user_turn" tools/agent_core tests` -> key exists in config parsing and tests.

Do not implement this as:

- hidden `while partial` loop without new `subgoal`;
- reuse `recommended_next_step` as executable command string.

### G14R.2 — Runtime step DTO + command registry

**Обязательные описания/выводы:** C14R.3, C14R.6, C14R.7, A14R.1, A14R.10, A14R.11.

Implementation anchors:

- New module allowed: `tools/agent_core/runtime/agent_memory_runtime_contract.py`.
- `tools/agent_core/runtime/agent_memory_query_pipeline.py` must import and use the registry; no parallel parser hidden inside pipeline.
- `tools/agent_core/runtime/agent_memory_chat_log.py` or existing log helpers must log compact command events.

Acceptance tests:

- `test_runtime_step_rejects_unknown_state`
- `test_command_registry_rejects_unknown_command`
- `test_runtime_step_transition_table_blocks_invalid_transition`
- `test_command_output_rejects_prose_around_json`

Static checks:

- `rg "requested_reads" tools/agent_core/runtime/agent_memory_query_pipeline.py` -> only legacy adapter section with comment `W14R legacy adapter remove after G14R.3`.

Do not implement this as:

- scattered string literals for command names;
- parser that silently drops unknown fields.

### G14R.3 — LLM command prompts and strict JSON parsers

**Обязательные описания/выводы:** C14R.3, C14R.4, C14R.5.

Implementation anchors:

- `tools/agent_core/runtime/agent_memory_query_pipeline.py` — replace old `PLANNER_SYSTEM` path with command-specific prompts.
- New module allowed: `tools/agent_core/runtime/agent_memory_commands.py` containing prompt builders and typed parse results.
- `tools/agent_core/runtime/agent_memory_config.py` — reuse `parse_memory_json_with_retry` only if it rejects non-JSON wrappers under `strict_command_json=true`.

Acceptance tests:

- `test_plan_traversal_prompt_forbids_invented_paths`
- `test_plan_traversal_allows_only_whitelisted_actions`
- `test_finish_decision_must_select_existing_candidate_results`
- `test_summarize_c_claims_require_source_lines`
- `test_summarize_b_requires_child_summaries`

Do not implement this as:

- one mega prompt that can return any shape;
- free-form markdown followed by best-effort JSON extraction in strict mode.

### G14R.4 — B -> C decomposition runtime

**Обязательные описания/выводы:** A14R.4, A14R.5, C14R.2.

Implementation anchors:

- `tools/agent_core/runtime/memory_c_segmentation.py` — single service for C boundaries.
- `tools/agent_core/memory/pag_indexer.py` — stop treating Python-only AST C as the only C source; new service must cover code/text with explicit `semantic_kind`.
- `tools/agent_core/runtime/pag_graph_write_service.py` — all C writes through graph write service.

Acceptance tests:

- `test_decompose_b_to_c_python_function_boundaries`
- `test_decompose_b_to_c_markdown_sections`
- `test_decompose_b_to_c_text_line_windows_when_no_structure`
- `test_decompose_b_to_c_respects_source_boundary_policy`

Do not implement this as:

- returning raw whole B file to LLM;
- C ids that change when unrelated file lines change and no content changed.

### G14R.5 — C and B LLM summaries

**Обязательные описания/выводы:** C14R.2, A14R.4.

Implementation anchors:

- New module allowed: `tools/agent_core/runtime/agent_memory_summary_service.py`.
- `tools/agent_core/runtime/semantic_c_extraction.py` and `memory_c_extractor_prompt.py` must be reviewed: either reused as C summary command or explicitly deprecated in favor of the new command service.
- `tools/agent_core/memory/sqlite_pag.py` / `PagGraphWriteService` existing node fields must store `summary`, `fingerprint`, `attrs.summary_fingerprint`.

Acceptance tests:

- `test_summarize_c_writes_summary_and_summary_fingerprint`
- `test_summarize_b_file_uses_only_child_c_summaries`
- `test_summarize_b_directory_uses_child_b_or_c_summaries`
- `test_b_summary_invalidates_when_child_summary_fingerprint_changes`

Do not implement this as:

- B summary `"File"` / `"Directory"` after W14R is marked complete;
- B summary generated from raw full file instead of child C summaries.

### G14R.6 — Result assembly: C summaries and read_lines

**Обязательные описания/выводы:** A14R.8, A14R.9, §1.3.

Implementation anchors:

- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — response payload must include `agent_memory_result.v1` or map it into existing `memory_slice` without losing fields.
- `tools/agent_core/tool_runtime/memory_grants.py` — read_lines ranges must be covered by grants.
- `tools/agent_core/tool_runtime/multi_root_paths.py` — path validation must be shared or equivalent with a single helper.

Acceptance tests:

- `test_memory_result_contains_c_summary_without_raw_b_content`
- `test_memory_result_read_lines_are_granted_ranges`
- `test_memory_result_rejects_absolute_and_parent_paths`
- `test_create_file_subgoal_may_return_b_path_without_c_content`

Do not implement this as:

- full-file grant for every selected C;
- AM response that only says "read selected context" without selected C/read_lines.

### G14R.7 — D summary after AM result

**Обязательные описания/выводы:** A14R.6.

Implementation anchors:

- `tools/agent_core/runtime/d_creation_policy.py` — reuse fingerprint/dedupe.
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — call D creation only after `finish_decision`.

Acceptance tests:

- `test_d_summary_created_after_finish_decision`
- `test_d_summary_links_to_selected_abc_nodes`
- `test_d_summary_not_used_as_b_or_c_source`

### G14R.8 — Observability and desktop-safe compact payloads

**Обязательные описания/выводы:** C14R.8, A14R.13.

Implementation anchors:

- `tools/agent_core/runtime/memory_journal.py`
- `tools/agent_core/runtime/agent_memory_chat_log.py`
- `context/proto/runtime-event-contract.md` — add compact W14R event section after implementation.

Acceptance tests:

- `test_memory_runtime_step_journal_has_compact_payload`
- `test_memory_command_rejected_logs_error_code_without_prompt`
- `test_memory_result_returned_logs_counts_not_raw_text`

Manual smoke:

1. Run `ailit desktop --dev` or runtime test environment.
2. Ask "о чем этот репозиторий".
3. Verify journal has `memory.runtime.step`, `memory.command.parsed`, `memory.result.returned`.
4. Verify no journal row contains full prompt or full file text.

### G14R.9 — Integration, README/context, and old planner removal

**Обязательные описания/выводы:** C14R.7, C14R.8, all audit findings.

Implementation anchors:

- `README.md` — update current Workflow 14 row after implementation closes, not when this plan is only drafted.
- `context/INDEX.md` and `context/proto/runtime-event-contract.md` — add short canonical contract.
- `plan/14-agent-memory-planner-command-contract.md` — mark superseded by this plan or archive in README status.

Acceptance tests:

- `test_query_context_runtime_happy_path_repo_question`
- `test_query_context_runtime_happy_path_file_question`
- `test_query_context_runtime_partial_when_budget_exhausted`
- `test_legacy_requested_reads_disabled_after_w14r`

Definition of Done:

- All tests named in G14R.1-G14R.9 exist and pass.
- `flake8` passes on changed Python files.
- `pytest` passes at least for AgentMemory/runtime affected tests.
- Manual smoke recorded in task/commit note.
- README/context updated in the closing commit.
- Self-review from `.cursor/rules/project-workflow.mdc` passes.

---

## 7. Примеры простым языком

Этот раздел заменяет старый пункт 6 из `plan/14-agent-memory-planner-command-contract.md` в новой терминологии.

### 7.1 Пользователь: "О чем этот репозиторий?"

Человеческий смысл:

1. AgentWork понимает, что ему нужен общий контекст проекта.
2. AgentWork отправляет в AM query: `subgoal="понять назначение репозитория"`, `expected_result_kind="mixed"`.
3. AM показывает LLM только первый уровень A-B/A-C: например `README.md`, `tools/`, `tests/`, `plan/`.
4. LLM не угадывает полный путь. Оно выбирает:
   - `get_c_content` для C под `README.md`, если C уже есть;
   - или `decompose_b_to_c` для `README.md`, если C ещё нет;
   - затем `summarize_c`;
   - затем `finish`.
5. AM возвращает AgentWork C summaries из README и, если нужно, B summary по ключевым папкам.

Пример `plan_traversal` output:

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "plan_traversal",
  "command_id": "cmd-1",
  "status": "ok",
  "payload": {
    "actions": [
      {
        "action": "decompose_b_to_c",
        "path": "README.md",
        "node_id": "B:README.md",
        "reason": "README обычно содержит назначение проекта, нужно получить C-summary вместо raw файла."
      }
    ],
    "is_final": false,
    "final_answer_basis": []
  },
  "decision_summary": "Начать с README.md.",
  "violations": []
}
```

Что запрещено:

- вернуть `requested_reads: [{"path": "<namespace>"}]`;
- silently fallback на README после невалидного path;
- вернуть весь README как raw B content.

### 7.2 Пользователь: "Изучи репозиторий, посмотри каждый файл и построй дерево памяти"

Человеческий смысл:

1. Это не один LLM prompt и не один гигантский raw context.
2. AM строит A/B дерево через листинг и PAG writes.
3. Для каждого файла B в пределах бюджета AM создаёт C boundaries.
4. Для каждого C AM вызывает `summarize_c`.
5. Для каждого B AM вызывает `summarize_b`, когда child C summaries готовы.
6. Если бюджет закончился, AM возвращает `status="partial"` и точную причину: сколько B/C обработано и какой следующий subgoal должен запросить AgentWork.

Runtime steps:

```text
start
 -> list_frontier
 -> plan_traversal
 -> materialize_b
 -> decompose_b_to_c
 -> summarize_c
 -> summarize_b
 -> collect_result
 -> finish_decision
 -> finish
```

Пример partial result:

```json
{
  "schema_version": "agent_memory_result.v1",
  "query_id": "mem-2",
  "status": "partial",
  "results": [
    {
      "kind": "c_summary",
      "path": "README.md",
      "c_node_id": "C:README.md#section:intro",
      "summary": "README описывает ailit-agent как CLI/runtime ядро с AgentMemory и desktop.",
      "read_lines": [],
      "reason": "Первичный обзор проекта."
    }
  ],
  "decision_summary": "Обработана первая партия файлов; полный обход требует продолжения.",
  "recommended_next_step": "Продолжить AgentMemory query: обработать tools/agent_core/runtime.",
  "runtime_trace": {
    "steps_executed": 12,
    "final_step": "finish",
    "partial_reasons": ["runtime_step_budget_exhausted"]
  }
}
```

Что запрещено:

- считать задачу закрытой после одного A/B inventory без C summaries;
- отправить в LLM весь репозиторий;
- спрятать budget exhaustion за `partial=false`.

### 7.3 Пользователь: "О чем файл a/b/toggle.c?"

Сценарий A: AgentWork уже знает точный relpath `a/b/toggle.c`.

1. AgentWork отправляет AM query с `known_paths=["a/b/toggle.c"]`.
2. AM materializes B path under A.
3. AM decomposes B file into C: функции, structs, или line windows.
4. AM вызывает `summarize_c` по релевантным C.
5. AM возвращает C summaries или exact read_lines.

Сценарий B: пользователь сказал только `toggle.c`.

1. AM показывает LLM первый уровень A-B.
2. Если путь не найден на первом уровне, LLM просит `list_children` по B-папкам, но только через bounded traversal.
3. Если найден ровно один `a/b/toggle.c`, AM продолжает как в сценарии A.
4. Если найдено несколько `toggle.c`, AM возвращает `status="partial"` и просит AgentWork уточнить путь или сделать следующий AM query с disambiguation subgoal.

Пример finish:

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command": "finish_decision",
  "command_id": "cmd-9",
  "status": "ok",
  "payload": {
    "finish": true,
    "status": "complete",
    "selected_results": [
      {
        "kind": "c_summary",
        "path": "a/b/toggle.c",
        "node_id": "C:a/b/toggle.c:function:toggle_enable",
        "reason": "Эта функция описывает основную логику файла."
      }
    ],
    "decision_summary": "Достаточно C-summary для ответа о назначении файла.",
    "recommended_next_step": ""
  },
  "decision_summary": "AM query can finish.",
  "violations": []
}
```

Что запрещено:

- LLM придумывает `a/b/toggle.c`, если такого пути не было в frontier/listing.
- AM возвращает `README.md`, если `toggle.c` не найден.
- AM возвращает полный файл вместо C summaries/read_lines.

### 7.4 Пользователь: "Создай новый файл рядом с реализацией памяти"

Человеческий смысл:

1. AM не пишет файл.
2. AM может вернуть `b_path`, если задача AgentWork — выбрать место для нового файла.
3. Если выбор зависит от существующего поведения, AM также должен вернуть C summaries/read_lines по соседним файлам.

Valid result:

```json
{
  "schema_version": "agent_memory_result.v1",
  "query_id": "mem-4",
  "status": "complete",
  "results": [
    {
      "kind": "b_path",
      "path": "tools/agent_core/runtime",
      "c_node_id": null,
      "summary": null,
      "read_lines": [],
      "reason": "Runtime AgentMemory modules live here; new command contract module belongs in this folder."
    },
    {
      "kind": "c_summary",
      "path": "tools/agent_core/runtime/agent_memory_query_pipeline.py",
      "c_node_id": "C:...",
      "summary": "Current query pipeline owns planner calls and PAG growth.",
      "read_lines": [],
      "reason": "Anchor for integration."
    }
  ],
  "decision_summary": "AgentWork has target folder and integration anchor.",
  "recommended_next_step": "",
  "runtime_trace": {
    "steps_executed": 6,
    "final_step": "finish",
    "partial_reasons": []
  }
}
```

---

## 8. Dependencies

```text
G14R.1 AgentWork policy
  -> G14R.2 runtime_step + registry
  -> G14R.3 prompts/parsers
  -> G14R.4 B->C decomposition
  -> G14R.5 summaries
  -> G14R.6 result assembly
  -> G14R.7 D after result
  -> G14R.8 observability
  -> G14R.9 integration/README/context
```

G14R.4 may start after G14R.2 DTO names are frozen. G14R.5 cannot close before G14R.4 produces stable C boundaries. G14R.6 cannot close before G14R.3 `finish_decision` exists.

---

## 9. Self-review checklist for this plan

- Every audit finding A14R.* has an executor in §5.
- Every contract C14R.* is bound to one or more stages.
- No stage says only "add tests"; every test has a required name.
- Commands include input JSON, output JSON, and prompt restrictions.
- `runtime_step` includes state, transition, budgets, and observability.
- B summary policy is strict: LLM-only and child-summary based.
- AgentWork multi-query policy is strict and capped.
- Exact config source and env isolation rules are stated.
- Anti-patterns forbid namespace-as-path, raw B content, silent fallback, hidden loops.
- DoD requires end-to-end path from AgentWork query to AM result, D, observability, context/README.

---

## 10. Changelog плана

| Дата | Изменение |
|------|-----------|
| 2026-04-29 | Первичная публикация `plan/14-agent-memory-runtime.md`: AgentWork/AM policy, command protocol, runtime_step, B/C/D summary policy, общий алгоритм, этапы G14R.1-G14R.9, простые сценарии из старого пункта 6 в новой терминологии. |

---

*Конец документа Workflow 14 Runtime.*
