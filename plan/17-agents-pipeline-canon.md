# План внедрения 17: tooling и управление промптами под канон agents pipeline

**Идентификатор процесса:** `agents-pipeline-canon-17`  
**Файл:** `plan/17-agents-pipeline-canon.md`  
**Статус:** черновик под ревью **`107_implementation_plan_reviewer`**; исполнение слайсов — отдельными `start-feature` / `start-fix` после человеческого OK канона и этого плана.

**Канон SoT (поведение и термины):** [`context/algorithms/agents/INDEX.md`](../context/algorithms/agents/INDEX.md) и связанные файлы пакета: [`glossary.md`](../context/algorithms/agents/glossary.md), [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md), [`roles-and-artifacts.md`](../context/algorithms/agents/roles-and-artifacts.md), [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md), [`donor-comparison.md`](../context/algorithms/agents/donor-comparison.md), [`killer-features.md`](../context/algorithms/agents/killer-features.md), [`user-story-handoff.md`](../context/algorithms/agents/user-story-handoff.md), [`anti-patterns.md`](../context/algorithms/agents/anti-patterns.md).

**Входные артефакты pipeline (трассировка, не дублирование канона):** `context/artifacts/target_doc/original_user_request.md`, `synthesis.md`, `verification.md` (решение **`105`:** `approved`), `target_algorithm_draft.md`.

---

## 0. Зачем выполнять этот план: что изменится по сравнению с текущим состоянием

**Сейчас (до закрытия остальных слайсов плана 17).** Канон в [`context/algorithms/agents/`](../context/algorithms/agents/INDEX.md) уже фиксирует целевое поведение. Слайс **G17.3** по **`10_researcher`** в **`.cursor/`** **выполнен в этом репозитории**: файл роли удалён, в карте моделей и в промптах **01** / **00** диапазон ролей под оркестратором **01** — **02–09** и **11–13**; исследование для алгоритмов в каноне — **только** **`start-research`** (**100**, **101–108**). Остаётся **разрыв по другим пунктам плана**: точки входа **start-feature** / **start-fix** не везде явно разводят **`plan/`** (корень репозитория) и **план артефактов 06** — из‑за этого одна и та же формулировка «план» читается по-разному. Шаблон **USER-story** в правилах входа может отсутствовать или дублироваться в чатах. Автоматического CI на «не вызывай Subagent из роли **02–09**» **нет** — риск регрессии формулировок остаётся на совести ревью.

**После выполнения оставшихся выбранных слайсов (ожидаемый эффект для команды).** Выравнивание по **`10_researcher`** **сохранено**; дополнительно промпты и правила **дотягиваются до канона** там, где ещё есть зазор: в **start-feature** / **start-fix** — короткий, видимый блок «**план репозитория** ≠ **план 06**» со ссылкой на [`glossary.md`](../context/algorithms/agents/glossary.md); в одном из правил — **копируемый минимум полей USER-story**, согласованный с [`user-story-handoff.md`](../context/algorithms/agents/user-story-handoff.md). Для снижения регрессии **G1** зафиксирован **rg**-шаг или скрипт и whitelist шумных совпадений.

**Чего план намеренно не делает:** не вводит новый оркестратор, не меняет продуктовый Python-код без отдельной постановки, не заменяет человеческое ревью и не обещает «полный парсер Markdown в CI».

---

## 1. Цель и границы

### 1.1 Цель

Зафиксировать **узкие** слайсы внедрения для выравнивания **репозиторных** правил и промптов с утверждаемым пакетом канона «Agents pipeline»: устранение документированных расхождений, шаблон USER-story, опциональные статические проверки — так, чтобы последующий `start-feature` не превращался в переписывание всего мультиагентного runtime.

### 1.2 In scope

- Правки **текстов** под `.cursor/` (промпты ролей, правила `start-*`, карта моделей), согласованные с каноном.
- Разводка **`plan/`** (корень репозитория) vs **план артефактов `06`** — явные отсылки в точках входа, если сейчас недостаточно заметны ([`glossary.md`](../context/algorithms/agents/glossary.md)).
- **Выполнено (G17.3):** удаление **`10_researcher`** из [`project-agent-models.mdc`](../.cursor/rules/project/project-agent-models.mdc), из списков ролей в **`readme100.md`**, **`00_agent_development.md`**, выравнивание диапазона ролей в **`01_orchestrator.md`**, удаление файла **`.cursor/agents/10_researcher.md`**; согласование с [`glossary.md`](../context/algorithms/agents/glossary.md) и [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md). Перед коммитом следующих слайсов — повторная проверка grep по **`.cursor/`** на **`10_researcher`** (ожидается **0**).
- Лёгкая **rg/flake8**-дисциплина на затронутых файлах и опциональный **rg-gate** по формулировкам «не запускать субагентов» в **02–09** (зазор **G1** в [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md)).
- Минимальная схема полей **USER-story** и место шаблона ([`user-story-handoff.md`](../context/algorithms/agents/user-story-handoff.md)).

