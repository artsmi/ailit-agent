# Рабочий процесс 14: runtime-контракт AgentMemory и протокол команд LLM

**Идентификатор:** `agent-memory-runtime-14` (файл `plan/14-agent-memory-runtime.md`).

**Статус:** **закрыт (G14R.0–G14R.11, 2026-04-29).** Реализация: W14 `AgentMemoryQueryPipeline` (`plan_traversal` / `finish_decision`), `payload.agent_memory_result`, без G13 `c_upserts`/`requested_reads` в ответе планнера; legacy C extraction — `agent_core.legacy`; интеграция — `tests/test_g14r11_w14_integration.py`.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc). Исторический источник проблемы: [`plan/14-agent-memory-planner-command-contract.md`](14-agent-memory-planner-command-contract.md) — считать примером недостаточно строгой постановки, а не целевым контрактом.

---

## 1. Цель и границы

### 1.1 Цель

Рабочий процесс 14 должен заменить текущий слабый путь:

```text
LLM свободно пишет requested_reads -> runtime угадывает пути -> эвристики goal_terms/entrypoint -> частичный PAG slice
```

на жёсткий runtime:

```text
AgentWork subgoal
  -> один или несколько AgentMemory query
  -> машина состояний runtime_step
  -> AM вызывает команды LLM со строгим JSON
  -> детерминированные действия AM над A/B/C/D
  -> итоговый memory result: C summaries и/или точные read_lines из C
  -> AgentWork решает следующий рабочий шаг
```

### 1.2 Ноды памяти

| Нода | Нормативное значение |
|------|----------------------|
| **A** | Корень проекта. Один `A` на проектный `namespace`/`project_root`. A не хранит сырой код; A связывает B первого уровня. |
| **B** | Файл или папка. Содержание B считается зафиксированным только через содержание дочерних элементов: для папки через B/C-потомков, для файла через C-потомков. Summary B **всегда** создаётся отдельным LLM-запросом `summarize_b`. |
| **C** | Смысловая часть файла B: функция/класс для кода, секция по заголовку/абзац для текста, окно строк только как fallback-граница. Summary C **всегда** создаётся LLM-запросом `summarize_c`. |
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

### 1.4 Вне границ W14

- Менять провайдера LLM или обучать модель.
- Разрешать LLM исполнять shell/Python или произвольные файловые инструменты.
- Возвращать сырой prompt, chain-of-thought, секреты, полный текст больших файлов в журнал/trace.
- Считать успешным полный обход проекта без C-summary/read_lines результата.

### 1.5 Итерация 3: clean replacement, без совместимости со старыми данными

W14 выполняется как **clean replacement**. Старые PAG/KB/runtime memory базы будут удалены вручную перед практическим использованием нового workflow, поэтому план **не требует migration layer** и **не сохраняет runtime-совместимость со старыми memory data**.

Нормативные решения:

| ID | Решение |
|----|---------|
| **D14R.1** | Старые базы AgentMemory/PAG/KB считаются disposable для W14. Implementation и tests строят новые временные базы с нуля. |
| **D14R.2** | Старые `requested_reads`, старые C/D attrs, старые B summary `"File"`/`"Directory"` не поддерживаются как рабочий путь. Если старый payload приходит в W14 runtime после этапа отключения legacy adapter, он отклоняется как `legacy_contract_rejected`. |
| **D14R.3** | `agent_memory_result.v1` возвращается отдельным payload-полем рядом с существующим `memory_slice`: `payload.agent_memory_result`. `memory_slice` остаётся compatibility surface для UI/старого AgentWork только до закрытия workflow, но не является источником истины для нового AM result. |
| **D14R.4** | Выбран вариант B: `semantic_c_extraction.py` и `memory_c_extractor_prompt.py` не являются source of truth для W14 runtime. Новый source of truth: `agent_memory_runtime_contract.py`, `agent_memory_commands.py`, `agent_memory_summary_service.py`. Старые модули разрешены только как reference при чтении кода, не как runtime dependency. |

Запрещённые реализации:

- писать migration для старых sqlite/KB/PAG данных как часть W14;
- сохранять `requested_reads` как нормальный production path;
- прятать `agent_memory_result.v1` внутрь `memory_slice` так, что AgentWork не может прочитать его отдельным полем;
- импортировать legacy C extraction modules из нового W14 runtime после этапа quarantine/removal.

---

## 2. Research / аудит текущего состояния

| ID | Находка | Источник истины |
|----|---------|-----------------|
| **A14R.1** | Текущий `PLANNER_SYSTEM` просит свободные поля `requested_reads`, `c_upserts`, `link_claims`; нет закрытого enum команд и нет state machine. | `tools/agent_core/runtime/agent_memory_query_pipeline.py`, `PLANNER_SYSTEM`. |
| **A14R.2** | `AgentMemoryQueryPipeline.run()` после JSON берёт `requested_reads[].path` как relpath; namespace может попасть в path и дальше runtime начинает угадывать. | `tools/agent_core/runtime/agent_memory_query_pipeline.py`, разбор `req_reads` и вызов `_grow_pag_for_query`. |
| **A14R.3** | `MemoryExplorationPlanner.select_paths()` при промахе explicit path переходит к `goal_terms`, затем к `_ENTRYPOINT_NAMES`; это полезный fallback для старого режима, но в новом runtime он не должен маскировать невалидные команды LLM. | `tools/agent_core/runtime/memory_growth.py`, `PATH_SEL_EXPLICIT`, `PATH_SEL_GOAL_TERMS`, `PATH_SEL_ENTRYPOINT`. |
| **A14R.4** | `PagIndexer` уже умеет строить A/B дерево и механические C для Python, но B summaries сейчас заглушки `"Directory"` / `"File"` и не являются LLM-сводкой. | `tools/agent_core/memory/pag_indexer.py`, `_upsert_dir_b_node`, `_upsert_file_b_node`, `_index_python_files`. |
| **A14R.5** | C segmentation имеет механический каталог чанков и политику границы источника, но не является единым runtime_step с обязательным LLM `summarize_c`. | `tools/agent_core/runtime/memory_c_segmentation.py`, `MechanicalChunkCatalogBuilder`, `FullBIngestionPolicy`. |
| **A14R.6** | D создаётся через `DCreationPolicy` из goal и node_ids; в W14 D должен создаваться после AM result, а не заменять C/B summaries. | `tools/agent_core/runtime/d_creation_policy.py`, `maybe_upsert_query_digest`. |
| **A14R.7** | `AgentMemoryWorker.handle()` уже возвращает `memory_slice`, grants, `partial`, `recommended_next_step`, `decision_summary`; это anchor для нового AM result envelope. | `tools/agent_core/runtime/subprocess_agents/memory_agent.py`, обработка `memory.query_context`. |
| **A14R.8** | `MemoryGrantChecker` уже проверяет path+lines, значит read_lines из C должны материализоваться как grants/read ranges, а не как произвольный полный файл. | `tools/agent_core/tool_runtime/memory_grants.py`. |
| **A14R.9** | `multi_root_paths.py` уже фиксирует root boundary; новый контракт path должен использовать тот же принцип: relpath под work root, без `..`, без абсолютных путей от LLM. | `tools/agent_core/tool_runtime/multi_root_paths.py`. |
| **A14R.10** | В `opencode` typed event registry показывает полезный паттерн: тип события и payload schema регистрируются вместе. W14 должен держать один registry команд AM. | `/home/artem/reps/opencode/packages/opencode/src/bus/bus-event.ts:6-31`. |
| **A14R.11** | В `opencode` session events типизированы через schema classes с literal `type`; это референс для `runtime_step.type`/`command.name`, без копирования кода. | `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:92-140`. |
| **A14R.12** | В `claude-code` agent memory явно разделяет scopes и path ownership; W14 должен так же отделить AgentWork request от AM-owned memory writes. | `/home/artem/reps/claude-code/tools/AgentTool/agentMemory.ts:12-64`. |
| **A14R.13** | В `letta` memory blocks рендерятся с metadata и лимитами; W14 должен возвращать компактный результат с лимитами, а не большой сырой контекст. | `/home/artem/reps/letta/letta/schemas/memory.py:68-80`, `/home/artem/reps/letta/letta/schemas/memory.py:142-173`. |
| **A14R.14** | В W13 уже согласован подробный audit/verbose путь AgentMemory через `memory_journal` и `agent_memory_chat_log`; W14 обязан не просто добавить новые события, а обновить AgentMemory logs/chat_logs по тому же компактному формату и с теми же запретами на сырой prompt/текст. | `tools/agent_core/runtime/memory_journal.py`, `tools/agent_core/runtime/agent_memory_chat_log.py`, `tools/agent_core/runtime/subprocess_agents/memory_agent.py`, `context/proto/runtime-event-contract.md`. |
| **A14R.15** | В текущем runtime есть legacy C extraction модули, которые нельзя считать source of truth для W14 после выбора clean replacement. Их нужно удалить или закарантинить отдельным этапом после появления нового summary service. | `tools/agent_core/runtime/semantic_c_extraction.py`, `tools/agent_core/runtime/memory_c_extractor_prompt.py`, `tools/agent_core/runtime/agent_memory_query_pipeline.py`. |

