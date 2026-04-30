# Контракты артефактов пайплайна (`artifact-*.mdc`)

Здесь зафиксированы **пути файлов**, **JSON в начале ответа** субагента (если есть) и **минимальная структура** markdown-артефактов. Детальные чеклисты и примеры — в процессных правилах (`main/*-process.mdc`, `review-*/*-process.mdc`).

**Правило:** если агент **X** потребляет выход **K**, оба в блоке **«Обязательно прочитай»** указывают **один и тот же** `artifact-*.mdc` (и при необходимости узкие процессные файлы).

| Файл | Содержание | Продюсер | Потребители (минимум) |
|------|------------|----------|------------------------|
| [artifact-technical-specification.mdc](artifact-technical-specification.mdc) | `technical_specification.md`, JSON 02 | 02 | 03, 04, 06, 07 |
| [artifact-tz-review.mdc](artifact-tz-review.mdc) | `tz_review.md`, JSON 03 | 03 | 02 |
| [artifact-architecture.mdc](artifact-architecture.mdc) | `architecture.md`, JSON 04 | 04 | 05, 06 |
| [artifact-architecture-review.mdc](artifact-architecture-review.mdc) | `architecture_review.md`, JSON 05 | 05 | 04 |
| [artifact-open-questions.mdc](artifact-open-questions.mdc) | `open_questions.md` (единый формат) | 04, 06, 08 | оркестратор, следующий исполнитель |
| [artifact-plan.mdc](artifact-plan.mdc) | `plan.md` | 06 | 07, 08, 09 |
| [artifact-task-description.mdc](artifact-task-description.mdc) | `tasks/task_X_Y.md` | 06 | 07, 08, 09 |
| [artifact-planner-response.mdc](artifact-planner-response.mdc) | JSON 06 (план + задачи + `task_waves`) | 06 | 07, 01 (оркестратор) |
| [artifact-plan-review.mdc](artifact-plan-review.mdc) | `plan_review.md`, JSON ревью плана | 07 | 06, оркестратор |
| [artifact-developer-response.mdc](artifact-developer-response.mdc) | JSON 08, отчёты тестов | 08 | 09, оркестратор (опц.) |
| [artifact-code-review-response.mdc](artifact-code-review-response.mdc) | JSON 09 | 09 | 08 |
| [artifact-test-report.mdc](artifact-test-report.mdc) | отчёты прогона / пути логов | 08, 11 | 09, `fix_by_tests` |
| [artifact-change-inventory.mdc](artifact-change-inventory.mdc) | `change_inventory.md` | 12 | 13, 01 (completion diagnostics) |
| [artifact-tech-writer-report.mdc](artifact-tech-writer-report.mdc) | `tech_writer_report.md` | 13 | 01, selective sync step |

Файл **`{artifacts_dir}/escalation_pending.md`** при эскалации к пользователю (блокирующие вопросы, конфликты, ожидание решения) описан в [`main/orchestrator-stage-blocked.mdc`](../main/orchestrator-stage-blocked.mdc) и [`main/orchestrator-duties.mdc`](../main/orchestrator-duties.mdc); отдельный `artifact-*.mdc` не используется.

Оркестратор (**01**) не обязан читать весь набор: при расхождении формата ответа субагента — сверка с этим каталогом или конкретным `artifact-*.mdc` (см. [orchestrator-duties.mdc](../main/orchestrator-duties.mdc)).
