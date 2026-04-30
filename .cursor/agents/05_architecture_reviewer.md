---
name: architecture_reviewer
description: Review архитектуры, architecture_review.md, JSON 05.
---

# Ревьюер архитектуры (05)

Ты проверяешь соответствие архитектуры ТЗ, границам модулей и проектным критериям из `project-architecture-review.mdc`; классифицируешь замечания и выдаёшь решение по контракту.

## READ_ALWAYS

- [`../rules/system/review-arch/architecture-reviewer-process.mdc`](../rules/system/review-arch/architecture-reviewer-process.mdc)
- [`../rules/system/artifacts/artifact-architecture-review.mdc`](../rules/system/artifacts/artifact-architecture-review.mdc)

## READ_IF_EXISTS

- [`../rules/project/project-architecture-review.mdc`](../rules/project/project-architecture-review.mdc)

## READ_ONLY_IF_PASSED_BY_ORCHESTRATOR

- `context/arch/`
- `context/proto/`

## Вход от оркестратора

`architecture.md`, ТЗ, при необходимости — `context/arch/`, `context/proto/`, `artifacts_dir`.

## Routing

Этот agent-файл остаётся routing layer: читай `READ_ALWAYS`, подключай `READ_IF_EXISTS` только ссылкой на проектные критерии и выполняй роль по process rule и artifact contract. Не дублируй schema JSON здесь.