---

## 3. Целевые контракты

### C14R.1 Политика AgentWork ↔ AgentMemory

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

Вход AgentWork → AM:

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

Выход AM → AgentWork: `agent_memory_result.v1` из §1.3.

### C14R.1a Payload strategy `agent_memory_result.v1` + `memory_slice`

Новый runtime обязан возвращать `agent_memory_result.v1` отдельным полем:

```json
{
  "payload": {
    "agent_memory_result": {
      "schema_version": "agent_memory_result.v1",
      "query_id": "mem-...",
      "status": "complete|partial|blocked",
      "results": [],
      "decision_summary": "string",
      "recommended_next_step": "string",
      "runtime_trace": {}
    },
    "memory_slice": {
      "kind": "memory_slice",
      "schema": "memory.slice.v1"
    },
    "grants": [],
    "project_refs": []
  }
}
```

Правила:

- `payload.agent_memory_result` — обязательный source of truth для W14 AgentWork.
- `payload.memory_slice` допускается как compatibility projection для существующих UI/AgentWork consumers, но не может содержать поля, которых нет или которые противоречат `agent_memory_result`.
- Если старый caller читает только `memory_slice`, он получает best-effort compact projection; новый W14 caller обязан читать `agent_memory_result`.
- Тест `test_query_context_returns_agent_memory_result_next_to_memory_slice` должен ломаться, если result спрятан только внутри `memory_slice`.

### C14R.2 Политика summary для B/C/D

#### C summary

`summarize_c` обязателен для каждого C, который попадает в итоговый `c_summary`.

