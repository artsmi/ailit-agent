# Target-doc pipeline (`start-research` → роль `100`)

Человекочитаемая карта: **кто за что отвечает**, **в каком порядке вызываются агенты** и **где лежит результат**. Нормативные детали gates, JSON и ownership — в [`100_target_doc_orchestrator.md`](./100_target_doc_orchestrator.md) и в [`.cursor/rules/start-research.mdc`](../rules/start-research.mdc); этот файл — сжатая навигация для восстановления контекста и правок промптов.

---

## 1. Нумерация `100+` и состав пайплайна

- Target-doc роли имеют префикс **`100`–`108`** (отдельно от feature/fix `01`–`13`), чтобы не пересекаться с legacy-нумерацией. Норматив: [`100_target_doc_orchestrator.md`](./100_target_doc_orchestrator.md) и [`start-research.mdc`](../rules/start-research.mdc).
- В **истории git** target-doc пайплайн эволюционировал (в т.ч. пост-verifier стадии плана и human reader). Если в старых заметках встречаются id `14`/`18`–`25`, смотри таблицу в разделе 6 ниже.
- Старые промпты **`15`–`17`** (research-plan без target-doc) **удалены** из репозитория; `research_waves` мапятся только на **`101`** / **`102`** по решению **`103`**.

---

## 2. Последовательность запуска (кто после кого)

Управляет только **`100_target_doc_orchestrator`** (текущий чат по `start-research.mdc`). Он **не** исполняет research и **не** пишет draft сам — только вызывает Subagents по контракту.

Типичный happy-path:

1. **`100`** — intake: артефакты под `context/artifacts/target_doc/`, `original_user_request.md`, при необходимости `preflight.md`, ведение `status.md` / ledger / validation.
2. **`103_target_doc_synthesizer`** — первый содержательный шаг и каждый «barrier» после research: synthesis, решение нужен ли research, волны jobs, вопросы пользователю, `ready_for_author`.
3. Цикл **research (по решению `103`)**:
   - **`102_current_repo_researcher`** — для jobs с `kind=current_repo` (и follow-up того же типа).
   - **`101_donor_researcher`** — для jobs с `kind=donor_repo`.
   - После выполнения волны — снова **`103`** с путями к отчётам.
4. **`104_target_doc_author`** — когда `103` выставил `ready_for_author=true` (возможны несколько проходов по `authoring_plan` из JSON `103`).
5. **`105_target_doc_verifier`** — один раз на полный draft после всех проходов `104` цикла.
6. После **`105` approved** строго по цепочке:
   - **`106_implementation_plan_author`** — файл под `plan/`;
   - **`107_implementation_plan_reviewer`** — `plan_review_latest.json` + JSON для `100`;
   - **`108_target_doc_reader_reviewer`** — human approval package (`human_review_packet.md`, coverage, matrix, gaps, `reader_review.md`, `start_feature_handoff.md` и т.д. по промпту `108`).
7. **`100`** — запрос явного user OK (whitelist из `project-human-communication.mdc`), затем публикация канона в `context/algorithms/**`, обновление индексов, completion gate, auto commit (без push), если это предусмотрено правилами `100`.

**Параллельность внутри research:** если в `research_waves` у волны `parallel=true`, **`100`** запускает все jobs этой волны **одной пачкой** параллельных Subagent calls; при `parallel=false` — **строго по порядку** `jobs[]`. См. раздел 3.

---

## 3. Кто планирует research и сколько агентов запускается

| Вопрос | Ответ |
|--------|--------|
| Нужен ли research, какие темы, donor vs current repo | Решает **`103_target_doc_synthesizer`** (содержательный owner). |
| Сколько волн, состав jobs, `parallel` / порядок / barrier | Задаёт **`103`** в JSON (`research_waves`, поля вроде `parallel`, `jobs[]`). |
| Фактический запуск Subagents, соблюдение порядка и параллелизма | Исполняет **`100`**: маппинг `kind` → роль `102` или `101`, barrier, повторный вызов `103`. |
| Сколько процессов параллельно | Столько **jobs в одной wave с `parallel=true`**, сколько перечислил `103`; **`100` не увеличивает и не уменьшает** счёт по своей инициативе. |
| Legacy `research_jobs` без `research_waves` | **`100`** трактует как одну последовательную волну и фиксирует fallback в `status.md` — **не** придумывает parallelism сам. |

Итого: **планирование исследований** (что и в каком объёме) — **`103`**; **оркестрация запусков** — **`100`**.

---

## 4. Кто формирует «документацию»

Здесь разные слои документов:

