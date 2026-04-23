# Workflow: memory-4 (гарантированная память + анти‑loop как у доноров)

Документ задаёт **четвёртую итерацию** памяти в `ailit`: сделать слой памяти
**автоматическим на уровне runtime** (без знания пользователем `kb_*`),
добавить **ограничители длинных циклов** (как у доноров), и расширить
наблюдаемость/оценку эффективности.

Канон процесса разработки репозитория: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

## 0. Контекст и проблема (на примере `speexworkdir`)

Наблюдаемая проблема в `ailit chat`:

- Пользователь просит «изучи репозиторий и создай память».
- Модель уходит в длинный инструментальный цикл: много `read_file`/`run_shell`,
  иногда с таймаутами и отменой, а **инструменты KB** (`kb_search`, `kb_write_fact`,
  `kb_fetch`, `kb_promote`) **не вызываются**.
- Итог: **нет событий `memory.access`**, `memory_access_total=0`, а значит
  «долгая память» (KB) не создаётся и повторный запуск снова тратит токены.

Цель M4: runtime должен **гарантировать** работу слоёв памяти и ограничителей
цикла **без** того, чтобы пользователь понимал внутренние имена инструментов.

## 1. Доноры (ориентиры, без копипаста)

### 1.1 OpenCode: жёсткий cap итераций agent loop

OpenCode описывает конфиг, который ограничивает количество «агентных шагов»
перед форсированием text-only:

```1260:1269:/home/artem/reps/opencode/packages/sdk/js/src/v2/gen/types.gen.ts
  /**
   * Maximum number of agentic iterations before forcing text-only response
   */
  steps?: number
```

### 1.2 OpenCode: отдельная ось permission для `doom_loop`

В типах permissions выделено действие `doom_loop` как отдельное правило:

```1220:1227:/home/artem/reps/opencode/packages/sdk/js/src/v2/gen/types.gen.ts
      lsp?: PermissionRuleConfig
      doom_loop?: PermissionActionConfig
      skill?: PermissionRuleConfig
```

### 1.3 Claude Code: post-compact restore с бюджетом и skip уже видимого

Ориентир на «восстановление недавно прочитанного после компакта» с ограничением
по **числу файлов** и **токен‑бюджету**, плюс skip, если content уже в tail:

```1398:1464:/home/artem/reps/claude-code/services/compact/compact.ts
Creates attachment messages for recently accessed files to restore them after compaction.
Files are selected based on recency, but constrained by both file count and token budget limits.
...
Files already present as Read tool results in preservedMessages are skipped ...
```

### 1.4 Claude Code: budget на tool results + persistence на диск вместо «тащи всё в промпт»

Ориентир на «пустые tool results ломают цикл» и на persistence больших результатов
на диск (вместо увеличения контекста):

```267:334:/home/artem/reps/claude-code/utils/toolResultStorage.ts
Handle large tool results by persisting to disk instead of truncating.
...
Inject a short marker so the model always has something to react to.
...
Use tool-specific threshold ... fall back to global limit
...
Persist the entire content as a unit
```

### 1.5 Claude Code: permission/risk классификация (вместо «просто allow/deny»)

Ориентир на модели контроля действий и риска:

```343:360:/home/artem/reps/claude-code/README.md
Tools are registered ... filtered by ... permission deny rules.
...
permission system ... far more sophisticated than "allow/deny":
Permission Modes ...
Risk Classification ... LOW/MEDIUM/HIGH ...
Protected Files ...
Path Traversal Prevention ...
```

## 2. Текущее состояние `ailit` (опорные точки реализации)

### 2.1 Compaction и post-compact restore в ailit

В `SessionRunner._prepare_context` compaction = оставить хвост и усечь tool results,
а затем (опционально) докинуть **восстановленные фрагменты** `read_file` и эмитнуть
`compaction.restore_files`:

```360:399:/home/artem/reps/ailit-agent/tools/agent_core/session/loop.py
        compacted = compact_messages(...)
        if (settings.post_compact_restore_enabled and len(messages) > settings.compaction_tail_messages):
            restore_msg, plan = self._recent_reads.build_restore_message(...)
            if restore_msg is not None and plan.restored:
                compacted.append(restore_msg)
                self._emit(events, "compaction.restore_files", {"restored_files": len(plan.restored), ...})
```

Compaction по факту — простой хвост + усечение длинных TOOL:

```1:32:/home/artem/reps/ailit-agent/tools/agent_core/session/compaction.py
def compact_messages(...):
    """Оставить хвост из tail_max сообщений; усечь длинные TOOL content."""
```

### 2.2 События памяти (`memory.access`, `memory.promotion.*`)