Вход:

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
    "text": "ограниченный исходный текст"
  },
  "user_subgoal": "string",
  "limits": {
    "max_summary_chars": 700,
    "max_claims": 8
  }
}
```

Выход:

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

Ограничения prompt:

```text
Ты выполняешь команду AgentMemory summarize_c.
Верни только JSON, соответствующий agent_memory_command_output.v1.
Не добавляй markdown, chain-of-thought, скрытые рассуждения, секреты или текст вне JSON.
Суммируй только переданный текст C. Не делай выводы из файлов, которых нет во входе.
Каждое утверждение из claims должно опираться на source_lines внутри locator текущего C.
Если текста недостаточно, верни status="partial" и объясни причину в refusal_reason.
important_lines должны быть минимальными и не должны покрывать весь C, кроме случая когда C содержит <= 20 строк.
```

#### B summary

B summary **всегда** создаётся через LLM `summarize_b`, но входом является не произвольный полный файл, а уже зафиксированные дочерние элементы.

Правила:

- Summary B-папки создаётся из summary дочерних B и/или summary дочерних C.
- Summary B-файла создаётся из summary C этого файла.
- Если C для B ещё не построены, `summarize_b` запрещён; runtime_step обязан сначала перейти в `decompose_b_to_c` или вернуть `partial`.
- B summary помечается устаревшим, если изменился fingerprint любого дочернего C или B.
- B summary не может содержать claims без ссылки на id дочерней ноды.

Вход:

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

Выход:

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

Ограничения prompt:

```text
Ты выполняешь команду AgentMemory summarize_b.
Верни только JSON, соответствующий agent_memory_command_output.v1.
Используй только переданные summary дочерних элементов. Не выдумывай содержимое файла.
Для B-файла суммируй только то, что сообщают дочерние C. Для B-папки суммируй только то, что сообщают дочерние B/C.
Если обязательные дочерние элементы отсутствуют или устарели, верни status="partial" и заполни missing_children.
Не выводи сырой исходный код.
Не раскрывай chain-of-thought.
```

#### D summary

D summary создаётся после AM result для конкретного `query_id`.

Правила:

- Вход D = `subgoal`, финальные `results`, выбранные id нод, компактный `decision_summary`.
- D запрещено использовать как источник для B/C summary.
- D fingerprint = нормализованный summary + связанные A/B/C id, совместимо с существующим `DCreationPolicy`.

### C14R.3 Протокол команд

`command` — это запрос AgentMemory к LLM. Одна команда имеет один prompt, один входной JSON, один выходной JSON и один детерминированный parser.

Входной envelope:

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

Выходной envelope:

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

Глобальные ограничения prompt для каждой команды:

```text
Ты строгий исполнитель команды AgentMemory.
Верни только валидный JSON. Не добавляй markdown. Не добавляй поясняющий текст вне JSON.
Никогда не раскрывай chain-of-thought или скрытые рассуждения.
Используй только данные из входного JSON.
Не выдумывай пути, id нод, номера строк или содержимое файлов.
Все пути должны быть относительными POSIX-путями внутри project_root. Абсолютные пути и ".." запрещены.
Если информации недостаточно, верни status="partial" или status="refuse" с машинно-читаемой причиной.
Финальное решение о завершении задачи должно быть явно выражено через finish_decision.
```

### C14R.4 Матрица команд LLM

Эта таблица обязательна для реализации. Агент-исполнитель не должен выводить новую команду из текста prompt или из примеров: команда считается существующей только если она есть в этой таблице, в registry и в parser DTO.

| Команда LLM | Что делает | Когда вызывается | Формат входа | Формат выхода | Prompt ID | Parser / DTO anchor | Обязательные тесты |
|-------------|------------|------------------|--------------|---------------|-----------|---------------------|--------------------|
| `plan_traversal` | Выбирает следующие ограниченные действия AM по текущему frontier. Не читает файлы и не пишет PAG. | После `list_frontier`, после обновления frontier, после `collect_result`, пока нет решения `finish_decision`. | `agent_memory_command_input.v1` + payload из §C14R.5. | `agent_memory_command_output.v1` + `payload.actions[]`, `payload.is_final`, `payload.final_answer_basis`. | `AM_PROMPT_PLAN_TRAVERSAL_RU_V1` | `AgentMemoryCommandName.PLAN_TRAVERSAL`, `PlanTraversalInput`, `PlanTraversalOutput` в `agent_memory_runtime_contract.py`. | `test_plan_traversal_prompt_contains_required_output_schema`, `test_plan_traversal_allows_only_whitelisted_actions`. |
| `summarize_c` | Создаёт summary C и grounded claims по одному C-фрагменту. | После `decompose_b_to_c`, когда C-текст разрешён политикой границы источника и нужен для результата или B summary. | `agent_memory_command_input.v1` + `c_node`, `user_subgoal`, `limits`. | `agent_memory_command_output.v1` + `summary`, `semantic_tags`, `important_lines`, `claims`, `refusal_reason`. | `AM_PROMPT_SUMMARIZE_C_RU_V1` | `AgentMemoryCommandName.SUMMARIZE_C`, `SummarizeCInput`, `SummarizeCOutput`. | `test_summarize_c_prompt_contains_required_output_schema`, `test_summarize_c_claims_require_source_lines`. |
| `summarize_b` | Создаёт summary B только из summary дочерних B/C, без сырого B content. | После того как runtime подтвердил свежие child summaries для B-файла или B-папки. | `agent_memory_command_input.v1` + `b_node.children[]`, `user_subgoal`, `limits`. | `agent_memory_command_output.v1` + `summary`, `child_refs`, `missing_children`, `confidence`, `refusal_reason`. | `AM_PROMPT_SUMMARIZE_B_RU_V1` | `AgentMemoryCommandName.SUMMARIZE_B`, `SummarizeBInput`, `SummarizeBOutput`. | `test_summarize_b_prompt_contains_required_output_schema`, `test_summarize_b_requires_child_summaries`. |
| `finish_decision` | Явно завершает AM query и выбирает итоговые `c_summary`, `read_lines`, `b_path`. | После `collect_result` или при исчерпании бюджета, когда runtime должен вернуть `complete`, `partial` или `blocked`. | `agent_memory_command_input.v1` + `candidate_results[]`, `missing_or_stale[]`. | `agent_memory_command_output.v1` + `finish`, `status`, `selected_results[]`, `decision_summary`, `recommended_next_step`. | `AM_PROMPT_FINISH_DECISION_RU_V1` | `AgentMemoryCommandName.FINISH_DECISION`, `FinishDecisionInput`, `FinishDecisionOutput`. | `test_finish_decision_prompt_contains_required_output_schema`, `test_finish_decision_must_select_existing_candidate_results`. |

Расширение команд допускается только отдельным этапом плана: добавить строку в таблицу, DTO, parser, prompt, tests, observability event и пример сценария. Команда, отсутствующая в матрице, должна отклоняться как `unknown_command`.

### C14R.5 Команда `plan_traversal`

Назначение: выбрать следующие действия AM по текущему frontier. Это единственная команда, которая выбирает traversal-действия. Она не читает файлы и не пишет PAG.

Входной payload:

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

Выходной payload:

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

Жёсткие правила:

- `list_children` разрешён только для A и B.
- `get_b_summary` разрешён только для B и возвращает summary+path, а не сырой файл.
- `get_c_content` разрешён только для C и может дать C summary и/или read_lines в итоговый результат.
- `decompose_b_to_c` разрешён только для B; это runtime-запрос на материализацию C-нод.
- `summarize_b` разрешён только когда runtime знает, что дочерние summaries B существуют и свежие.
- `finish` должен быть единственным действием, если `is_final=true`.

Полный prompt `AM_PROMPT_PLAN_TRAVERSAL_RU_V1`:

```text
Ты выполняешь команду AgentMemory plan_traversal.
Твоя задача: выбрать следующий ограниченный набор действий AgentMemory для user_subgoal.
Верни только JSON по схеме agent_memory_command_output.v1.
Не добавляй markdown, комментарии, chain-of-thought или текст вне JSON.

Обязательные поля верхнего уровня:
- schema_version: ровно "agent_memory_command_output.v1";
- command: ровно "plan_traversal";
- command_id: тот же command_id, что во входе;
- status: "ok", "partial" или "refuse";
- payload: объект по схеме ниже;
- decision_summary: строка до 500 символов;
- violations: массив строк, пустой массив если нарушений нет.

Схема payload:
- actions: массив объектов, минимум 1, максимум limits.max_actions;
- actions[].action: только "list_children", "get_b_summary", "get_c_content", "decompose_b_to_c", "summarize_b", "finish";
- actions[].path: относительный POSIX-путь из frontier или ".";
- actions[].node_id: id ноды из frontier или null только для "finish";
- actions[].reason: короткая причина до 240 символов;
- is_final: boolean;
- final_answer_basis: массив id C/B, которые уже есть во входе; пустой массив если is_final=false.