### 1.3 Out of scope

- Реализация нового оркестратора, нового JSON envelope для всех ролей, общего event journal.
- Обязательное введение **отдельной роли исследователя у `01`** вместо контура **`start-research`**.
- Массовый рефакторинг всех файлов `.cursor/agents/*.md` сверх перечня **implementation anchors** слайса.
- Копирование текстов/кода доноров (запрет канона, [`anti-patterns.md`](../context/algorithms/agents/anti-patterns.md)).

### 1.4 Явные запреты для исполнителей слайсов

| Запрет | Норматив |
|--------|----------|
| Смешивать смысл **`plan/*.md`** и выхода **`06`** | [`glossary.md`](../context/algorithms/agents/glossary.md), [`anti-patterns.md`](../context/algorithms/agents/anti-patterns.md) |
| Трактовать успех **11** как **`completion`** или замену **09** | [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md), [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md) |
| Подменять контур **100–108** ручной «исследовательской» сессией **01** | [`glossary.md`](../context/algorithms/agents/glossary.md), [`user-story-handoff.md`](../context/algorithms/agents/user-story-handoff.md) |
| Расширять scope слайса до «переписать весь пайплайн» | Этот файл, §1.3 |

---

## 2. Аудит / текущая картина

Опора на **`verification.md`** (`105`, `approved`) и факты **`synthesis.md`**; **новый** product research в рамках плана **не** требуется.

| ID | Находка | Источник истины в репозитории | Связь с каноном |
|----|---------|-------------------------------|-----------------|
| **A17.1** | Канон-пакет `context/algorithms/agents/` заполнен; **CR4:** подстрока `context/artifacts` в каноне отсутствует. | `verification.md` §2 проход | Пакет по [`INDEX.md`](../context/algorithms/agents/INDEX.md) |
| **A17.2** | В каноне зафиксировано: исследование для канона — **`start-research`**; **`10_researcher`** в нормативном пайплайне **нет**. | Пакет [`agents/INDEX.md`](../context/algorithms/agents/INDEX.md) | Цель слайса **G17.3** |
| **A17.3** | Расхождение канон ↔ **`.cursor/`** по **`10_researcher`** **устранено** в актуальном дереве: в **`.cursor/`** совпадений **нет**; **`01`** описывает роли **`02`–`09`, `11`–`13`**. | [`project-agent-models.mdc`](../.cursor/rules/project/project-agent-models.mdc), grep по **`.cursor/`** | **G17.3** закрыт; регрессия — повтор grep |
| **A17.4** | Автоматического CI-линтера на «Task / Subagent из **02–09**» **нет**; риск **G1**. | [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md) | Зазор документирован в каноне |
| **A17.5** | Целевая нарезка **S1–S6** согласована в **`synthesis.md`** (Small-Scope). | `synthesis.md` §Small-Scope | Слайсы §4 |

---

## 3. Нормативные решения / контракты

| ID | Решение | Закреплено в каноне (markdown) |
|----|---------|--------------------------------|
| **C17.1** | Канон **не** дублируется в `plan/`; план только мост к `start-feature` / правкам `.cursor/`. | [`agents/INDEX.md`](../context/algorithms/agents/INDEX.md) §План внедрения |
| **C17.2** | Выравнивание промптов с каноном **не** меняет продуктовый Python-код, пока слайс явно не добавляет задачи на код. | §1.3 |
| **C17.3** | После правок промптов **required:** `flake8` по затронутым путям (если правки касаются соседнего Python — редко; иначе N/A) и регрессия **`pytest`** всего дерева. | [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md) |
| **C17.4** | Роль **`10_researcher`** **не** используется; исследование для канона — только **`start-research`** / **100**. | [`glossary.md`](../context/algorithms/agents/glossary.md), [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md) |
| **C17.5** | Любой rg-gate по **02–09** и **11–13** — **подстрочный поиск**, не полноценный парсер Markdown; ложные срабатывания снимаются **явным whitelist** в комментарии плана или скрипта. | §4.4 |

---

## 4. Этапы / слайсы

Зависимости: **G17.1 → G17.2** (терминология перед видимым упоминанием в шаблонах); **G17.3** логично сразу после согласования терминов (убрать **10** из `.cursor/`); **G17.4** и **G17.5** параллелим с **G17.2**; **G17.6** **отменён** (отдельный шаг «10 до 08» не используется — см. канон и **C17.4**).