| Артефакт / слой | Кто пишет (owner) |
|-----------------|-------------------|
| Отчёты «что в коде сейчас» — `context/artifacts/target_doc/current_state/*.md` | **`102`** |
| Отчёты по donor — `context/artifacts/target_doc/donor/*.md` | **`101`** |
| Сводка, решения, волны, готовность к авторингу — `synthesis.md` (и машинный JSON от `103`) | **`103`** |
| Черновик/целевой алгоритм — `target_algorithm_draft.md` | **`104`** |
| Вердикт верификатора — `verification.md` | **`105`** |
| Пакет для человека перед approval | **`108`** (`human_review_packet.md`, `source_request_coverage.md`, …) |
| Запись user approval | **`100`** (`approval.md` и т.п. по правилам `100`) |
| Опубликованный канон в `context/algorithms/**` после OK | Выполняет **`100`** по completion gate (текст обычно выводится из утверждённого draft/пакета; править канон вслепую без gate запрещено правилами `100`). |

**`106` и `107`** не заменяют target-doc: они относятся к **плану внедрения** под `plan/` (см. раздел 5).

---

## 5. Кто формирует финальный план в папке `plan/`

- **Автор файла** markdown под `plan/<NN>-<slug>.md` (путь **`implementation_plan_path`** из handoff / JSON **`103`**) — **`106_implementation_plan_author`**.
- **Ревью** этого файла и запись **`context/artifacts/target_doc/plan_review_latest.json`** — **`107_implementation_plan_reviewer`**. При `rework_required` оркестратор снова вызывает **`106`**, затем **`107`** — по правилам `100`.
- Это **не** тот же артефакт, что «план фичи» от **`06_planner`** в основном feature-pipeline: здесь план — **мост к `start-feature` / `start-fix`** после утверждённого target-doc, с трассировкой к канону и ограничением scope.

---

## 6. Карта агентов с краткой аннотацией

| ID | Файл промпта | Subagent type / примечание | Аннотация (зачем человеку) |
|----|----------------|----------------------------|----------------------------|
| **100** | [`100_target_doc_orchestrator.md`](./100_target_doc_orchestrator.md) | оркестратор в текущем чате | Ведёт артефакты, вызывает Subagents, не делает research и не пишет draft за других; запрашивает approval и закрывает workflow. |
| **101** | [`101_donor_researcher.md`](./101_donor_researcher.md) | `donor_researcher` | Один donor repo / scope: факты, ссылки на код, переносимые паттерны — вход для `103` под оркестрацией `100`. |
| **102** | [`102_current_repo_researcher.md`](./102_current_repo_researcher.md) | `current_repo_researcher` | Текущий репозиторий по job от `103`: «что есть сейчас», без выбора целевого дизайна. |
| **103** | [`103_target_doc_synthesizer.md`](./103_target_doc_synthesizer.md) | `target_doc_synthesizer` | Единственный содержательный «мозг» этапа: synthesis, research waves, вопросы пользователю, `ready_for_author`, путь плана и пр. |
| **104** | [`104_target_doc_author.md`](./104_target_doc_author.md) | `target_doc_author` | Человекочитаемый целевой алгоритм + контракт + примеры + критерии — `target_algorithm_draft.md`. |
| **105** | [`105_target_doc_verifier.md`](./105_target_doc_verifier.md) | `target_doc_verifier` | Проверка полноты и готовности к approval; `verification.md`, rework-инструкции для `100`. |
| **106** | [`106_implementation_plan_author.md`](./106_implementation_plan_author.md) | `target_doc_verifier` + prompt `106_…` | Один файл плана в `plan/` для нарезки внедрения после verifier OK. |
| **107** | [`107_implementation_plan_reviewer.md`](./107_implementation_plan_reviewer.md) | `target_doc_verifier` + prompt `107_…` | Ревью плана `106`, JSON в `plan_review_latest.json`. |
| **108** | [`108_target_doc_reader_reviewer.md`](./108_target_doc_reader_reviewer.md) | `target_doc_verifier` + prompt `108_…` | «Глазами человека»: approval package и ясность, можно ли утверждать. |

**Памятка по типам Subagent:** для **`106`–`108`** в таблице `100` указан базовый тип `target_doc_verifier` с **разными** файлами промпта — это важно при настройке Task tool / Cursor.

---

## 7. Связь с агентами вне этого пайплайна

- **`01_orchestrator`** — feature/fix; **не** ведёт `start-research`.
- **`06_planner`**, **`07_plan_reviewer`** — план работ по фиче в `plan/*` в основном контуре; отличать от **`106`/`107`** (план внедрения после target-doc).
- **`10_researcher`** — точечные исследования по поручению `01`; **не** заменяет `101`/`102` в `research_waves` target-doc.

---

## 8. Что править при «восстановлении описания агентов»

1. Сверить каждую роль с колонкой Subagent в **`100`** § *Subagent Invocation Contract*.
2. Синхронизировать **`start-research.mdc`** (краткий route) с полным текстом **`100`** при расхождениях.
3. В промптах **`101`/`102`** убрать или обновить устаревшие фразы про **`01`**/**`15`**, если они мешают читателю (фактический consumer в target-doc — **`103`**).

---

*Документ создан как опора для человека; при изменении контракта pipeline обновляйте этот файл вместе с `100` и `start-research.mdc`.*