Правила:
- Запрашивай list_children только для A или B.
- Запрашивай get_b_summary только для B.
- Запрашивай get_c_content только для C.
- Запрашивай decompose_b_to_c только для B-файла или B-папки, которую runtime разрешил материализовать.
- Запрашивай summarize_b только если во входе указано, что дочерние summaries есть и свежие.
- Не выдумывай пути, которых нет во frontier.
- Не запрашивай сырой B content. Сырой текст доступен только как ограниченные read_lines из C.
- Если достаточно C summaries/read_lines, верни ровно одно действие finish, is_final=true.
- Если сведений недостаточно, верни status="partial" и действие, которое уменьшает неопределённость.
```

### C14R.6 Команда `finish_decision`

Назначение: LLM явно сообщает AM, должен ли runtime завершить AM query и какие C summaries/read_lines/B paths входят в результат. Это не финальный ответ AgentWork пользователю.

Входной payload:

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

Выходной payload:

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

Полный prompt `AM_PROMPT_FINISH_DECISION_RU_V1`:

```text
Ты выполняешь команду AgentMemory finish_decision.
Твоя задача: решить, достаточно ли memory evidence для user_subgoal внутри текущего AM query.
Верни только JSON по схеме agent_memory_command_output.v1.
Не добавляй markdown, комментарии, chain-of-thought или текст вне JSON.

Обязательные поля верхнего уровня:
- schema_version: ровно "agent_memory_command_output.v1";
- command: ровно "finish_decision";
- command_id: тот же command_id, что во входе;
- status: "ok", "partial" или "refuse";
- payload: объект по схеме ниже;
- decision_summary: строка до 500 символов;
- violations: массив строк, пустой массив если нарушений нет.

Схема payload:
- finish: boolean, для завершения должен быть true;
- status: "complete", "partial" или "blocked";
- selected_results: массив объектов из candidate_results; нельзя добавлять новые node_id/path;
- selected_results[].kind: "c_summary", "read_lines" или "b_path";
- selected_results[].path: путь из candidate_results;
- selected_results[].node_id: node_id из candidate_results;
- selected_results[].reason: короткая причина выбора;
- decision_summary: строка до 700 символов;
- recommended_next_step: строка, пустая если status="complete".

Правила:
- Выбирай только candidate_results, которые были переданы во входе.
- Для вопросов "объясни/о чем" предпочитай c_summary.
- Для точной проверки поведения предпочитай read_lines.
- Для задач создания файла b_path разрешён только как место назначения; он не является evidence о существующем коде.
- Если evidence неполный, верни payload.status="partial" и recommended_next_step как следующий memory subgoal для AgentWork.
- Если дальнейшее движение запрещено политикой или бюджетом, верни payload.status="blocked" и объясни причину в decision_summary.
```

### C14R.7 Полные prompt для `summarize_c` и `summarize_b`

Полный prompt `AM_PROMPT_SUMMARIZE_C_RU_V1`:

```text
Ты выполняешь команду AgentMemory summarize_c.
Твоя задача: создать компактный summary одного C-фрагмента и grounded claims по переданному тексту.
Верни только JSON по схеме agent_memory_command_output.v1.
Не добавляй markdown, комментарии, chain-of-thought или текст вне JSON.

Обязательные поля верхнего уровня:
- schema_version: ровно "agent_memory_command_output.v1";
- command: ровно "summarize_c";
- command_id: тот же command_id, что во входе;
- status: "ok", "partial" или "refuse";
- summary: строка до limits.max_summary_chars;
- semantic_tags: массив строк, максимум 12 элементов;
- important_lines: массив объектов;
- claims: массив объектов, максимум limits.max_claims;
- refusal_reason: строка, пустая если status="ok".

Схема important_lines:
- start_line: integer, >= c_node.locator.start_line;
- end_line: integer, <= c_node.locator.end_line;
- reason: строка до 240 символов.

Схема claims:
- claim: строка, только то, что следует из c_node.text;
- confidence: number от 0.0 до 1.0;
- source_lines.start_line и source_lines.end_line: диапазон внутри c_node.locator.

Правила:
- Используй только c_node.text и user_subgoal.
- Не делай выводы из других файлов, даже если знаешь типичный проект.
- Не цитируй большие куски исходного кода.
- Каждый claim обязан иметь source_lines.
- Если c_node.text пустой, обрезан или недостаточен, верни status="partial" и заполни refusal_reason.
- Если вход нарушает policy или содержит секреты, верни status="refuse" и кратко укажи refusal_reason.
```

Полный prompt `AM_PROMPT_SUMMARIZE_B_RU_V1`:

```text
Ты выполняешь команду AgentMemory summarize_b.
Твоя задача: создать summary B-файла или B-папки только из summary дочерних B/C.
Верни только JSON по схеме agent_memory_command_output.v1.
Не добавляй markdown, комментарии, chain-of-thought или текст вне JSON.

Обязательные поля верхнего уровня:
- schema_version: ровно "agent_memory_command_output.v1";
- command: ровно "summarize_b";
- command_id: тот же command_id, что во входе;
- status: "ok", "partial" или "refuse";
- summary: строка до limits.max_summary_chars;
- child_refs: массив node_id, которые реально использованы;
- missing_children: массив node_id или path, которые нужны, но отсутствуют/устарели;
- confidence: number от 0.0 до 1.0;
- refusal_reason: строка, пустая если status="ok".

Правила:
- Используй только b_node.children[].summary.
- Не выдумывай содержимое B-файла или B-папки.
- Для B-файла summary должен описывать только смысл его C children.
- Для B-папки summary должен описывать только смысл child B/C.
- Если children пустые, отсутствуют summary или есть stale children, верни status="partial" и заполни missing_children.
- Не выводи сырой исходный код.
- Не раскрывай chain-of-thought.
```

### C14R.8 Схема `runtime_step`

`runtime_step` — машинно-читаемое описание положения AM runtime. Каждый AM query является конечной машиной состояний.

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

Разрешённые переходы:

| Из состояния | Разрешённый следующий шаг | Обязательное условие |
|------|--------------|--------------------|
| `start` | `list_frontier` | Query envelope валиден. |
| `list_frontier` | `plan_traversal` | Подготовлен frontier первого уровня A-B и A-C. |
| `plan_traversal` | `materialize_b` | LLM запросила `list_children`, `get_b_summary` или materialization пути. |
| `plan_traversal` | `decompose_b_to_c` | LLM запросила `decompose_b_to_c`. |
| `plan_traversal` | `summarize_b` | LLM запросила `summarize_b`, и дочерние summaries свежие. |
| `plan_traversal` | `finish_decision` | LLM запросила `finish`. |
| `materialize_b` | `list_frontier` | Доступны новые дочерние B. |
| `decompose_b_to_c` | `summarize_c` | Созданы C boundaries, и текст разрешён политикой границы источника. |
| `summarize_c` | `collect_result` | Создан хотя бы один кандидат C summary или read_lines. |
| `summarize_b` | `collect_result` | Создан или обновлён B summary. |
| `collect_result` | `plan_traversal` | Требуется дальнейший обход, и бюджет не исчерпан. |
| `collect_result` | `finish_decision` | Кандидаты результата соответствуют expected_result_kind или бюджет исчерпан. |
| `finish_decision` | `finish` | LLM вернула `finish=true`. |
| любое нефинальное | `blocked` | Ошибка валидации, превышен cap, запрещённый путь/контент или нет прогресса. |

Запрещённые реализации:

- скрытые циклы, которыми управляют неявные boolean вроде `partial`;
- выполнение свободного текста `recommended_next_step` как инструкции;
- прямое исполнение path из `requested_reads` без `runtime_step`.

### C14R.9 Модель исполнения внутри одного AM query

Внутри одного AM query **разрешены и обязательны** последовательные runtime-запросы, если следующий шаг зависит от результата предыдущего. Это не считается несколькими AM queries. Несколько AM queries появляются только на уровне AgentWork, когда пользовательская задача декомпозирована на разные memory subgoals.

Норматив:

1. `plan_traversal` может вернуть несколько `actions`, но runtime исполняет их через `runtime_step` по одному.
2. Действия считаются зависимыми и обязаны идти строго последовательно, если:
   - второе действие использует B/C, созданные первым;
   - второе действие пишет summary того же B/C;
   - второе действие увеличивает `read_line_ranges_used`;
   - одно из действий ведёт к `finish_decision`.
3. Независимые действия разрешено выполнить в одной пачке только если runtime явно пометил их `parallelizable=true` в своей внутренней модели, и они:
   - читают разные B/C;
   - не пишут одни и те же ноды;
   - не меняют общий frontier до завершения пачки;
   - имеют общий cap на количество действий.
4. После любой пачки независимых действий runtime обязан создать один `collect_result` step и заново вызвать `plan_traversal` или `finish_decision`.
5. LLM не решает, что исполнять параллельно. LLM только возвращает `actions[]`; решение о последовательном или пакетном исполнении принимает runtime по детерминированным правилам.

Пример зависимой цепочки внутри одного AM query:

```text
list_frontier
 -> plan_traversal(decompose_b_to_c README.md)
 -> decompose_b_to_c
 -> summarize_c
 -> collect_result
 -> finish_decision
 -> finish