Эмит `memory.access` идёт **только** для инструментов, имя которых начинается с `kb_`:

```245:287:/home/artem/reps/ailit-agent/tools/agent_core/session/loop.py
def _emit_memory_access(...):
    name = str(tool_name or "")
    if not name.startswith("kb_"):
        return
    ...
    self._emit(..., "memory.access", {"tool": name, ...})
```

### 2.3 Панель «Память (M3)» и unified summary

В `ailit chat` уже есть панель и метрики `memory_access_total/by_tool` и эвристика,
но на примере `speexworkdir` видно, что при отсутствии `kb_*` вызовов она даёт ноль,
что правильно, но не решает продуктовую задачу «память должна работать всегда».

## 3. Принципы M4 (канон)

1. **Пользователь не обязан знать `kb_*`.** Любой режим «изучи проект и запомни»
   должен вызывать память автоматически на уровне runtime.
2. **KB write не в конце сессии.** Запись должна происходить **инкрементально**,
   чтобы `session.cancelled` не обнулял прогресс.
3. **Ограничение agentic loop как у доноров.** Нужен cap шагов и детектор doom-loop,
   не только `max_turns`.
4. **Наблюдаемость — единый источник.** Всё должно отражаться в JSONL и
   `build_session_summary` (как contract).

## 4. План работ (этапы → задачи → критерии приёмки)

### Этап M4-0: Research и фиксация требований

**Цель:** формализовать, что значит «память всегда работает», какие режимы UI/CLI нужны,
и какие ограничения по privacy/PII.

- **Задача M4-0.1 — терминология и режимы**
  - **Описание:** зафиксировать режимы «исследование репо», «вопрос‑ответ», «редактирование»
    и правила включения памяти (retrieval + write).
  - **Критерии приёмки:**
    - в этом документе есть таблица режимов и expected runtime‑политик памяти;
    - есть список «не писать в KB» (секреты/PII/сырой чат).

- **Задача M4-0.2 — baseline сценарии e2e (из реальных логов)**
  - **Описание:** выбрать 2–3 сценария (например `speexworkdir`) и зафиксировать
    ожидаемые метрики (`memory.access > 0`, `kb_write_fact` count, отсутствие long `run_shell`).
  - **Критерии приёмки:**
    - есть ссылки на конкретные `ailit-chat-*.log` (путь) и ожидаемые поля summary.

### Этап M4-1: Автоматический слой памяти (retrieval + write) на уровне runtime

**Цель:** при задачах «изучи и запомни» память работает даже если LLM не вызывает `kb_*`.

- **Задача M4-1.0 — Определить «когда включать авто‑память»**
  - **Описание:** реализовать *продуктовый* переключатель/режим (а не промпт):
    - UI toggle «Авто‑память: on/off»;
    - или настройка проекта (`project.yaml`);
    - или явная команда (например `@memory on`).
  - **Критерии приёмки:**
    - режим отражён в JSONL (`memory.policy.enabled=true/false`) и unified summary;
    - пользователь может выключить авто‑write.

- **Задача M4-1.1 — MemoryPolicy/Orchestrator в session loop**
  - **Описание:** добавить runtime‑компонент, который после `model.response` и/или после
    `tool.call_finished` принимает решение:
    - какие `kb_search` сделать (retrieval, чтобы уменьшить повторные `read_file`);
    - какие факты записать `kb_write_fact` (инкрементально, батчами).
  - **Критерии приёмки:**
    - при сценарии «изучи репо и запомни» в логе появляются `memory.access` для `kb_*`
      даже если модель не вызвала их напрямую;
    - запись в KB происходит **в процессе** (до конца сессии).
  - **Проверки:**
    - `PYTHONPATH=tools python3 -m pytest -q` (юнит);
    - новый e2e‑сценарий (см. M4-4) подтверждает рост `memory.access`.

- **Задача M4-1.2 — Авто‑summaries → KB write (anti‑raw‑chat)**
  - **Описание:** вместо сырого чата писать нормализованные факты: `title/summary/body`,
    provenance (repo, path, commit/mtime), `scope/namespace`.
  - **Критерии приёмки:**
    - ни один авто‑write не пишет полный диалог;
    - соблюдаются ограничения governance (`draft` only, promotion отдельно).

- **Задача M4-1.3 — Интеграция с permission/approval**
  - **Описание:** авто‑write должен быть либо безопасен по умолчанию, либо требовать approve
    в «опасных» режимах.
  - **Критерии приёмки:**
    - авто‑write не может silently писать в «org» scope без политики;
    - есть трасса событий (diag) о том, почему write выполнен/пропущен.

### Этап M4-2: Анти‑loop ограничения (как у доноров)

**Цель:** остановить «длинный цикл» инструментов без прогресса и без ручного stop.

