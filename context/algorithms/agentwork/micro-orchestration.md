# Микро-оркестрация: классификация, план, verify, repair

Центральный класс: `WorkTaskOrchestrator` в `work_orchestrator.py`. Он намеренно остаётся **над** `SessionRunner`: один и тот же runner может обслуживать другие профили агентов в будущем.

## Включение и обход

- Глобальный выключатель: переменная окружения `AILIT_WORK_MICRO_ORCHESTRATOR` в значениях `0/false/no/off` — оркестратор пропускается, вызывается только `_execute(base_messages)` (legacy-путь).
- Профильный выключатель: в merge-конфиге `agent_work.enabled: false` — то же поведение.

## Фазы (события trace)

События вида `work.phase.started` / `work.phase.finished` с полем `phase`:

| Значение `phase` | Смысл |
|------------------|--------|
| `classify` | Определён `WorkTaskKind` |
| `micro_plan` | Построен `WorkTaskPlan` |
| `execute` | Запущен SessionRunner |
| `verify` | Запущен RuntimeVerifier |
| `repair` | Повторный execute после провала verify |
| `final` | (косвенно) итог в `WorkTaskResult` |

План публикуется отдельным событием **`work.micro_plan.compact`** (payload из `WorkTaskPlan.to_payload` + `chat_id`, `message_id`).

## Классификатор задач (`TaskClassifier`)

Полностью **детерминированный** разбор текста пользователя по подстрокам (англ. и рус. маркеры):

- **LARGE_CODE_CHANGE** — «workflow», «architecture», «реализуй этап», …
- **SMALL_CODE_CHANGE** — «fix», «pytest», «добав», …
- **READ_ONLY** — «explain», «покажи», «где», …
- **CHAT_ONLY** — пустой текст, вопросительный стиль без code-маркеров, fallback.

Нет отдельного LLM-классификатора на этом уровне (в отличие от perm-режима).

## Micro-planner (`MicroPlanner`)

Строит `WorkTaskPlan`: `kind`, `summary` (до ~160 символов), кортеж `WorkStep` с заголовками и `done_when`, опционально `expected_files` из эвристик по путям в тексте пользователя (`_extract_expected_files`).

- Для **small_code_change**: три шага — найти точку изменения, локальная правка, точечная проверка.
- Для **large_code_change**: не выполнять как micro-task; вернуть пользователю текст декомпозиции (`_large_task_text`), **без** вызова SessionRunner на полную реализацию.
- Для **read_only** и **chat_only**: минимальные шаги без verify-цепочки на код.

## Подмешивание плана в промпт

Для задач **не** класса `CHAT_ONLY` и **не** `READ_ONLY` (на практике это **`SMALL_CODE_CHANGE`**, потому что `LARGE_CODE_CHANGE` завершается до фазы execute) в хвост сообщений добавляется **скрытое** system-сообщение с префиксом `[ailit-work-orchestrator]`, JSON-представлением плана и инструкцией не расширять scope и не объявлять финал до verify gate. Перед сохранением истории эти сообщения удаляются (`_strip_orchestrator_messages`).

## Execute

`_execute` вызывает `SessionRunner.run` в цикле: если состояние `WAITING_APPROVAL`, извлекается `call_id` из событий, вызывается `wait_for_approval` (блокировка до Desktop), затем повтор.

Сбор изменённых файлов: по событиям `tool.call_finished` с `ok` и полем `relative_path`.

## Verify (`RuntimeVerifier`)

Активен при `verify_policy == python_default"` (значение из профиля `AgentWorkProfile`).

Только для **`WorkTaskKind.SMALL_CODE_CHANGE`**:

- До трёх команд `python -m pytest` по изменённым файлам под `tests/` или с `test` в имени.
- Если доступен flake8 — одна команда по списку изменённых `.py` (до 12 файлов).

Таймаут одной команды 120 с, усечение stdout/stderr для trace. Результат публикуется событием **`work.verify.finished`**.

## Repair

Если verify не `ok`, не `skipped`, и `max_repair_attempts > 0`, добавляется ещё одно orchestrator system-сообщение с кратким дампом провала и повторяется `_execute`. После успешного repair verify может запуститься снова на объединённом списке файлов.

## Итоговый текст пользователю (`_final_text`)

Для small_code_change к последнему ответу ассистента дописывается строка о результате проверки (успех / пропуск / не прошла с перечислением команд).