```

Запрещённые реализации:

- считать каждый `runtime_step` новым AM query;
- вызывать AgentWork между зависимыми runtime steps одного AM query;
- исполнять `summarize_b` до завершения `summarize_c` для дочерних C;
- исполнять `finish_decision` параллельно с любым действием.

### C14R.10 Источник истины для config

Основной config: merged ailit config, загруженный через `load_merged_ailit_config_for_memory()`, плюс AgentMemory YAML из `load_or_create_agent_memory_config()`.

Обязательные ключи:

| Ключ | Значение по умолчанию | Правило |
|-----|---------|------|
| `memory.runtime.max_memory_queries_per_user_turn` | `6` | Cap AgentWork; превышение возвращает `blocked` с `too_many_memory_queries`. |
| `memory.runtime.max_runtime_steps_per_query` | `12` | Cap AM; каждый переход увеличивает счётчик. |
| `memory.runtime.max_llm_commands_per_query` | `20` | Включает `plan_traversal`, `summarize_c`, `summarize_b`, `finish_decision`. |
| `memory.runtime.max_frontier_items` | `200` | Listing, переданный в `plan_traversal`, детерминированно обрезается с `truncated=true`. |
| `memory.runtime.max_c_text_chars` | `12000` | На один вход `summarize_c`. Больший C делится на меньшие C boundaries или возвращает partial. |
| `memory.runtime.max_read_line_ranges` | `40` | На один AM query. |
| `memory.runtime.strict_command_json` | `true` | Parser отклоняет не-JSON или неизвестные поля с journal event. |
| `memory.runtime.allow_parallel_action_batches` | `false` | По умолчанию действия внутри одного AM query исполняются строго последовательно; включение требует тестов из C14R.9. |

Тестовая изоляция должна использовать существующую изоляцию корневого `conftest.py` (`AILIT_*`, временный HOME, временные PAG/KB/journal). Subprocess tests обязаны явно передавать тот же env.

### C14R.11 Контракт observability и обновления AgentMemory logs

W14 обязан обновить AgentMemory logs/chat_logs по ранее согласованному W13 варианту: компактный audit/verbose путь, стабильные topic names, whitelist payload и запрет сырого prompt/полного текста. Это не advisory: этап нельзя закрыть, если новые runtime/command события пишутся только в journal и не видны в AgentMemory chat debug logs.

Обязательные journal/trace/chat_logs events:

| Event/topic | Когда | Компактный payload |
|-------------|------|-----------------|
| `memory.query.accepted` | AM принял AgentWork query | `query_id`, `user_turn_id`, `expected_result_kind`, budgets |
| `memory.runtime.step` | Каждый переход `runtime_step` | `step_id`, `state`, `next_state`, action kind, counters |
| `memory.command.requested` | Перед LLM command | `command`, `command_id`, `query_id`, compact input stats, `prompt_id`, без prompt text |
| `memory.command.parsed` | Валидный JSON от LLM | `command`, `status`, result counts, `schema_version` |
| `memory.command.rejected` | Невалидный JSON/schema/unknown action | `command`, `error_code`, `command_id`, `prompt_id` |
| `memory.node.decomposed` | B -> C boundaries materialized | `b_node_id`, `c_count`, `strategy` |
| `memory.summary.created` | Записан C или B summary | `level`, `node_id`, `summary_fingerprint`, `command_id` |
| `memory.result.returned` | AM возвращает result в AgentWork | `query_id`, `status`, result kinds/counts |
| `memory.chat_debug.command` | Запись в `AgentMemoryChatDebugLog` для команды | `command`, `prompt_id`, `command_id`, input/output sizes, redaction policy |

Запрещённые payload fields: сырой полный prompt, chain-of-thought, секреты, полный текст файлов, полный listing репозитория сверх cap. `read_lines` могут появляться в AM response payload только когда выбраны как результат; journal/chat_logs хранят hashes/counts, а не сырой текст.

---

## 4. Общий алгоритм AgentMemory

1. **Принять query.** Провалидировать `agent_work_memory_query.v1`; назначить `query_id`; загрузить бюджеты.
2. **Построить первый frontier.** AM отправляет в LLM только listing первого уровня A-B и A-C:
   - metadata корня A;
   - B, которые являются прямыми детьми A;
   - C, которые являются прямыми детьми B первого уровня, если они уже материализованы и свежие;
   - только summaries, без raw B content.
3. **Вызвать `plan_traversal`.** LLM возвращает ограниченные actions из whitelist.
4. **Детерминированно выполнить runtime action.**
   - `list_children` для A/B читает PAG/index/listing и обновляет frontier.
   - `get_b_summary` возвращает только B summary+path.
   - `get_c_content` добавляет кандидаты C summary или ограниченные read_lines.
   - `decompose_b_to_c` запускает создание C boundaries для B-файла.
   - `summarize_c` создаёт/обновляет C summary через LLM.
   - `summarize_b` создаёт/обновляет B summary через LLM из дочерних summaries.
5. **Повторять внутри бюджета.** Runtime проходит переходы `runtime_step`, пока кандидат результата не достаточен, query не заблокирован или бюджет не исчерпан.
6. **Вызвать `finish_decision`.** LLM явно выбирает финальные `selected_results` и status.
7. **Создать D summary.** Если policy разрешает, создать D из финального AM result и связанных node ids.
8. **Вернуть AM result в AgentWork.** AgentWork может запросить другой AM query для другого subgoal; это единственный разрешённый multi-query путь.

Главный инвариант:

```text
AM никогда не возвращает сырой B content.
Финальный результат AM — C summaries и/или read_lines из C, плюс B paths только для задач создания/выбора места.
```

---

## 5. Таблица трассировки ID -> этап

| ID | Этап-исполнитель |
|----|------------------|
| A14R.1, A14R.2, A14R.3 | G14R.2, G14R.3 |
| A14R.4, C14R.2 | G14R.4, G14R.5 |
| A14R.5 | G14R.4 |
| A14R.6 | G14R.7 |
| A14R.7, C14R.1, C14R.1a | G14R.0, G14R.1, G14R.7 |
| A14R.8, A14R.9 | G14R.7 |
| A14R.10, A14R.11 | G14R.2 |
| A14R.12 | G14R.1 |
| A14R.13 | G14R.10 |
| A14R.14 | G14R.9 |
| A14R.15, D14R.4 | G14R.6 |
| D14R.1, D14R.2, D14R.3 | G14R.0, G14R.11 |
| C14R.3, C14R.4 | G14R.2, G14R.3 |
| C14R.5, C14R.6, C14R.7 | G14R.3 |
| C14R.8 | G14R.2, G14R.3 |
| C14R.9 | G14R.1, G14R.3 |
| C14R.10 | G14R.2, G14R.11 |
| C14R.11 | G14R.9, G14R.10, G14R.11 |

---

## 6. Этапы реализации

### G14R.0 — Design freeze: clean replacement без migration

**Обязательные описания/выводы:** D14R.1, D14R.2, D14R.3, D14R.4, C14R.1a.

Якоря реализации:

- `plan/14-agent-memory-runtime.md` — решения D14R.1-D14R.4 должны оставаться нормативными для всех следующих этапов.
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — проверить будущую точку ответа `memory.query_context`, где появится `payload.agent_memory_result`.
- `tools/agent_core/runtime/agent_memory_query_pipeline.py` — проверить будущую точку отключения `requested_reads`.

Критерии приемки:

- `test_w14_clean_replacement_has_no_migration_mode`
- `test_query_context_returns_agent_memory_result_next_to_memory_slice`
- `test_legacy_requested_reads_rejected_after_clean_replacement`

Статические проверки:

- `rg "migration|migrate|legacy data compatibility" tools/agent_core/runtime tests` -> пусто или только в negative tests / comments W14.
- `rg "agent_memory_result" tools/agent_core/runtime tests` -> есть DTO/response path и tests.

Запрещённые реализации:

- начинать W14 с migration старых баз;
- сохранять старые `requested_reads` как рабочий путь после G14R.3;
- использовать `memory_slice` как единственный контейнер результата W14.

### G14R.1 — Политика memory query для AgentWork

**Обязательные описания/выводы:** C14R.1, A14R.7, A14R.12.

Якоря реализации:

- `tools/agent_core/runtime/subprocess_agents/work_agent.py` — найти место, где AgentWork запрашивает `memory.query_context`; ввести `user_turn_id`, `query_id`, `subgoal`.
- `tools/agent_core/runtime/models.py` — создать явный DTO/envelope для `agent_work_memory_query.v1`; generic payload не является source of truth для W14.
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — принимать новый query envelope без потери backward compatibility только на один workflow-релиз.

Критерии приемки:

- `test_agentwork_can_issue_multiple_memory_queries_for_one_turn`
- `test_agentwork_memory_query_loop_stops_at_config_cap`
- `test_memory_query_requires_subgoal_and_stop_condition`

Статические проверки:

- `rg "max_memory_queries_per_user_turn" tools/agent_core tests` -> ключ есть в parsing config и tests.

Запрещённые реализации:

- скрытый цикл `while partial` без нового `subgoal`;
- повторное использование `recommended_next_step` как исполняемой command string.

### G14R.2 — DTO runtime step и registry команд

**Обязательные описания/выводы:** C14R.3, C14R.4, C14R.8, C14R.10, A14R.1, A14R.10, A14R.11.

Якоря реализации:

- Разрешён новый модуль: `tools/agent_core/runtime/agent_memory_runtime_contract.py`.
- `tools/agent_core/runtime/agent_memory_query_pipeline.py` обязан импортировать и использовать registry; параллельный parser внутри pipeline запрещён.
- `tools/agent_core/runtime/agent_memory_chat_log.py` или существующие log helpers обязаны логировать compact command events.

Критерии приемки:

- `test_runtime_step_rejects_unknown_state`
- `test_command_registry_rejects_unknown_command`
- `test_runtime_step_transition_table_blocks_invalid_transition`
- `test_command_output_rejects_prose_around_json`

Статические проверки:

- `rg "requested_reads" tools/agent_core/runtime/agent_memory_query_pipeline.py` -> только секция legacy adapter с комментарием `W14R legacy adapter remove after G14R.3`.

Запрещённые реализации:

- разбросанные string literals для имён команд;
- parser, который молча отбрасывает unknown fields.

### G14R.3 — Prompt команд LLM и строгие JSON parsers

**Обязательные описания/выводы:** C14R.3, C14R.4, C14R.5, C14R.6, C14R.7, C14R.9.

Якоря реализации:

- `tools/agent_core/runtime/agent_memory_query_pipeline.py` — заменить старый путь `PLANNER_SYSTEM` на command-specific prompts.
- Разрешён новый модуль `tools/agent_core/runtime/agent_memory_commands.py` с prompt builders и typed parse results.
- `tools/agent_core/runtime/agent_memory_config.py` — переиспользовать `parse_memory_json_with_retry` только если он отклоняет non-JSON wrappers при `strict_command_json=true`.

Критерии приемки:

- `test_plan_traversal_prompt_forbids_invented_paths`
- `test_plan_traversal_allows_only_whitelisted_actions`
- `test_finish_decision_must_select_existing_candidate_results`
- `test_summarize_c_claims_require_source_lines`
- `test_summarize_b_requires_child_summaries`
- `test_plan_traversal_prompt_contains_required_output_schema`
- `test_summarize_c_prompt_contains_required_output_schema`
- `test_summarize_b_prompt_contains_required_output_schema`
- `test_finish_decision_prompt_contains_required_output_schema`
- `test_one_query_executes_dependent_runtime_steps_sequentially`
- `test_parallel_action_batches_disabled_by_default`

Запрещённые реализации:

- один mega prompt, который может вернуть любую shape;
- free-form markdown с последующим best-effort JSON extraction в strict mode.

### G14R.4 — Runtime-декомпозиция B -> C

**Обязательные описания/выводы:** A14R.4, A14R.5, C14R.2.

Якоря реализации:

- `tools/agent_core/runtime/memory_c_segmentation.py` — единый service для C boundaries.
- `tools/agent_core/memory/pag_indexer.py` — перестать считать Python-only AST C единственным C source; новый service должен покрывать code/text с явным `semantic_kind`.
- `tools/agent_core/runtime/pag_graph_write_service.py` — все C writes идут через graph write service.

Критерии приемки:

- `test_decompose_b_to_c_python_function_boundaries`
- `test_decompose_b_to_c_markdown_sections`
- `test_decompose_b_to_c_text_line_windows_when_no_structure`
- `test_decompose_b_to_c_respects_source_boundary_policy`

Запрещённые реализации:

- возврат целого сырого B file в LLM;
- C ids, которые меняются при изменении нерелевантных строк файла, когда content C не изменился.

### G14R.5 — LLM summaries для C и B

**Обязательные описания/выводы:** C14R.2, A14R.4, D14R.4.

Якоря реализации:

- Разрешён новый модуль: `tools/agent_core/runtime/agent_memory_summary_service.py`.
- `tools/agent_core/runtime/semantic_c_extraction.py` и `memory_c_extractor_prompt.py` должны быть проверены только как reference. Новый runtime W14 не должен импортировать их как implementation.
- `tools/agent_core/memory/sqlite_pag.py` / `PagGraphWriteService` существующие поля node должны хранить `summary`, `fingerprint`, `attrs.summary_fingerprint`.

Критерии приемки:

- `test_summarize_c_writes_summary_and_summary_fingerprint`
- `test_summarize_b_file_uses_only_child_c_summaries`
- `test_summarize_b_directory_uses_child_b_or_c_summaries`
- `test_b_summary_invalidates_when_child_summary_fingerprint_changes`

Запрещённые реализации:

- B summary `"File"` / `"Directory"` после закрытия W14R;
- B summary, созданный из сырого полного файла вместо дочерних C summaries.
- импорт `semantic_c_extraction.py` или `memory_c_extractor_prompt.py` из нового `agent_memory_summary_service.py`.

### G14R.6 — Legacy C extraction quarantine/removal

**Обязательные описания/выводы:** A14R.15, D14R.4.

Этап начинается только после того, как G14R.5 создал новый `agent_memory_summary_service.py`. Старые модули нельзя удалять первым шагом workflow, потому что до появления нового пути они остаются полезным reference и могут быть нужны старым tests. Но до финального DoD они должны быть удалены или закарантинены так, чтобы W14 runtime их не импортировал.

Якоря реализации:

- `tools/agent_core/runtime/semantic_c_extraction.py`
- `tools/agent_core/runtime/memory_c_extractor_prompt.py`
- `tools/agent_core/runtime/agent_memory_summary_service.py`
- `tools/agent_core/runtime/agent_memory_query_pipeline.py`
- `tests/test_g14_agent_memory_runtime_contract.py` или новый `ailit/agent_memory/tests/test_g14_agent_memory_legacy_quarantine.py`

Критерии приемки:

- `test_w14_runtime_does_not_import_legacy_c_extraction`
- `test_w14_runtime_uses_summary_service_for_c_and_b`
- `test_legacy_c_extraction_modules_are_deleted_or_quarantined`

Статические проверки:

- `rg "semantic_c_extraction|memory_c_extractor_prompt" tools/agent_core/runtime tests` -> whitelist: только quarantine tests, archive/reference comments или удалённые файлы.
- `rg "agent_memory_summary_service" tools/agent_core/runtime tests` -> есть production imports и tests.

Запрещённые реализации:

- удалить legacy модули до появления нового summary service;
- оставить импорт legacy C extraction из W14 runtime;
- закрыть workflow, если `semantic_c_extraction.py` остаётся production dependency.

### G14R.7 — Сборка результата: C summaries и read_lines

**Обязательные описания/выводы:** A14R.7, A14R.8, A14R.9, §1.3, C14R.1a, D14R.3.

Якоря реализации:

- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — response payload должен включать `agent_memory_result.v1` или маппить его в существующий `memory_slice` без потери полей.
- `tools/agent_core/tool_runtime/memory_grants.py` — ranges для read_lines должны быть покрыты grants.
- `tools/agent_core/tool_runtime/multi_root_paths.py` — path validation должен идти через один shared helper; второй независимый helper для W14 запрещён.

Критерии приемки:

- `test_memory_result_contains_c_summary_without_raw_b_content`
- `test_memory_result_read_lines_are_granted_ranges`
- `test_memory_result_rejects_absolute_and_parent_paths`
- `test_create_file_subgoal_may_return_b_path_without_c_content`
- `test_query_context_returns_agent_memory_result_next_to_memory_slice`

Запрещённые реализации:

- full-file grant для каждого выбранного C;
- AM response, который только говорит "read selected context" без выбранных C/read_lines.
- возврат `agent_memory_result.v1` только внутри `memory_slice`.

### G14R.8 — D summary после AM result

**Обязательные описания/выводы:** A14R.6.

Якоря реализации:

- `tools/agent_core/runtime/d_creation_policy.py` — переиспользовать fingerprint/dedupe.
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — вызывать создание D только после `finish_decision`.

Критерии приемки:

- `test_d_summary_created_after_finish_decision`
- `test_d_summary_links_to_selected_abc_nodes`
- `test_d_summary_not_used_as_b_or_c_source`

### G14R.9 — Обновление AgentMemory logs/chat_logs по W13 contract

**Обязательные описания/выводы:** A14R.14, C14R.11.

Якоря реализации:

- `tools/agent_core/runtime/memory_journal.py`
- `tools/agent_core/runtime/agent_memory_chat_log.py`
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py`
- `ailit/agent_memory/tests/test_g13_agent_memory_llm_pipeline.py` или новый `ailit/agent_memory/tests/test_g14_agent_memory_runtime_logs.py`

