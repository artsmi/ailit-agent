<!-- Canonical AgentMemory target algorithm — published after user approval 2026-05-03 -->
**Источник:** черновик `context/artifacts/target_doc/target_algorithm_draft.md` (Produced by: 21_target_doc_author), верификация `context/artifacts/target_doc/verification.md`.

# failure-retry-observability

## Failure And Retry Rules

### Матрица (user list + уточнения)

| Условие | Исход AMR | Примечание |
|---------|-----------|------------|
| LLM API недоступен после bounded retry | `blocked` | Единственный класс для инфраструктуры провайдера |
| Invalid JSON / W14 parse (repair разрешён) | один repair; иначе `partial` + contract failure | См. pipeline F8 |
| Invalid JSON строгого пути (`invalid json` substring) | repair **запрещён** | `_should_repair_w14_error` |
| LLM ссылается на несуществующую ноду | `partial` или structured reject шага | Без бесконечных повторов |
| Invalid graph link candidate | candidate отклонён; основной результат возможен → `partial`/`complete` с reason в trace | Низкая confidence не promoted |
| Пустая БД | разрешённый indexing / walk flow (init, memory_init) | Не crash |
| Файл удалён / недоступен | `partial` + reason | |
| Язык неизвестен | fallback `unknown_text`, `semantic_chunk_kind = text_window` / `heading_section` | |
| Caps превышены (runtime limits / selection caps) | `partial` + reason | `stop_condition` сейчас **не** wired — gap |
| Есть полезные данные без полноты | `partial`, не silent success | |

### FR1: No infinite loops

Внутренний `run` **не** может планировать второй `plan_traversal` HTTP round без нового внешнего query. Continuation — на уровне AgentWork / init orchestrator с новым `query_id` и обновлёнными `known_*`.

### FR2: No silent success

Возврат `complete` при пустом `results` и отсутствии явной политики finish — **forbidden**; минимум `partial` с `reason`.

---
## Observability

### Security levels

1. **Default / production external:** journal события с компактными payload + key-based redaction (`redact_journal_value`); compact строки без полного LLM текста.
2. **Verbose chat log (`memory.debug.verbose == 1`):** может содержать полные LLM request/response — **не** смешивать с «внешним протоколом по умолчанию».
3. **Broker stdout rich stream:** полные graph DTO — **без** journal redaction; риск размера/PII — требует политики на стороне broker/Desktop.

### Обязательные семейства событий (имена)

- `memory.request.received`, `memory.command.requested|parsed|rejected|normalized`, `memory.runtime.step`, `memory.slice.returned`, `memory.result.returned`, `memory.index.node_updated`, `memory.query.budget_exceeded` (со стороны Work), `orch_memory_init_*` (CLI).

### Heartbeat / liveness (норматив vs текущий снимок — D1)

- **Норматив (цель):** допускается отдельное ephemeral событие liveness с низкочастотным тиком **или** эквивалентная проекция на UI без обмана «я жив», если нет прогресса.
- **Текущий снимок:** отдельного `heartbeat` event **нет**; liveness = непрерывные compact строки + `memory.runtime.step` + фазы оркестратора.

### Path scope design notes (non-normative)

Из donor claude-code: паттерн «normalize + prefix-under-root + carve-out internal roots» полезен для политики чтения/записи, если в будущем появятся множественные roots; **не** копировать env/имена.

---

## Design Notes From Donor Research (non-normative)

- **Opencode:** discriminated union по `type`; разделение durable vs ephemeral каналов; центральный каталог событий; reducer/projection для UI.
- **Claude-code:** resolver scope→root; единый предикат принадлежности пути; порядок permission gates; разделение осей PAG namespace vs session log dirs.