- **Задача M4-2.1 — `agent_steps` cap (аналог OpenCode `steps`)**
  - **Описание:** ограничить число подряд (или суммарно) итераций вида
    `model.response` → `tool_calls` → `tool_results` → `model.request` без «финализации».
  - **Критерии приёмки:**
    - при превышении cap сессия завершает ход с понятной причиной и просит пользователя
      уточнить/подтвердить следующий шаг (или форсирует text-only ответ).
  - **Проверки:**
    - unit‑тест на срабатывание cap;
    - e2e‑тест на реальном сценарии «скан репо».

- **Задача M4-2.2 — doom-loop detector (повторы без прогресса)**
  - **Описание:** детектор повторов tool invocations (same tool+args / одинаковые path‑range)
    и/или «циклы каталогов», отдельная политика как в OpenCode `doom_loop`.
  - **Критерии приёмки:**
    - повтор одного и того же `read_file(path,offset,limit)` после restore‑hint приводит
      к предупреждению/deny/переформулировке, а не к бесконечной цепочке.

- **Задача M4-2.3 — `run_shell` guardrails**
  - **Описание:** запрет/ограничение интерактивных лаунчеров, долгих процессов
    и команд‑инсталляторов в режиме «обзор репо».
  - **Критерии приёмки:**
    - сценарий `speexworkdir` не запускает проект‑лаунчер по умолчанию;
    - если модель хочет — должна получить approve или переключить режим.

### Этап M4-3: Наблюдаемость и UI/CLI отчёты «как продукт»

**Цель:** у пользователя всегда есть ответ «как сработала память» без ручного анализа.

- **Задача M4-3.1 — единый “Memory FullReport”**
  - **Описание:** расширить unified summary: статистика по памяти (retrieval/write),
    loop‑guards (сколько раз сработали caps), эффективность (эвристика) + причины.
  - **Критерии приёмки:**
    - `ailit session usage summary --json` содержит блок `memory_full_report` (или экв.)
      с breakdown по инструментам и по policy‑решениям.

- **Задача M4-3.2 — UI: «Память» как главный экран**
  - **Описание:** в `ailit chat` блок памяти должен объяснять:
    - какие слои сработали (FS/pager/compaction vs KB);
    - что было записано/не записано и почему;
    - сколько токенов сэкономили.
  - **Критерии приёмки:**
    - при `memory_access_total=0` UI показывает **диагноз** (какой policy не включился),
      а не только «пока нет событий».

### Этап M4-4: Evaluation suite и e2e регрессии (автоматизировано)

**Цель:** не ломать память/loop‑guards в будущем.

- **Задача M4-4.1 — e2e сценарии на mock provider**
  - **Описание:** добавить e2e тесты, которые:
    - запускают короткий «обзор репо»;
    - проверяют, что KB‑события появились;
    - проверяют, что doom‑loop/cap срабатывает и завершается корректно.
  - **Критерии приёмки:**
    - тесты выполняются командой `PYTHONPATH=tools python3 -m pytest -q`;
    - есть отдельная команда для e2e, если репо разделяет `tests/e2e/`.
    - e2e используют `config/test.local.yaml` (через env или явный флаг), и запускаются
      через `scripts/test-e2e` (e2e-only) и `scripts/start-e2e` (полный прогон).

- **Задача M4-4.2 — offline regression на JSONL**
  - **Описание:** фиксировать expected поля summary на 1–2 эталонных логах и сравнивать.
  - **Критерии приёмки:**
    - при изменении runtime отчёт меняется предсказуемо и покрыт тестом.

### Этап M4-5: Governance/TTL/Review (перенос deferred из M3)

**Цель:** закрыть хвосты governance и «acceleration layer».

- **Задача M4-5.1 — TTL/архив для `deprecated`**
  - **Описание:** policy «как жить фактам во времени», отдельная утилита/команда.
  - **Критерии приёмки:** есть механизм пометки/очистки без потери provenance.

- **Задача M4-5.2 — reviewer signature / audit**
  - **Описание:** расширить provenance, чтобы фиксировать, кто и как подтвердил факт.
  - **Критерии приёмки:** промоушен трассируется и объясним в отчёте.

- **Задача M4-5.3 — vector/BM25 как acceleration (rebuildable)**
  - **Описание:** если добавляется индекс — только как rebuildable слой поверх KB,
    с явной командой rebuild.
  - **Критерии приёмки:** индекс не объявлен SoT, при рассинхроне побеждает канон.

## 5. Вопросы к пользователю (нужно для финализации постановки)

Ответы зафиксированы (2026‑04‑23):