Критерии приемки:

- `test_agent_memory_chat_log_records_command_requested_without_raw_prompt`
- `test_agent_memory_chat_log_records_command_rejected_with_error_code`
- `test_memory_journal_and_chat_log_share_command_id`
- `test_memory_logs_do_not_store_full_file_text`

Статические проверки:

- `rg "memory.command.requested|memory.command.parsed|memory.command.rejected" tools/agent_core/runtime tests` -> есть runtime writer и tests.
- `rg "prompt_text|raw_prompt|full_file_text" tools/agent_core/runtime/agent_memory_chat_log.py tests` -> только whitelist/redaction tests, не production payload.

Запрещённые реализации:

- писать новые command events только в journal и не писать в AgentMemory chat debug logs;
- логировать полный prompt или сырой C/B text;
- использовать разные `command_id` в journal и chat_logs.

### G14R.10 — Observability и desktop-safe compact payloads

**Обязательные описания/выводы:** C14R.11, A14R.13.

Якоря реализации:

- `tools/agent_core/runtime/memory_journal.py`
- `tools/agent_core/runtime/agent_memory_chat_log.py`
- `context/proto/runtime-event-contract.md` — add compact W14R event section after implementation.

Критерии приемки:

- `test_memory_runtime_step_journal_has_compact_payload`
- `test_memory_command_rejected_logs_error_code_without_prompt`
- `test_memory_result_returned_logs_counts_not_raw_text`