### G17.1 — S1: Видимость разводки `plan/` vs план **06** в точках входа

| Поле | Содержание |
|------|------------|
| **Цель** | Снизить ошибки постановки в монорепо: один искатель открывает **`plan/`**, другой — артефакт **06**; входы должны отсылать к [`glossary.md`](../context/algorithms/agents/glossary.md). |
| **Implementation anchors** | [`.cursor/rules/start-feature.mdc`](../.cursor/rules/start-feature.mdc), [`.cursor/rules/start-fix.mdc`](../.cursor/rules/start-fix.mdc), при необходимости один абзац в [`.cursor/rules/project/project-workflow.mdc`](../.cursor/rules/project/project-workflow.mdc); канон: [`glossary.md`](../context/algorithms/agents/glossary.md). |
| **Зависимости** | Нет. |
| **Anti-patterns** | Дублировать полный глоссарий в каждом правиле; менять смысл **06** (канон задаёт термин, не новую роль). |
| **Критерии приёмки** | В **start-feature** и **start-fix** есть явная отсылка «план репозитория `plan/` ≠ план артефактов **06**» + ссылка на [`glossary.md`](../context/algorithms/agents/glossary.md) **или** эквивалентная короткая формулировка с тем же различением. |

**Проверки (именованные):**

```bash
# Регрессия продукта (обязательна до коммита любого слайса, если не сказано иначе):
/home/artem/reps/ailit-agent/.venv/bin/python -m pytest /home/artem/reps/ailit-agent/tests -q
```

```bash
# Подтверждение наличия подстрок разводки (после правок; adjust пути при переносе):
rg -n "plan/|06_planner|глоссари|glossary\.md" /home/artem/reps/ailit-agent/.cursor/rules/start-feature.mdc /home/artem/reps/ailit-agent/.cursor/rules/start-fix.mdc
```

---

### G17.2 — S2: Согласованность «терминальные состояния» с топологией (документирование в промптах)

| Поле | Содержание |
|------|------------|
| **Цель** | Таблица терминальных состояний уже в каноне; убедиться, что **01** и overrides не противоречат ей в free-text (точечные правки). |
| **Implementation anchors** | [`01_orchestrator.md`](../.cursor/agents/01_orchestrator.md) (state machine, completion); [`.cursor/rules/project/project-orchestrator-overrides.mdc`](../.cursor/rules/project/project-orchestrator-overrides.mdc); канон: [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md). |
| **Зависимости** | Рекомендуется после G17.1 (общая терминология). |
| **Anti-patterns** | Вводить новые имена состояний без строки в каноне; удалять строку **09** из критического пути. |
| **Критерии приёмки** | Нет противоречия между таблицей в [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md) и описанием в **`01`** / overrides; при расхождении исправляется промпт, **или** (если меняется поведение) — сначала канон через **12→13** (вне этого слайса). |

**Проверки:**

```bash
rg -n "completion|blocked|partial|финальн|terminal" /home/artem/reps/ailit-agent/.cursor/agents/01_orchestrator.md /home/artem/reps/ailit-agent/.cursor/rules/project/project-orchestrator-overrides.mdc
```

Ручное сравнение: строки таблицы терминальных состояний в [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md) ↔ разделы **`01`** (без требования автоматического diff-инструмента).

---

### G17.3 — S3: Удаление **`10_researcher`** из `.cursor/` и согласование с **`01`**

**Статус в этом репозитории:** выполнено; ниже — зафиксированный контракт и проверки на регрессию.

| Поле | Содержание |
|------|------------|
| **Цель** | Канон требует: исследование для алгоритмов — только **`start-research`** (**100**, **101–108**). Роль **`10_researcher`** из репозитория **удаляется** (карта моделей, таблицы в промптах, любые «ad-hoc researcher» у **01**). Таблица **Subagent types** в **`01`** перечисляет **только** реально вызываемые типы: **02–09**, **11–13** в контуре **01** и **101–108** у **100**. |
| **Implementation anchors** | [`project-agent-models.mdc`](../.cursor/rules/project/project-agent-models.mdc); [`01_orchestrator.md`](../.cursor/agents/01_orchestrator.md) (блок Subagent types); при необходимости другие `.cursor/agents/*.md` и правила, где встречается **`10_researcher`**; канон: [`glossary.md`](../context/algorithms/agents/glossary.md), [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md). |
| **Зависимости** | Логично после **G17.1**; может параллелиться с **G17.2** при отсутствии конфликта правок в одном файле. |
| **Anti-patterns** | Снова ввести **10** как обязательный шаг **start-feature**; оставить «мёртвую» строку в карте без удаления из промптов; смешивать **101/102** с сессией **01**. |
| **Критерии приёмки** | `rg "10_researcher"` по **`.cursor/`** возвращает **0** совпадений **или** остаток перечислен в явном **whitelist** с задачей на следующий PR; в **`01`** таблица типов согласована с каноном; **`project-agent-models.mdc`** не содержит **`10_researcher`**. |

