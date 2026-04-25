# G9.9 — чеклист готовности релиза (Workflow 9, `ailit desktop`)

Канон постановки: [`plan/9-ailit-ui.md`](../plan/9-ailit-ui.md) (этап G9.9.4). Workflow-правила: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

## Статус

**Workflow 9 считается закрытым по коду и автотестам;** полный ручной прогон desktop на целевой Linux-машине остаётся вне обязательного CI.

## Проверки

| Пункт | Состояние | Примечание |
|-------|-----------|------------|
| Сборка desktop | OK (в репозитории) | `cd desktop && npm run typecheck && npm run lint && npm run build` |
| Упаковка Linux | По среде | `npm run package:linux` в `desktop/` (нужен Node) |
| Python: тесты G9.9 | OK | `tests/test_g9_9_e2e_desktop_workflow.py`, `tests/test_g9_9_degradation.py` + существующие runtime/PAG/CLI |
| Python: стиль | OK | `flake8` по затронутым файлам |
| Install | По среде | `./scripts/install` / `dev`; idempotency — по [`plan/deploy-project-strategy.md`](../plan/deploy-project-strategy.md) |
| `ailit desktop` без AppImage | OK (автотест) | Диагностика exit 2, подсказка `--dev` |
| `ailit project add` ошибки | OK | Некорректный path → exit 2 |
| Runtime недоступен | OK (автотест) | `ailit runtime status` → подсказки `systemctl` / `journalctl` |
| Отчёт MD/JSON | OK | `reportExport`, redaction в `traceNormalize` |
| Секреты в trace/report | OK по умолчанию | Redact чувствительных ключей; отчёт без file body в prod-режиме |
| Динамические агенты + диалог | OK | manifest, проекции, G9.7–G9.8 тесты |
| Ручной UX (чат, отчёт, PAG, highlight) | Вне CI | Выполнять на Linux с установленным бинарником при приёмке релиза |

## Перенос открытых пунктов

Пункты, которые **нельзя** закрыть в headless CI (полный прогон Electron, интерактив), не расширяют scope Workflow 9: фиксируются здесь и переносятся в следующий план **только** после согласования (см. project-workflow.mdc).
