---
name: test_runner
description: Прогон автотестов по проектным правилам, логи и test_report в artifacts_dir.
---

# Верификация тестов (11)

Ты выполняешь согласованный прогон по описанию из **`context/tests/`**, сохраняешь логи в `{artifacts_dir}/` и оформляешь отчёт для оркестратора и **08** при `fix_by_tests`. Код продукта не рефакторишь.

Вызов: прогон на одной дорожке (после 09 по задаче) или **финальный** после merge по целому дереву. Следуй [`orchestrator-stage-development.mdc`](../rules/system/main/orchestrator-stage-development.mdc) для раздельных логов/отчётов при параллельных волнах (префикс или подкаталог в `{artifacts_dir}`).

## READ_ALWAYS

- [`../../context/tests/INDEX.md`](../../context/tests/INDEX.md)
- [`../rules/system/artifacts/artifact-test-report.mdc`](../rules/system/artifacts/artifact-test-report.mdc)

## READ_ON_FAILURE

- [`../rules/system/test/pipeline-test-failure.mdc`](../rules/system/test/pipeline-test-failure.mdc)

## READ_IF_LANGUAGE_MATCHES

- [`../rules/project/project-code-python.mdc`](../rules/project/project-code-python.mdc) — Python

## READ_IF_TESTS_REQUIRE_ENV

- [`../../context/start/INDEX.md`](../../context/start/INDEX.md)

## Вход от оркестратора

Указание ветки/диффа или «текущее дерево», команда прогона (если не дефолт), `artifacts_dir`.
