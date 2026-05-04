# Feature: канон arch/proto — W14 links, external events, журнал

## Что зафиксировано в `context/`

- **`context/arch/system-elements.md`:** P3 — цепочка `propose_links` → `AgentMemoryLinkCandidateValidator` → `PagGraphWriteService`; журнал `memory.external_event` и `agent_memory.external_event.v1`; поле `durability` JSONL; OR-013 (`agent_memory_terminal_outcomes.py`).
- **`context/proto/broker-memory-work-inject.md`:** отдельный подраздел W14 propose_links / PAG / внешние события / durability; расширен блок «Связанный код».
- **`context/proto/runtime-event-contract.md`:** ссылка на SoT каталога внешних событий (вне whitelist D-OBS-1).

## Источник фактов

Реализация: `tools/agent_core/runtime/agent_memory_query_pipeline.py`, `agent_memory_link_candidate_validator.py`, `pag_graph_write_service.py`, `agent_memory_external_events.py`, `memory_journal.py`, `agent_memory_terminal_outcomes.py`, `subprocess_agents/memory_agent.py`.

## Связанные воспоминания

- [`feature_memory_init_fix_2026-05-02.md`](feature_memory_init_fix_2026-05-02.md) — UC-03 VERIFY и `memory-query-context-init.md`.

## Оглавление

[`index.md`](index.md)