**Проверки:**

```bash
rg -n "10_researcher" /home/artem/reps/ailit-agent/.cursor/
```

```bash
rg -n "Subagent types:" /home/artem/reps/ailit-agent/.cursor/agents/01_orchestrator.md
```

```bash
/home/artem/reps/ailit-agent/.venv/bin/python -m pytest /home/artem/reps/ailit-agent/tests -q
```

---

### G17.4 — S4: Опциональный rg-gate «не предлагать Task/Subagent» для **02–09**

| Поле | Содержание |
|------|------------|
| **Цель** | Снизить регрессию **G1**: минимальная автопроверка или документированный pre-merge шаг. |
| **Implementation anchors** | [`.cursor/agents/02_analyst.md`](../.cursor/agents/02_analyst.md) … [`.cursor/agents/09_code_reviewer.md`](../.cursor/agents/09_code_reviewer.md) — выборочно; канон: [`anti-patterns.md`](../context/algorithms/agents/anti-patterns.md), [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md). |
| **Зависимости** | Нет. |
| **Anti-patterns** | Парсер Markdown «в стиле компилятора»; блокировать упоминания **100** в учебных примерах как ложные срабатывания grep; считать grep заменой ревью человека. |
| **Критерии приёмки** | Либо (а) скрипт в `scripts/` + команда в документации репозитория, либо (б) зафиксированный **rg one-liner** в [`context/arch/`](../context/arch/) или в комментарии к PR-чеклисту; **whitelist** допустимых совпадений документирован. Минимум: каждый файл **02–09** содержит явный запрет запуска Subagents **или** ссылку на **project-workflow** + строка не удалена. |

**Проверки (пример grep, уточнить паттерн под формулировки):**

```bash
# Ожидаем: для каждого агента 02-09 найдётся минимум одно из (запрет Subagent / Task tool / отсылка к project-workflow):
for f in /home/artem/reps/ailit-agent/.cursor/agents/0[2-9]_*.md; do
  echo "== $f ==";
  rg -n "Subagent|Task tool|project-workflow|не запуска" "$f" | head -5;
done
```

```bash
/home/artem/reps/ailit-agent/.venv/bin/python -m pytest /home/artem/reps/ailit-agent/tests -q
```

---

### G17.5 — S5: Шаблон минимальной USER-story (OR-006)

| Поле | Содержание |
|------|------------|
| **Цель** | Дать копируемый минимум полей для **`start-feature` / `start-fix`**, согласованный с [`user-story-handoff.md`](../context/algorithms/agents/user-story-handoff.md). |
| **Implementation anchors** | [`.cursor/rules/start-feature.mdc`](../.cursor/rules/start-feature.mdc), [`.cursor/rules/start-fix.mdc`](../.cursor/rules/start-fix.mdc); канон: [`user-story-handoff.md`](../context/algorithms/agents/user-story-handoff.md). |
| **Зависимости** | G17.1 желателен (термины `plan/`). |
| **Anti-patterns** | Требовать JSON от человека; обещать детерминированный NL-router «story → gate». |
| **Критерии приёмки** | В одном из правил входа есть блок «Минимальный шаблон USER-story» с полями из канона (цель, ограничения, **`non_code_intent`** / путь к алгоритму при наличии, ожидаемый результат для fix). |

**Проверки:**

```bash
rg -n "USER-story|user-story|non_code|story" /home/artem/reps/ailit-agent/.cursor/rules/start-feature.mdc /home/artem/reps/ailit-agent/.cursor/rules/start-fix.mdc
```

---

### G17.6 — S6: **Отменён**

Слайс **S6** («пред-маршрутный шаг **10** до **08**») **не** выполняется: в каноне зафиксировано удаление роли **`10_researcher`**; исследование — только **`start-research`**. Историческая ссылка на G17.6 в старых версиях плана считается **устаревшей**.

---

## 5. Пользовательские сценарии

### Happy path

1. Оператор утвердил канон [`agents/INDEX.md`](../context/algorithms/agents/INDEX.md) и открыл этот план.
2. Запускает `start-feature` для слайса **G17.3** с ссылкой на §4.3 и канон.
3. После правок **`.cursor/`** и регресса **`pytest`** в репозитории **нет** активной роли **`10_researcher`**; таблица **Subagent types** в **`01`** согласована с каноном (**02–09**, **11–13**, **101–108**).

