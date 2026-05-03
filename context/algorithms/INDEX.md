# Target Algorithms

Этот раздел хранит утверждённые человеком целевые алгоритмы подсистем. Документы отсюда являются канонической опорой для `start-feature` и `start-fix`: аналитик, планировщик и test runner должны трассировать изменения к соответствующему target flow, commands, observability и acceptance criteria.

## Правила

- Новый документ создаётся через `start-research` / `18_target_doc_orchestrator`.
- Документ получает статус `approved` только после review `22_target_doc_verifier` и явного OK пользователя.
- Feature/fix pipeline не должен менять целевой алгоритм молча. Если реализация требует изменить поведение из target doc, это оформляется как отдельный target-doc update или blocker.
- Документы пишутся человеческим языком, но содержат точные технические контракты, команды проверки, failure rules и anti-patterns.

## Документы

| Документ | Назначение | Статус |
|----------|------------|--------|
| [agent-memory/INDEX.md](agent-memory/INDEX.md) | Целевой алгоритм **AgentMemory**: broker/CLI, W14, PAG graph, LLM protocol, события, failure/retry. | `approved` (2026-05-03) |
