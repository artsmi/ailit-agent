# Workflow: perm-5 (режимы tools + LLM‑классификатор как у доноров)

Документ задаёт **пятую итерацию** управления инструментами в `ailit chat` / `ailit agent`:

- **по умолчанию**: режим **Explore** = чтение файлов + shell (allowlist);
- на каждый запрос пользователя запускается **LLM‑классификатор** (отдельный prompt/вызов),
  который выбирает режим: `read`, `read_plan`, `explore`, `edit`, `not_sure`;
- `not_sure` → UI **обязан** спросить пользователя (и заблокировать основной ответ до выбора);
- решения классификатора записываются в KB как обучаемый сигнал, а в следующий классификатор
  передаётся **структурированная история последних N решений** (N — глобальный конфиг).

Канон процесса разработки репозитория: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

## 0. Доноры (ориентиры, без копипаста)

### 0.1 OpenCode: primary‑агенты с разными правами (Build vs Plan)

Build как дефолт “всё можно”, Plan как ограниченный режим (ask для edit/bash):

```48:66:/home/artem/reps/opencode/packages/web/src/content/docs/ru/agents.mdx
### Использование Build
...
Build — основной агент **по умолчанию** со всеми включенными инструментами.
...
### Использование Plan
...
По умолчанию ... значение `ask`:
- `file edits`
- `bash`
```

### 0.2 OpenCode: permission defaults и UI‑семантика ask (once/always/reject)

```147:179:/home/artem/reps/opencode/packages/web/src/content/docs/ru/permissions.mdx
## По умолчанию
...
- `doom_loop` и `external_directory` по умолчанию равны `"ask"`.
...
## Что означает «ask»
...
- `once`
- `always` (до конца сессии)
- `reject`
...
```

### 0.3 Claude Code: единая точка смены permission mode (не “тихо”)

```30:79:/home/artem/reps/claude-code/utils/sessionState.ts
export type SessionExternalMetadata = {
  permission_mode?: string | null
  ...
}
...
Register a listener for permission-mode changes ...
... so no mode-mutation path can silently bypass them.
```

## 1. Цель и проблема

В `ailit chat` модель может уйти в `write_file`/`run_shell`, хотя пользователь просил
“показать точки входа” или “запомнить”. В донорах это решено через режимы/permissions
и ask‑гейты, а не через ручной “переключатель в UI”.

Цель perm‑5: **автоматически** выбирать режим на каждом запросе пользователя,
обеспечить “обучаемость” (через KB‑историю решений) и сохранить контроль (not_sure → спросить).

## 2. Термины и режимы (канон)

### 2.1 Режимы

- **`read`**: только read‑инструменты (fs read/list/glob/grep, KB read/write разрешены).
- **`read_plan`**: `read` + создание *неисполняемых* файлов по запросу пользователя.
  Ограничение: **не менять структуру проекта**, писать только в workdir, запрещены shell‑команды.
- **`explore`**: `read` + `run_shell` по allowlist без вопросов; всё остальное shell → ask.
- **`edit`**: `explore` + `write_file`/patch (полные правки) → ask/allow по политике проекта.
- **`not_sure`**: режим не определён; UI обязан спросить пользователя.

### 2.2 Дефолты

- Дефолт для `ailit chat`: **`explore`**.
- Дефолт для `ailit agent run`: зависит от профиля (см. §6).

## 3. Архитектура решения

### 3.1 ModeClassifier (LLM)

Для каждого пользовательского сообщения:

1) собрать **структурированную историю** последних N решений:
   - `user_intent_short`
   - `mode_chosen`
   - `decided_by` (`llm|user|policy`)
   - `overridden` (bool)
   - `ts`
2) сделать отдельный LLM‑вызов “classifier” со **строгим JSON output**:
   - `mode`: enum (`read|read_plan|explore|edit|not_sure`)
   - `confidence`: float 0..1
   - `reason`: short string
3) записать решение в KB (kind: `mode_decision`, scope=`run` или `project`).

#### 3.1.1 JSON Schema ответа классификатора (P5‑0.1)