### Partial path

1. Слайс **G17.4**: grep выдаёт шум на примере кода в промпте; исполнитель добавляет **whitelist** и сужает паттерн.
2. Документальные правки **start-feature** приняты; полная автоматизация в CI откладывается — в §7 помечается `implementation_backlog`.

### Failure / blocked path

1. Исполнитель снова вводит **`10_researcher`** в карту или в **`01`** как рабочую роль → **остановка**: противоречие **C17.4** и [`glossary.md`](../context/algorithms/agents/glossary.md).
2. Исполнитель смешивает **`plan/17-…`** с выходом **06** в инструкции пользователю → нарушение **C17.1** / [`anti-patterns.md`](../context/algorithms/agents/anti-patterns.md).

---

## 6. Наблюдаемость и доказательства закрытия этапов

| Этап | Доказательство закрытия |
|------|-------------------------|
| G17.1 | Diff в `start-feature`/`start-fix` + успешный `rg` из §4.1. |
| G17.2 | Ручная сверка 1:1 с таблицей в [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md) + журнал в PR. |
| G17.3 | `rg "10_researcher" .cursor/` → 0 (или задокументированный whitelist) + `pytest -q` зелёный. |
| G17.4 | Зафиксированная команда grep или скрипт + список файлов **02–09** (и при необходимости **11–13**). |
| G17.5 | Наличие шаблона в правиле + `rg` из §4.5. |
| G17.6 | **Не применяется** (слайс отменён; см. §4.6). |

Норматив по **SoT** сессии и **11→01:** [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md).

---

## 7. Gaps (таблица, таксономия `project-human-communication.mdc`)

| ID | Тип | Важность | Описание | Следующее действие |
|----|-----|----------|----------|-------------------|
| **GAP-17-1** | `implementation_backlog` | Средняя | Нет `.github/workflows`; rg-gate только локально. | G17.4: при появлении CI — перенести команду. |
| **GAP-17-2** | `implementation_backlog` | Низкая | Ранее: optional **10** до **08** — **снято** каноном. | Нет действия; не открывать G17.6. |
| **GAP-17-3** | `doc_incomplete` | Низкая | В части файлов канона `Status: draft` при пакетном `ready_for_verify` (**105** MINOR-1). | Опциональный follow-up **104** / **13**, не блокер этого плана. |
| **GAP-17-4** | `verification_gap` | Нет для G17.1–G17.5 | Отдельные unit-тесты на содержимое `.md` промптов отсутствуют. | Приоритет: rg + ревью; тесты только если позже запросят. |

---

## 8. Definition of Done — трассировка «слайс → канон → проверка»

| Слайс | Файлы канона (markdown) | Что доказываем |
|-------|-------------------------|----------------|
| G17.1 | [`glossary.md`](../context/algorithms/agents/glossary.md), [`INDEX.md`](../context/algorithms/agents/INDEX.md) | Разводка `plan/` vs **06** видна из `start-*`. |
| G17.2 | [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md) | Терминальные состояния согласованы с **`01`**. |
| G17.3 | [`glossary.md`](../context/algorithms/agents/glossary.md), [`pipeline-topology.md`](../context/algorithms/agents/pipeline-topology.md), [`roles-and-artifacts.md`](../context/algorithms/agents/roles-and-artifacts.md) | **`10_researcher`** удалён из `.cursor/`; **CR-F6** снят. |
| G17.4 | [`anti-patterns.md`](../context/algorithms/agents/anti-patterns.md), [`observability-and-tests.md`](../context/algorithms/agents/observability-and-tests.md) | **G1** частично закрыт grep/дисциплиной. |
| G17.5 | [`user-story-handoff.md`](../context/algorithms/agents/user-story-handoff.md) | **OR-006** воспроизводим из шаблона входа. |
| G17.6 | — | **Отменён** (см. §4.6). |

**Общий DoD плана:** все выбранные к исполнению слайсы имеют PR с `pytest -q` зелёным; затронутый Python (если есть) — `flake8` по файлам; нет изменения семантики гейтов без обновления канона через **12→13**.

---

## 9. Flake8

- Если слайс **не** трогает `.py`: **flake8** не обязателен.
- Если добавляется `scripts/*.py`: выполнить  
  `flake8 <путь_к_новым_или_изменённым_.py>`  
  (интерпретатор из `/home/artem/reps/ailit-agent/.venv`).

---

Produced by: 106_implementation_plan_author