1. **Авто‑write в KB:** **всегда включено** (runtime‑гарантия, не промпт).
2. **Namespace/идентификация репозитория:** нужен **путь + URI** (например `git@github.com:introlab/odas.git`),
   плюс учитывать версии по branch/commit. Требование: у разных пользователей разные пути, но память одна.
3. **Doom-loop политика:** нужно выбрать A/B/C (см. §6 ниже).
4. **run_shell guardrails:** пользователь предпочитает «разрешить всё по умолчанию»;
   ограничители должны быть минимальными и ориентированы на safety/UX (таймауты, интерактив, повторы).
5. **Е2Е:** e2e должны работать с `config/test.local.yaml` и запускаться через
   `scripts/start-e2e` или `scripts/test-e2e`. Нужно уточнить, что именно входит в каждый скрипт.

## 6. Уточнение: варианты политики doom-loop (A/B/C) и где что похоже у доноров

**A — форсировать text-only ответ (жёсткий cap):**

- Похоже на OpenCode: `AgentConfig.steps` = «после N агентных итераций форсировать text-only»
  (см. ссылку в §1.1).
- Плюсы: предсказуемо, останавливает runaway tool loop.
- Минусы: модель может не успеть «дойти до результата» без внешнего вмешательства.

**B — попросить уточнение у пользователя (интерактивный стоп):**

- Похоже на permission-паттерн Claude Code: система объясняет риск и просит approve/уточнение,
  вместо того чтобы молча продолжать (см. §1.5).
- Плюсы: меньше неожиданных остановок; пользователь контролирует направление.
- Минусы: требует внимания пользователя; хуже для «автопилота».

**C — автоматически сменить стратегию (например: “переключиться на KB/summary-mode”):**

- Это ближе к «policy/skill» подходу: вместо продолжения read/scan переходить к retrieval+write,
  делать краткий план и сохранить факты.
- Плюсы: сохраняет автономность; меньше ручных стопов.
- Минусы: сложнее верифицировать; требует хороших эвристик и трассировки причин в отчёте.

Рекомендуемый базовый режим для M4: A как *hard cap* (anti‑runaway) + C как *auto‑fallback*,
а B — как UX‑вариант в UI (вопрос пользователю).

## 7. Версионность и «единая память при разных путях»: предложенный подход

Цель: запись в KB должна адресоваться **не** только к `work_root` (локальному пути), а к
устойчивому **repo_id**, с привязкой к версии, но без взрыва дубликатов.

Предложение (канон ключей):

- **`repo_uri`**: нормализованный remote (ssh/https → canonical), напр. `github.com/introlab/odas`.
- **`repo_path`**: локальный путь (для навигации/trace), но не как primary key.
- **`ref`**:
  - `branch` (предпочтение текущей ветки),
  - `commit` (точная привязка для файлов/фактов, когда доступно),
  - fallback: `default_branch` или `unknown`.

Правило retrieval:

1) сначала искать факты с совпадающим `repo_uri` и текущим `branch`;  
2) если мало — расширять на default branch;  
3) если факт привязан к `commit`, считать его «точным» и выше по рангу;  
4) при расхождении фактов между ветками — использовать governance (`supersedes_id`, `valid_to`)
   и provenance (файл+commit), не плодить копии без нужды.

Это обеспечивает «одна память» при разных путях и допускает умеренную ветвистость без дублей.

### 7.1 Критерии приёмки: branch/commit fallback и объяснимость

**Сценарий:** пользователь был на `develop`, затем создал ветку `new_feature` и запускает
задачу «изучи репозиторий и запомни» на `new_feature`.

- **AC-7.1.1 (branch-first)**: поиск памяти на `new_feature` сначала использует записи
  `repo_uri + branch=new_feature`, и только при недостатке результатов включает fallback.
- **AC-7.1.2 (default-branch fallback)**: если в `new_feature` мало/нет фактов, retrieval
  расширяется на `repo_uri + branch=default_branch` (например `develop` или `main`).
- **AC-7.1.3 (как определяется default_branch)**: runtime определяет `default_branch`
  через `origin/HEAD` (предпочтительно) или через локальные эвристики (`main/master/develop`),
  и логирует выбранный источник (`origin_head`, `heuristic`, `unknown`).
- **AC-7.1.4 (commit overrides)**: записи, привязанные к `commit`, имеют более высокий
  приоритет при совпадении `repo_uri` (и если commit reachable для текущего контекста),
  чем общие факты ветки.
- **AC-7.1.5 (explainability в отчёте)**: unified summary и UI показывают, откуда пришёл
  каждый использованный факт памяти: `repo_uri`, `branch`, `default_branch_used` (bool),
  `commit` (если есть), и `reason` (branch-first / fallback / commit-exact).