Контракт ответа модели — **один** JSON‑объект (без markdown fence, без текста вокруг):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["mode", "confidence", "reason"],
  "properties": {
    "mode": {
      "type": "string",
      "enum": ["read", "read_plan", "explore", "edit", "not_sure"]
    },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "reason": { "type": "string", "minLength": 1 }
  }
}
```

Парсер в рантайме допускает извлечение первого `{...}` из ответа и нормализацию `confidence` к диапазону 0..1; при полной неудаче разбора применяется безопасный режим **`read`** (событие `mode.classified`, `reason=classifier_parse_failed`).

**Важно:** классификатор — это не “security gate” сам по себе. Он выбирает режим,
а ниже работают tool‑permissions и allowlist/ask.

### 3.2 ModeEnforcer (единая точка)

Единая точка, которая:
- мержит реестр tools / PermissionEngine в зависимости от режима,
- эмитит события `mode.classified`, `mode.user_choice`, `mode.enforced`,
- делает “choke point” смены режима (аналог Claude Code).

### 3.3 UI ask‑gate для not_sure

Если классификатор вернул `not_sure`, UI:
- показывает выбор режима;
- блокирует основной вызов модели до выбора;
- выбор пишется как `mode.user_choice` и добавляется в историю.

## 4. План работ (этапы → задачи → критерии приёмки)

### Этап P5-0: Research и фиксация контрактов

- **Задача P5-0.1 — контракты событий и JSON**
  - **Описание:** зафиксировать события и JSON контракт классификатора.
  - **Критерии приёмки:**
    - есть описание schema JSON для ответа классификатора (enum + strict);
    - в unified summary есть срез `subsystems.perm_mode` (или экв.).

### Этап P5-1: LLM‑классификатор режима

- **Задача P5-1.1 — prompt классификатора**
  - **Описание:** отдельный prompt + строгий JSON output.
  - **Критерии приёмки:**
    - classifier не имеет доступа к tool‑calling;
    - classifier видит только intent + структурированную историю N.

- **Задача P5-1.2 — KB‑память решений**
  - **Описание:** записывать `mode_decision` и читать последние N перед классификацией.
  - **Критерии приёмки:**
    - решения не содержат сырой чат;
    - решения привязаны к repo namespace (`repo_uri/path + branch`) и доступны между запусками.

### Этап P5-2: Enforcement (режим → доступные tools)

- **Задача P5-2.1 — tool registry per mode**
  - **Описание:** `read/read_plan/explore/edit` формируют разные наборы tools.
  - **Критерии приёмки:**
    - в `read` невозможны `run_shell` и `write_file`;
    - в `read_plan` можно писать только неисполняемые файлы (см. P5-2.2);
    - в `explore` shell allowlist без вопросов, всё остальное shell → ask;
    - в `edit` write/shell возможны по политике, но protected paths остаются.

- **Задача P5-2.2 — верификатор “неисполняемых файлов” для read_plan**
  - **Описание:** разрешить создание только безопасных расширений (например `.md`, `.txt`,
    `.json`, `.yaml`, `.yml`) и/или путей `docs/`, `.ailit/plan/`.
  - **Критерии приёмки:**
    - попытка записать `.py`, `.sh`, `Makefile`, `Dockerfile` в read_plan → ask/deny.

### Этап P5-3: UI/UX

- **Задача P5-3.1 — not_sure gate**
  - **Описание:** UI диалог выбора режима + опция “запомнить для проекта” (always).
  - **Критерии приёмки:**
    - при not_sure основной ответ модели не вызывается;
    - выбор пользователя сохраняется и влияет на следующие запросы.

### Этап P5-4: `ailit agent` и мультиагентный рантайм

- **Задача P5-4.1 — режим для `ailit agent run`**
  - **Описание:** CLI/engine должен иметь явный флаг режима или policy.
  - **Критерии приёмки:**
    - workflow может задать mode upfront (без классификатора);
    - mode логируется в события.

- **Задача P5-4.2 — мультиагент: bypass слоя классификации**
  - **Описание:** флаг “multi-agent mode” отключает LLM‑классификатор и требует,
    чтобы orchestrator явно задавал mode для каждого worker.
  - **Критерии приёмки:**
    - worker не вызывает classifier (нет дополнительных модельных запросов);
    - orchestrator передаёт mode в task spec/контекст.

### Этап P5-5: Тесты, регрессии, критерии завершения

- **Unit‑тесты:**
  - классификатор: строгий JSON parse + not_sure;
  - enforcement: запрещённые tool calls в `read`/`read_plan`;
  - allowlist shell: `git status` allow без ask, `pip install` → ask.
- **E2E:**
  - сценарий “покажи точки входа” не вызывает `write_file`;
  - сценарий “сгенерируй docs/plan.md” в read_plan пишет файл без shell.

**Критерии завершения perm‑5:**
- пользователь в `ailit chat` без ручного переключения не получает “внезапный write_file”;
- not_sure всегда приводит к явному UI‑выбору;
- режим и решения видны в unified summary / UI панели.

## 5. Коммиты (правило разбиения)

После каждого логического блока — отдельный коммит:
- `P5-1`: classifier prompt + strict output + unit
- `P5-2`: enforcement per mode + allowlist + unit
- `P5-3`: UI gate + telemetry + e2e
- `P5-4`: agent/multi-agent bypass + tests