Ручной smoke:

1. Запустить `ailit desktop --dev` или runtime test environment.
2. Спросить "о чем этот репозиторий".
3. Проверить, что journal содержит `memory.runtime.step`, `memory.command.parsed`, `memory.result.returned`.
4. Проверить, что ни одна journal/chat_logs строка не содержит полный prompt или полный текст файла.

### G14R.11 — Интеграция, README/context и удаление старого planner

**Обязательные описания/выводы:** D14R.1-D14R.4, C14R.10, C14R.11, все audit findings.

Якоря реализации:

- `README.md` — обновить строку текущего Workflow 14 после закрытия implementation, не при одном только draft плана.
- `context/INDEX.md` и `context/proto/runtime-event-contract.md` — добавить короткий canonical contract.
- `plan/14-agent-memory-planner-command-contract.md` — пометить superseded этим планом или архивировать в README status.

Критерии приемки:

- `test_query_context_runtime_happy_path_repo_question`
- `test_query_context_runtime_happy_path_file_question`
- `test_query_context_runtime_partial_when_budget_exhausted`
- `test_legacy_requested_reads_disabled_after_w14r`
- `test_w14_no_runtime_imports_from_legacy_c_modules`

Definition of Done (критерий закрытия):

- Все tests, названные в G14R.0-G14R.11, существуют и проходят.
- `flake8` проходит по изменённым Python files.
- `pytest` проходит минимум по затронутым AgentMemory/runtime tests.
- Ручной smoke записан в task/commit note.
- README/context обновлены в closing commit.
- Самопроверка из `.cursor/rules/project-workflow.mdc` проходит.

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
- тихий fallback на README после невалидного path;
- вернуть весь README как raw B content.

### 7.2 Пользователь: "Изучи репозиторий, посмотри каждый файл и построй дерево памяти"

Человеческий смысл:

1. Это не один LLM prompt и не один гигантский сырой context.
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
2. Если путь не найден на первом уровне, LLM просит `list_children` по B-папкам, но только через ограниченный traversal.
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
  "decision_summary": "AM query готов к завершению.",
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

Валидный результат:

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
      "reason": "Здесь находятся runtime-модули AgentMemory; новый модуль command contract должен быть в этой папке."
    },
    {
      "kind": "c_summary",
      "path": "tools/agent_core/runtime/agent_memory_query_pipeline.py",
      "c_node_id": "C:...",
      "summary": "Текущий query pipeline отвечает за вызовы planner и рост PAG.",
      "read_lines": [],
      "reason": "Anchor для интеграции."
    }
  ],
  "decision_summary": "AgentWork получил целевую папку и anchor для интеграции.",
  "recommended_next_step": "",
  "runtime_trace": {
    "steps_executed": 6,
    "final_step": "finish",
    "partial_reasons": []
  }
}
```

---

## 8. Зависимости

```text
G14R.0 clean replacement freeze
  -> G14R.1 AgentWork policy
  -> G14R.2 runtime_step + registry
  -> G14R.3 prompts/parsers
  -> G14R.4 B->C decomposition
  -> G14R.5 summaries
  -> G14R.6 legacy C quarantine/removal
  -> G14R.7 result assembly
  -> G14R.8 D after result
  -> G14R.9 AgentMemory logs/chat_logs
  -> G14R.10 observability
  -> G14R.11 integration/README/context
```

G14R.0 должен быть закрыт до любых code changes. G14R.4 стартует только после freeze имён DTO в G14R.2. G14R.5 нельзя закрывать до того, как G14R.4 создаёт стабильные C boundaries. G14R.6 стартует только после появления нового `agent_memory_summary_service.py` из G14R.5 и не закрывается, пока W14 runtime импортирует legacy C modules. G14R.7 нельзя закрывать до появления `finish_decision` из G14R.3. G14R.9 нельзя закрывать без проверки chat_logs, а G14R.10 нельзя закрывать без compact payload contract в `context/proto/runtime-event-contract.md`.

---

## 9. Checklist самопроверки для этого плана

- Каждая audit finding A14R.* имеет этап-исполнитель в §5.
- Каждый contract C14R.* привязан к одному или нескольким этапам.
- Нет этапа, где написано только "add tests"; каждый test имеет обязательное имя.
- Команды включают входной JSON, выходной JSON, полный prompt и prompt restrictions.
- Матрица команд LLM содержит: command, что делает, когда вызывается, input, output, prompt id, parser/DTO anchor и tests.
- `runtime_step` включает state, transition, budgets и observability.
- Политика B summary строгая: только через LLM и только из child summaries.
- Политика AgentWork multi-query строгая и ограничена cap.
- Модель последовательных runtime steps внутри одного AM query явно описана и покрыта tests.
- Clean replacement без migration старых баз зафиксирован в D14R.1-D14R.4.
- `agent_memory_result.v1` возвращается отдельным `payload.agent_memory_result`, а не только внутри `memory_slice`.
- Legacy C extraction modules удалены или закарантинены отдельным этапом после появления нового summary service.
- Exact config source и правила env isolation указаны.
- Anti-patterns запрещают namespace-as-path, raw B content, silent fallback, hidden loops.
- DoD требует end-to-end путь от AgentWork query до AM result, D, observability, context/README.

---

## 10. Changelog плана

| Дата | Изменение |
|------|-----------|
| 2026-04-29 | Первичная публикация `plan/14-agent-memory-runtime.md`: AgentWork/AM policy, command protocol, runtime_step, B/C/D summary policy, общий алгоритм, этапы G14R.1-G14R.9, простые сценарии из старого пункта 6 в новой терминологии. |
| 2026-04-29 | Вторая итерация: добавлена матрица LLM commands, полные русскоязычные prompts, явная модель последовательных runtime steps внутри одного AM query, отдельный этап AgentMemory logs/chat_logs, расширены tests и обновлена терминология. |
| 2026-04-29 | Третья итерация: зафиксирован clean replacement без migration старых баз, отдельный `payload.agent_memory_result`, вариант B для legacy C extraction и этап quarantine/removal старых C-модулей после нового summary service. |

---

*Конец документа Workflow 14 Runtime.*
