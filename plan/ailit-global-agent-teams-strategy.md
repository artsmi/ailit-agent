# Стратегия: глобальный `ailit`, мультиагентные команды, плагины и human-readable chat

Документ фиксирует целевую продуктовую и инженерную стратегию после анализа локальных репозиториев `claude-code`, `opencode`, текущего кода `ailit-agent`, выборочного исследования экосистемы плагинов Claude Code и образца репозитория в `reps-research`. Используется как **единый ориентир для реализации**; детальная нарезка на мелкие итерации может дополнять `plan/agent-core-workflow.md` (этапы 7–9 и далее).

**Оглавление документов проекта:** [`docs/INDEX.md`](../docs/INDEX.md)

**Связанные планы:** [`agent-core-workflow.md`](agent-core-workflow.md), [`agent-core-architecture.md`](agent-core-architecture.md), [`agent-core-provider-strategy.md`](agent-core-provider-strategy.md), [`project-orchestrator-strategy.md`](project-orchestrator-strategy.md)

---

## 1. Итоговая цель реализации

После установки в систему `ailit` должен:

1. **Работать из любого каталога** с любым пользовательским проектом, не требуя «жить» внутри репозитория `ailit-agent`.
2. **Читать глобальные настройки** (провайдер, ключи через env/secure storage, дефолтные модели, лимиты токенов) из канонического пользовательского конфигурационного дерева (аналог `~/.claude` / XDG для OpenCode).
3. **Переопределяться на уровне проекта** (локальные файлы в корне проекта, gitignored при необходимости), с предсказуемым приоритетом слоёв merge.
4. **Конфигурироваться из терминала** командами вида «установить провайдера/модель/лимит», без ручного редактирования YAML как единственного пути.
5. **Сохранять и развивать** уже заложенную **оптимизацию токенов** (shortlist, compaction, бюджеты) как сквозную политику runtime.
6. **Поддерживать расширяемость в сторону экосистемы Claude Code** (marketplace, skills, hooks, команды) через **явный MVP-контракт** совместимости, а не через копирование всего их стека.
7. **Реализовать модель Agent Teams**: несколько изолированных агентных контекстов (отдельные сессии/процессы или явные границы state), **межагентная коммуникация** по каналу, согласованному с референсом (почтовый ящик + инструмент сообщений), и **наблюдаемость** этой коммуникации в `ailit chat`.
8. **Разделить режимы**:
   - `ailit chat` — интерактивная среда для пользователя, **human-readable** вывод (без «сырого» JSON в ответах пользователю; структурированные события — во внутреннем слое или вкладке «диагностика»).
   - `ailit agent` — исполнение сценариев/воркфлоу для автоматизации, CI и e2e; стабильный **машиночитаемый** поток событий (например JSONL) остаётся допустимым для потребителей-скриптов.

Критерий успеха продукта: пользователь устанавливает CLI один раз, открывает любой проект, задаёт провайдер глобально, запускает `ailit chat`, видит работу **одного или нескольких** агентов понятным языком, а `ailit agent` принимает задачу в произвольной форме (текст, путь к файлу, URL) и доводит её до проверяемых артефактов с тестами на реальном материализованном проекте.

---

## 2. Диагностика: почему сейчас `ailit` «привязан к репозиторию»

### 2.1. Жёсткий корень репозитория в путях

Модуль `ailit.paths` однозначно привязывает «корень» к расположению пакета внутри клона:

```8:10:/home/artem/reps/ailit-agent/tools/ailit/paths.py
def repo_root() -> Path:
    """Корень репозитория (каталог с pyproject.toml)."""
    return Path(__file__).resolve().parents[2]
```

### 2.2. CLI загружает провайдерский конфиг из дерева репозитория

В `ailit agent run` путь к YAML фиксируется относительно `repo_root()`:

```76:78:/home/artem/reps/ailit-agent/tools/ailit/cli.py
    wf = load_workflow_from_path(wf_path)
    cfg_path_yaml = repo_root() / "config" / "test.local.yaml"
    cfg = dict(load_test_local_yaml(cfg_path_yaml))
```

### 2.3. Chat UI та же привязка

```12:14:/home/artem/reps/ailit-agent/tools/ailit/chat_app.py
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "tools") not in sys.path:
    sys.path.insert(0, str(_REPO / "tools"))
```

и загрузка секретов/настроек:

```39:41:/home/artem/reps/ailit-agent/tools/ailit/chat_app.py
def _load_cfg() -> dict:
    p = _REPO / "config" / "test.local.yaml"
    return dict(load_test_local_yaml(p)) if p.is_file() else {}
```

### 2.4. Загрузчик конфига по умолчанию ориентирован на `cwd`

Это хорошо для проектов, но **не заменяет** глобальный слой:

```12:15:/home/artem/reps/ailit-agent/tools/agent_core/config_loader.py
def default_config_path() -> Path:
    """Путь к `config/test.local.yaml` относительно текущего каталога."""
    return Path.cwd() / "config" / "test.local.yaml"
```

**Вывод:** целевое состояние требует ввести **канонический глобальный путь** (и переменную окружения для override), единый **merge resolver** (global → project → local → CLI), и убрать обязательность `repo_root()` для пользовательского runtime-конфига; `repo_root()` может остаться только для **внутренних** ресурсов пакета (шаблоны, встроенные workflow), но не для `test.local.yaml` пользователя.

---

## 3. Опорные примеры в коде референсов (пути и строки)

Ниже — не «ссылки на репозиторий», а **конкретные якоря** для агентной системы разработки.

### 3.1. `claude-code` — глобальный дом конфигурации и teams

Дом пользовательских настроек и каталог команд:

```7:17:/home/artem/reps/claude-code/utils/envUtils.ts
export const getClaudeConfigHomeDir = memoize(
  (): string => {
    return (
      process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude')
    ).normalize('NFC')
  },
  () => process.env.CLAUDE_CONFIG_DIR,
)

export function getTeamsDir(): string {
  return join(getClaudeConfigHomeDir(), 'teams')
}
```

Порядок источников настроек (важен для проектирования merge в `ailit`):

```7:21:/home/artem/reps/claude-code/utils/settings/constants.ts
export const SETTING_SOURCES = [
  'userSettings',
  'projectSettings',
  'localSettings',
  'flagSettings',
  'policySettings',
] as const
```

Базовый слой настроек из плагинов перед merge файловых источников:

```657:668:/home/artem/reps/claude-code/utils/settings/settings.ts
    // Start with plugin settings as the lowest priority base.
    // All file-based sources (user, project, local, flag, policy) override these.
    const pluginSettings = getPluginSettingsBase()
    let mergedSettings: SettingsJson = {}
    if (pluginSettings) {
      mergedSettings = mergeWith(
        mergedSettings,
        pluginSettings,
        settingsMergeCustomizer,
      )
    }
```

XDG-утилиты для нативного инсталлятора:

```27:34:/home/artem/reps/claude-code/utils/xdg.ts
export function getXDGStateHome(options?: XDGOptions): string {
  const { env, home } = resolveOptions(options)
  return env.XDG_STATE_HOME ?? join(home, '.local', 'state')
}
```

Файловый mailbox между тиммейтами (изоляция + IPC через FS):

```1:17:/home/artem/reps/claude-code/utils/teammateMailbox.ts
/**
 * Teammate Mailbox - File-based messaging system for agent swarms
 *
 * Each teammate has an inbox file at .claude/teams/{team_name}/inboxes/{agent_name}.json
 * Other teammates can write messages to it, and the recipient sees them as attachments.
 */
```

Путь inbox:

```52:65:/home/artem/reps/claude-code/utils/teammateMailbox.ts
export function getInboxPath(agentName: string, teamName?: string): string {
  const team = teamName || getTeamName() || 'default'
  const safeTeam = sanitizePathComponent(team)
  const safeAgentName = sanitizePathComponent(agentName)
  const inboxDir = join(getTeamsDir(), safeTeam, 'inboxes')
  const fullPath = join(inboxDir, `${safeAgentName}.json`)
  ...
  return fullPath
}
```

Политика «текст в чат не виден команде — нужен инструмент»:

```8:17:/home/artem/reps/claude-code/utils/swarm/teammatePromptAddendum.ts
export const TEAMMATE_SYSTEM_PROMPT_ADDENDUM = `
# Agent Teammate Communication
...
- Use the SendMessage tool with \`to: "<name>"\` to send messages to specific teammates
...
Just writing a response in text is not visible to others on your team - you MUST use the SendMessage tool.
```

Инструмент отправки (точка расширения протокола «сообщение агенту»):

```1:44:/home/artem/reps/claude-code/tools/SendMessageTool/SendMessageTool.ts
import { feature } from 'bun:bundle'
import { z } from 'zod/v4'
...
import {
  createShutdownApprovedMessage,
  createShutdownRejectedMessage,
  createShutdownRequestMessage,
  writeToMailbox,
} from '../../utils/teammateMailbox.js'
...
import { SEND_MESSAGE_TOOL_NAME } from './constants.ts'
```

Константы swarm (имена, env для spawn):

```1:33:/home/artem/reps/claude-code/utils/swarm/constants.ts
export const TEAM_LEAD_NAME = 'team-lead'
...
export const TEAMMATE_COMMAND_ENV_VAR = 'CLAUDE_CODE_TEAMMATE_COMMAND'
export const TEAMMATE_COLOR_ENV_VAR = 'CLAUDE_CODE_AGENT_COLOR'
```

Парсинг «бюджета» из текста пользователя (UX-паттерн для token governance):

```1:28:/home/artem/reps/claude-code/utils/tokenBudget.ts
const SHORTHAND_START_RE = /^\s*\+(\d+(?:\.\d+)?)\s*(k|m|b)\b/i
...
export function parseTokenBudget(text: string): number | null {
```

### 3.2. `opencode` — XDG layout и многоуровневый конфиг

Глобальные пути приложения и override для тестов:

```8:26:/home/artem/reps/opencode/packages/opencode/src/global/index.ts
const app = "opencode"

const data = path.join(xdgData!, app)
const cache = path.join(xdgCache!, app)
const config = path.join(xdgConfig!, app)
const state = path.join(xdgState!, app)

export const Path = {
  get home() {
    return process.env.OPENCODE_TEST_HOME || os.homedir()
  },
  data,
  bin: path.join(cache, "bin"),
  log: path.join(data, "log"),
  cache,
  config,
  state,
}
```

Директории поиска конфигов: глобальный config + вверх по дереву `.opencode`:

```25:42:/home/artem/reps/opencode/packages/opencode/src/config/paths.ts
export const directories = Effect.fn("ConfigPaths.directories")(function* (directory: string, worktree?: string) {
  const afs = yield* AppFileSystem.Service
  return unique([
    Global.Path.config,
    ...(!Flag.OPENCODE_DISABLE_PROJECT_CONFIG
      ? yield* afs.up({
          targets: [".opencode"],
          start: directory,
          stop: worktree,
        })
      : []),
    ...(yield* afs.up({
      targets: [".opencode"],
      start: Global.Path.home,
      stop: Global.Path.home,
    })),
    ...(Flag.OPENCODE_CONFIG_DIR ? [Flag.OPENCODE_CONFIG_DIR] : []),
  ])
})
```

Плагины: автоскан каталога + разрешение относительных путей от файла конфигурации:

```26:64:/home/artem/reps/opencode/packages/opencode/src/config/plugin.ts
export async function load(dir: string) {
  const plugins: Spec[] = []

  for (const item of await Glob.scan("{plugin,plugins}/*.{ts,js}", {
    cwd: dir,
    absolute: true,
    dot: true,
    symlink: true,
  })) {
    plugins.push(pathToFileURL(item).href)
  }
  return plugins
}
...
export async function resolvePluginSpec(plugin: Spec, configFilepath: string): Promise<Spec> {
```

Merge с конкатенацией массивов (паттерн для списков агентов/skills):

```45:51:/home/artem/reps/opencode/packages/opencode/src/config/config.ts
function mergeConfigConcatArrays(target: Info, source: Info): Info {
  const merged = mergeDeep(target, source)
  if (target.instructions && source.instructions) {
    merged.instructions = Array.from(new Set([...target.instructions, ...source.instructions]))
  }
  return merged
}
```

### 3.3. `ailit-agent` — уже есть бюджет и e2e на материализованном проекте

Бюджет на уровне сессии:

```11:55:/home/artem/reps/ailit-agent/tools/agent_core/session/budget.py
@dataclass
class BudgetGovernance:
    """Ограничения по токенам и грубой оценке размера контекста."""

    max_total_tokens: int | None = None
    max_context_units: int | None = None
...
    def check_exceeded(self, messages: Sequence[ChatMessage]) -> str | None:
```

E2E: реальный вызов CLI на сгенерированном мини-приложении:

```13:51:/home/artem/reps/ailit-agent/tests/e2e/test_cli_agent_e2e.py
@pytest.mark.e2e
def test_cli_agent_run_dry_run_emits_finished(
    mini_app_root: Path,
) -> None:
    """Dry-run: код 0, в stdout есть workflow.finished."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=mini_app_root,
...
```

---

## 4. Исследование плагинов Claude Code (интернет + локальный образец)

### 4.1. Внешние источники (для стратегии распространения, не как runtime-зависимость)

- Официальная документация marketplaces: [Create and distribute a plugin marketplace](https://docs.anthropic.com/en/docs/claude-code/plugin-marketplaces)
- Каталоги и реестры: [ClaudePluginHub](https://www.claudepluginhub.com/), [claude-plugins.dev](https://claude-plugins.dev/), [claudecodemarketplace.net](https://claudecodemarketplace.net/marketplace)

Типичный состав плагина в экосистеме: skills, агенты, slash-команды, hooks, MCP — это **ориентир для MVP-контракта** `ailit`, а не требование реализовать всё сразу.

### 4.2. Локальный образец для разбора структуры

В репозитории исследований (shallow clone):

- `/home/artem/reps/reps-research/claude-code-plugins-sample`

Там типично встречаются деревья вида `plugins/<name>/`, вложенные `.agents/skills/...` — полезно для **схемы импорта** (какие файлы считаются входными для «расширения»).

---

## 5. Принципы проектирования (best practices из референсов)

| Принцип | Источник идеи | Применение к `ailit` |
|--------|----------------|----------------------|
| Явный глобальный config home + env override | `getClaudeConfigHomeDir`, `CLAUDE_CONFIG_DIR` | `AILIT_CONFIG_DIR` или `~/.config/ailit` (XDG) + документация |
| Слоёный merge с предсказуемым приоритетом | `SETTING_SOURCES`, `loadSettingsFromDisk` | global < project < local/gitignored < CLI flags |
| Плагины как низший слой defaults | `getPluginSettingsBase` | расширения не перетирают явные пользовательские policy |
| Проектные overrides вверх по дереву | `ConfigPaths.directories` | поиск `.ailit/config.*` или `project.yaml` от `cwd` |
| Плагины: resolve относительно declaring file | `resolvePluginSpec` | любой относительный путь в конфиге якорится к файлу, где объявлен |
| Agent teams: FS mailbox + tool-only visibility | `teammateMailbox`, `SendMessage`, prompt addendum | свой `TeamBus` (сначала FS, потом опционально socket/queue) |
| Token UX: явный бюджет в тексте | `parseTokenBudget` | связать с `BudgetGovernance` и UI в chat |
| Human vs machine вывод | разделение TUI/CLI в референсах | JSONL только для `agent`/CI; chat — таблицы, таймлайны, markdown |

---

## 6. Поддержка `ailit chat` для полного пользовательского теста `ailit agent`

### 6.1. Роли режимов

- **`ailit chat`**: сценарий «как пользователь» — выбор проекта, провайдера, наблюдение за ходом workflow, вмешательство (approve), чтение логов в понятном виде, запуск **нескольких** агентов в одной «сессии наблюдения».
- **`ailit agent`**: сценарий «как автоматизация» — неинтерактивный запуск, стабильный exit code, JSONL или структурированный log file.

### 6.2. Human-readable требования

Запрещено как **основной** ответ пользователю в chat:

- дамп сырого JSON больших `event` объектов в основном потоке сообщений.

Разрешено и рекомендуется:

- краткие **сводки** (что сделал агент, какие файлы, сколько токенов);
- **таймлайн** событий с типом и иконкой;
- раскрываемый блок «технические детали» для одной записи;
- экспорт «сырого лога» в файл по кнопке.

Внутренний слой может оставаться JSON/JSONL — важно разделить **transport/view model**.

### 6.3. Отображение нескольких агентов

Минимум: колонка или вкладки «Agent A / Agent B / Orchestrator», общая шкала времени, фильтр по типу события, подсветка **межагентных сообщений** (аналог доставки в mailbox).

---

## 7. Тесты, создающие реальные проекты через `ailit agent`

Уже есть направление: e2e на `mini_app_root` и `AilitCliRunner` (см. §3.3).

**Цель расширения тестов:**

1. Тест вызывает **публичную** утилиту установленного пакета (`ailit` в PATH после `pip install`) или через `python -m` — в CI выбрать один канонический способ и зафиксировать в документе задачи.
2. Тест материализует проект во **временную** директорию вне репозитория `ailit-agent`.
3. Тест запускает `ailit agent` с **новым** входом задачи (см. этап D): файл spec, URL (mock http), raw argv.
4. Тест проверяет **инварианты** на диске (файлы созданы) и **инварианты** событий (finished, нет budget_exceeded при норме).

Существующие файлы для опоры: `tests/e2e/mini_app_factory.py`, `tests/e2e/cli_runner.py`, `tools/ailit/demo_workspace.py`.

---

## 8. Ввод задачи для `ailit agent` (произвольная форма)

Контракт MVP:

| Форма ввода | Поведение |
|-------------|-----------|
| Один аргумент `-t/--task` строка | трактовать как inline spec |
| `--task-file PATH` | прочитать UTF-8 текст |
| `--task-url URL` | скачать (с лимитом размера, таймаутом, allowlist схем https только по умолчанию) |
| STDIN | если tty=false и нет других источников — прочитать полный spec |

Нормализация: все формы сводятся к **внутреннему** `TaskSpec` (plain dataclass / pydantic в будущем), который workflow engine получает как входной артефакт этапа `intake`.

---

## 9. Этапы, задачи, тесты, критерии приёмки и промпты

Нумерация **G–M** (global → multi-agent), чтобы не путать с этапами 1–9 в `agent-core-workflow.md`.

### Этап G. Глобальная конфигурация и отвязка от `repo_root()` для user config

**Цель этапа:** любой установленный `ailit` читает пользовательские настройки из глобального дома; проектные настройки — из дерева проекта.

#### Задача G.1 — Канон путей и переменные окружения

**Сделать:** ввести модуль (например `tools/ailit/user_paths.py` или расширить `paths.py`) с функциями: `global_config_dir()`, `global_state_dir()`, учёт XDG и `AILIT_CONFIG_DIR`.

**Критерии приёмки:**

- При установленном `AILIT_CONFIG_DIR` все глобальные чтения/записи идут туда.
- Без переменной — используется XDG-compliant путь (Linux: `~/.config/ailit` или аналог по спецификации).

**Тесты:** unit без сети: с подменой `HOME` и `AILIT_CONFIG_DIR`.

**Промпт для агента-разработчика:**

```text
Ты работаешь в репозитории ailit-agent.

Задача: добавить канонический глобальный каталог конфигурации для CLI и chat, не ломая существующие вызовы.

Требования:
1. Введи функцию global_config_dir() с приоритетом: переменная окружения AILIT_CONFIG_DIR, иначе XDG_CONFIG_HOME/ailit, иначе ~/.config/ailit (на non-XDG ОС согласуй с os.name).
2. Документируй поведение в одном модуле; избегай дублирования строк путей.
3. Не удаляй repo_root(): он может оставаться для внутренних ресурсов пакета, но не для пользовательского test.local.yaml.
4. Добавь минимальные unit-тесты с tmp_path и monkeypatch для HOME и AILIT_CONFIG_DIR.

Критерии приёмки:
- pytest проходит;
- ни один существующий тест не сломан;
- flake8/pep257 для новых файлов.

Опорные примеры на диске:
- /home/artem/reps/claude-code/utils/envUtils.ts строки 7–17 (CLAUDE_CONFIG_DIR + ~/.claude)
- /home/artem/reps/opencode/packages/opencode/src/global/index.ts строки 8–26 (xdg layout)

Файлы для правки (ориентир): tools/ailit/paths.py, tools/ailit/cli.py, tools/ailit/chat_app.py, tools/agent_core/config_loader.py.
```

**Статус:** выполнено (канон реализован в `tools/ailit/user_paths.py`; `repo_root()` не трогали).

**Чекпоинт для проверки (после G.1):**

- Из корня репозитория (или при `pip install -e .`): `PYTHONPATH=tools python3 -c "from ailit.user_paths import global_config_dir, global_state_dir; print(global_config_dir()); print(global_state_dir())"` — печатаются абсолютные пути без ошибок.
- С подменой каталога: `AILIT_CONFIG_DIR=/tmp/ailit-cfg-test python3 -c "from ailit.user_paths import global_config_dir; print(global_config_dir())"` — вывод ровно этот путь (разрешённый).
- На Linux без override: конфиг ожидается под `~/.config/ailit` (или `XDG_CONFIG_HOME/ailit`), состояние — под `~/.local/state/ailit` (или `XDG_STATE_HOME/ailit`).
- `python3 -m pytest tests/test_user_paths.py -q` — все тесты проходят.

#### Задача G.2 — Merge слоя конфигурации

**Сделать:** единая функция `load_merged_ailit_config(project_root: Path | None) -> Mapping` с порядком: defaults → global file(s) → project → env overrides.

**Критерии приёмки:** детерминированный порядок; покрыты тестом два конфликтующих ключа.

**Промпт:**

```text
Реализуй load_merged_ailit_config(project_root) в ailit-agent.

Слои (от низшего к высшему приоритету):
1) встроенные defaults в коде
2) глобальный YAML/JSON в global_config_dir()/config.yaml (имя согласуй и зафиксируй константой)
3) project: <project_root>/.ailit/config.yaml если есть
4) переменные окружения для провайдера (DEEPSEEK_API_KEY и т.д. — уже есть хелперы)

Требования:
- Типизация Python для публичных функций.
- Без сетевых вызовов.
- Тесты: tmp_path с двумя файлами, проверка перекрытия.

Опоры:
- claude-code/utils/settings/constants.ts 7–21 (порядок источников — аналогия)
- opencode/packages/opencode/src/config/paths.ts 25–42 (проектный поиск вверх по дереву — опционально на подзадачу G.3)
```

**Статус:** выполнено (`tools/ailit/merged_config.py`, `load_merged_ailit_config`, константа имени глобального файла — `config.yaml` в каталоге из `global_config_dir()`).

#### Задача G.3 — Поиск `.ailit/config.yaml` вверх по дереву от `project_root`

**Сделать:** при merge учитывать не только `<project_root>/.ailit/config.yaml`, но и файлы у предков каталога (монорепозитории, запуск из подпроекта).

**Критерии:** из вложенного каталога без своего `.ailit` подтягивается конфиг родителя; при нескольких файлах по пути ближайший к `project_root` перекрывает дальние.

**Статус:** выполнено (`tools/ailit/project_config_discovery.py`, `ProjectAilitConfigDiscovery.collect_deepest_first`; merge в `AilitConfigMerger.load`; тесты `tests/test_merged_config.py`).

**Чекпоинт для проверки (после G.2):**

- Unit-тест демонстрирует перекрытие одного и того же ключа из глобального и проектного файла — в merge побеждает ожидаемый слой.
- Вызов `load_merged_ailit_config` (или финальное имя функции) на временном `project_root` без файлов даёт предсказуемый dict с defaults.
- Нет сетевых вызовов при загрузке; pytest зелёный для новых тестов.

**Чекпоинт этапа G (интеграция путей + merge):**

- Пользовательский секрет не обязан лежать в клоне `ailit-agent`: достаточно глобального и/или проектного файла в канонических путях (после G.2 и этапа I это проверяется end-to-end).

---

### Этап H. CLI как у «взрослого» продукта (`ailit config …`)

**Цель:** базовые операции без редактирования файлов вручную.

#### Задача H.1 — `ailit config path`, `ailit config show`

**Критерии:** печать эффективного пути и сырого merge результата (для человека — yaml-safe).

**Промпт:**

```text
Добавь подкоманды ailit:
- `ailit config path` — печать global_config_dir и (если задан) project_root из cwd detection
- `ailit config show` — показать эффективный merge конфигурации (без секретов: редактировать ключи api_key)

Критерии приёмки:
- argparse подкоманды;
- секреты не попадают в stdout;
- pytest на подпроцесс или на функцию форматирования.

Не добавляй README.
```

**Статус:** выполнено (`tools/ailit/config_cli.py`, регистрация в `tools/ailit/cli.py`).

**Чекпоинт для проверки (после H.1):**

- `ailit config path` печатает глобальный каталог и (если реализовано обнаружение) корень проекта.
- `ailit config show` не выводит значения `api_key` и аналогичных секретных полей в открытом виде.
- `ailit config --help` / подкоманды отображаются в справке.

#### Задача H.2 — `ailit config set key value` (ограниченный allowlist ключей)

**Критерии:** только allowlisted nested keys; иначе ошибка с подсказкой.

**Статус:** выполнено (`tools/ailit/config_store.py`, подкоманда `ailit config set` в `config_cli.py`).

**Чекпоинт для проверки (после H.2):**

- Разрешённый ключ записывается в ожидаемый глобальный файл; неразрешённый ключ даёт понятную ошибку и не пишет файл.

---

### Этап I. Перевод `chat` и `agent run` на merged config

**Цель:** убрать обязательность `repo_root()/config/test.local.yaml` для конечного пользователя.

#### Задача I.1 — `agent run` использует merged config

Изменить участок:

```76:78:/home/artem/reps/ailit-agent/tools/ailit/cli.py
    cfg_path_yaml = repo_root() / "config" / "test.local.yaml"
    cfg = dict(load_test_local_yaml(cfg_path_yaml))
```

на загрузку через merge + опциональный fallback на старый путь для **разработчиков репозитория** (feature flag или явный `--dev-repo-config`).

**Промпт:**

```text
Обнови tools/ailit/cli.py:_cmd_agent_run так, чтобы провайдерский конфиг брался из load_merged_ailit_config(project_root), а не только из repo_root()/config/test.local.yaml.

Сохрани обратную совместимость для разработки в клоне ailit-agent (например если существует repo_root()/config/test.local.yaml — включить как низкий приоритет или флаг --dev-repo-config).

Тесты: обнови/добавь unit или e2e минимальный сценарий с tmp_path проектом и глобальным конфигом в tmp HOME.

Опора: текущие строки cli.py 76–78 и chat_app.py 39–41.
```

**Статус:** выполнено (`tools/ailit/agent_provider_config.py`, `AgentRunProviderConfigBuilder`, флаг `--no-dev-repo-config` в `ailit agent run`).

**Чекпоинт для проверки (после I.1):**

- `ailit agent run` с mock-провайдером в временном проекте подхватывает ключи из merge, без обязательного `repo_root()/config/test.local.yaml`.
- Режим разработки в клоне (`test.local.yaml` в репозитории или флаг) по-прежнему работает по задумке.

#### Задача I.2 — `chat_app` использует тот же resolver

**Критерии:** один источник правды для ключей DeepSeek и т.д.

**Статус:** выполнено (`chat_app.py`: `_load_merged_chat_cfg` через `AgentRunProviderConfigBuilder`).

**Чекпоинт для проверки (после I.2):**

- Запуск `ailit chat` (при наличии зависимостей) использует тот же merge, что и `agent run`; смена глобального файла меняет поведение без копирования YAML в корень `ailit-agent`.

---

### Этап J. Human-readable слой в `ailit chat`

**Цель:** пользователь не видит сырой JSON как основной ответ.

#### Задача J.1 — View-model над событиями

**Сделать:** слой форматирования: `format_event_for_user(event) -> str` (markdown), плюс структура для Streamlit.

**Тесты:** golden strings для 3–5 типов событий.

**Промпт:**

```text
Вынеси форматирование событий для UI ailit chat в отдельный модуль (например tools/ailit/chat_presenters.py) с классами по типу Strategy/Visitor, чтобы не дублировать if-цепочки в chat_app.py.

Требования:
- Публичные функции типизированы.
- Не ломай существующий функционал чата; замени прямые выводы JSON на presenter.
- Добавь тесты golden на несколько event_type.

Критерии приёмки: pytest; UI по-прежнему запускается streamlit run.
```

**Статус:** выполнено (`tools/ailit/chat_presenters.py`; в `chat_app.py`: вкладки Workflow/Adapter/Проект — markdown + expander для сырого JSONL; верхняя строка **«Меню»** в колонке рядом с настройками; ответы роли `tool` в диалоге — markdown + expander «Сырой JSON»).

**Чекпоинт для проверки (после J.1):**

- В основной области чата нет «обязательного» сырого JSON; при необходимости сырой вид доступен только во вспомогательном блоке (expander / диагностика).

---

### Этап K. Ввод задачи и сценарии e2e «как пользователь»

#### Задача K.1 — CLI флаги `--task`, `--task-file`, нормализация в `TaskSpec`

**Промпт:**

```text
Добавь в ailit agent run приём задачи:
--task TEXT | --task-file PATH | (stdin если не tty)

Собери нормализованный TaskSpec (dataclass) и передай первому шагу workflow или сохрани как артефакт в .ailit/run/<id>/task.md (выбери один канон).

Тесты: pytest subprocess с tmp_path, без сети для task-file и stdin.

Критерии: help обновлён; ошибки понятны.
```

**Статус:** выполнено (`tools/ailit/task_spec.py`, `tools/ailit/cli.py`, `workflow_engine/engine.py`, `workflow_engine/user_task_merge.py`; событие `run.started`; тесты `tests/test_task_spec.py`, `tests/test_workflow_engine.py`, `tests/e2e/test_agent_task_k1.py`).

**Чекпоинт для проверки (после K.1):**

- `--task`, `--task-file` и сценарий stdin (где применимо) дают один и тот же внутренний `TaskSpec` или артефакт в каноническом месте `.ailit/run/…`.

#### Задача K.2 — e2e: материализация + agent + pytest внешнего проекта

Расширить паттерн из `tests/e2e/test_cli_agent_e2e.py`.

**Промпт:**

```text
Добавь e2e тест: временная директория вне репозитория; materialize_demo_app туда; задать HOME с глобальным ailit config; запустить ailit agent с mock провайдером; затем pytest на сгенерированном приложении.

Критерии: тест помечен e2e и не требует ключей.

Опора: tests/e2e/test_cli_agent_e2e.py строки 13–51.
```

**Статус:** выполнено (`tests/e2e/test_cli_agent_e2e.py::test_k2_external_temp_materialize_agent_mock_then_pytest`: каталог под `tempfile.gettempdir()`, `materialize_demo_app`, изолированный `HOME` + `AILIT_CONFIG_DIR`, `ailit agent run` mock без dry-run, затем `pytest` на сгенерированном приложении).

**Чекпоинт для проверки (после K.2):**

- e2e в CI/локально проходит без реальных API-ключей; каталог проекта создаётся вне репозитория `ailit-agent`.

---

### Этап L. Agent Teams (изоляция + mailbox + наблюдаемость)

**Цель:** несколько агентов с отдельным state и обменом сообщениями; в `chat` виден обмен.

#### Задача L.1 — Спецификация `TeamSession` и FS mailbox под `AILIT_CONFIG_DIR` или project `.ailit/teams`

**Промпт:**

```text
Спроектируй и реализуй MVP межагентной почты для ailit-agent, вдохновлённый claude-code:
- каталог команд: <state>/teams/<team_id>/inboxes/<agent>.json
- атомарная запись с file lock (используй существующие утилиты проекта или добавь минимальную кроссплатформенную блокировку)
- сообщения: from, to, text, ts, read

Опоры:
- teammateMailbox.ts 1–65
- swarm/constants.ts 1–33

Тесты: два fake агента пишут друг другу в tmp_path.

Не интегрируй LLM на этом шаге.
```

**Статус:** выполнено (`tools/ailit/teams/mailbox.py`, `tools/ailit/teams/__init__.py`): `TeamSession`, `TeamRootSelector.for_project` → `<project>/.ailit/teams/<team_id>/inboxes/<agent>.json`, `for_global_state` → `<AILIT_STATE_DIR|XDG state>/teams/...`; блокировка sidecar `*.lock` + `flock` на POSIX, атомарная запись inbox; тесты `tests/test_teams_mailbox.py`.

**Чекпоинт для проверки (после L.1):**

- Два тестовых «агента» обмениваются сообщениями через ФС под управляемым `tmp_path`; файлы inbox читаемы и атомарны с точки зрения теста (нет порчи JSON при конкуренции в сценарии теста).

#### Задача L.2 — Инструмент агента `send_teammate_message` + политика prompt addendum

**Промпт:**

```text
Добавь tool в tool runtime: отправка сообщения другому агенту через mailbox MVP из задачи L.1.

Добавь optional system addendum для «teammate» ролей по аналогии с TEAMMATE_SYSTEM_PROMPT_ADDENDUM (текст можно адаптировать, но смысл тот же: обычный текст в чате не доставлен).

Интеграционный тест: mock provider + два агента в одном workflow YAML (если engine не умеет — сначала минимальный orchestrator в коде теста).

Опоры:
- teammatePromptAddendum.ts 8–17
- SendMessageTool.ts 1–44 (только архитектурно, не копируй код)
```

**Статус:** выполнено (`ailit/teams_tools.py`, merge в `chat_app._registry_for_chat`; `project_layer/models.py` поле `agents.*.role`, `project_layer/teammate_prompt.py`, `compute_chat_tuning`; тесты `tests/test_teammate_tool.py`, `tests/test_teammate_role_tuning.py`).

**Чекпоинт для проверки (после L.2):**

- Инструмент отправки маршрутизирует в mailbox; в system prompt для teammate-ролей явно сказано, что текст в чате не заменяет инструмент.

#### Задача L.3 — `ailit chat`: панель «Команда»

**Промпт:**

```text
Расширь Streamlit UI: панель со списком агентов, последними сообщениями mailbox, фильтром по адресату.

Требования: human-readable; сырой JSON только в expander.

Тесты: минимум unit на presenter; e2e UI не обязателен.
```

**Статус:** выполнено (`ailit/teams_panel_presenter.py`; вкладка «Команда» в `chat_app.py`, чекбокс «Инструмент команды (mailbox)»; презентер tool-ответа в `chat_presenters.py`; тест `tests/test_teams_panel_presenter.py`).

**Чекпоинт для проверки (после L.3):**

- В UI виден список агентов и последние сообщения; сырой JSON только под раскрывающимся блоком.

---

### Этап M. Плагины / marketplace совместимость (MVP)

**Цель:** не «запустить плагины Claude», а **импортировать подмножество** артефактов (skills, manifest) в project layer.

#### Задача M.1 — Контракт `ailit plugin install <git-url|path>` → распаковка в `.ailit/plugins/<id>`

**Промпт:**

```text
Реализуй MVP установки плагина в каталог проекта .ailit/plugins/<id> с манифестом ailit-plugin.yaml (минимальная схема версии 1).

Не реализуй полный marketplace parser Anthropic; достаточно:
- зафиксировать поля name, version, skills_paths[]
- импортировать skills в project_layer registry (если уже есть hooks — используй)

Опоры:
- opencode config/plugin.ts 26–64 (path resolution относительно declaring file)
- claude-code settings.ts 657–668 (плагин как низший слой defaults — концептуально)

Тесты: fixture плагин в tmp_path.
```

**Статус:** выполнено (`ailit/plugin_install.py`, `project_layer/plugin_manifest.py`, `project_layer/plugin_skills.py`, `compute_chat_tuning` подмешивает snippets; CLI `ailit plugin install`; тест `tests/test_plugin_install_and_skills.py`).

**Чекпоинт для проверки (после M.1):**

- `ailit plugin install` (или выбранная команда) создаёт каталог под `.ailit/plugins/<id>` с валидным манифестом; skills из плагина попадают в реестр проектного слоя.

---

### Этап N. Лимиты агентного цикла (`max_turns`) и UX (сопоставимо с продуктами Claude)

**Цель:** пользователь понимает, что такое лимит итераций сессии, как он **не** дублирует поля HTTP API провайдера, и что делать при `max_turns_exceeded`; поведение согласовано с best practices агентских клиентов.

**Контекст (как сейчас в `ailit-agent`):**

- В `agent_core.session.loop.SessionRunner.run` внешний цикл `for turn in range(settings.max_turns)` задаёт **максимум итераций** «агентного цикла» (вызов модели, обработка `tool_calls`, дозапросы и т.д.). Исчерпание без финального текстового ответа даёт `reason="max_turns_exceeded"` (состояние ошибки в текущей модели — см. `tools/agent_core/session/loop.py`).
- Это **оркестрационный** лимит (аналог «сколько шагов может сделать агент»), а не параметр вида `max_tokens` в одном запросе к Anthropic Messages API.
- В экосистеме **Claude** (API) явного поля `max_turns` нет; в **Claude Code** и подобных продуктах лимиты шагов/стоимости/таймауты задаются **на уровне приложения** — мы следуем той же логике разделения: API-лимиты vs политика цикла.

**Best practices (ориентир для реализации):**

1. **Разделять понятия в UI и документации:** «лимит шагов / итераций сессии» (`max_turns` в `SessionSettings`) vs «лимит длины ответа» (`max_tokens` у провайдера, если включён).
2. **Понятные дефолты:** для чата с включёнными file tools — не занижать лимит без причины; опционально профили «быстро / глубоко».
3. **При исчерпании лимита:** не оставлять пользователя только с сырой строкой `max_turns_exceeded` — кратко объяснить, что лимит **шагов** исчерпан, предложить увеличить слайдер `max_turns`, указать путь к JSONL-диагностике; опционально (отдельная подзадача) — «продолжить с увеличенным лимитом» без потери истории.
4. **Наблюдаемость:** в диагностике чата показывать последние `session.turn` / счётчик относительно лимита (данные уже эмитятся в diag sink).

#### Задача N.1 — Копирайт и подсказки при `max_turns_exceeded` в `ailit chat`

**Сделать:** заменить/дополнить сообщение об ошибке в UI (и при необходимости в `SessionOutcome` mapping) человекочитаемым текстом + ссылка на увеличение `max_turns`.

**Критерии:** при искусственно низком `max_turns` и цикле с tools пользователь видит объяснение, а не только внутренний код причины.

**Статус:** выполнено (`tools/ailit/chat_app.py`, `tools/ailit/session_outcome_user_copy.py`; коммит `feat(chat): N.1`).

#### Задача N.2 — Счётчик шагов / лимит в диагностике чата

**Сделать:** читать последние события процесса `chat` (или буфер diag) и выводить в expander/caption «ход X из Y».

**Критерии:** без ломания существующего потока сообщений.

**Статус:** выполнено (`tools/ailit/chat_app.py` — caption/диагностика «ход X из Y»; коммит `feat(chat): N.2`).

#### Задача N.3 (опционально) — Политика завершения: «мягкий» стоп vs `ERROR`

**Сделать:** зафиксировать продуктовое решение: оставлять `ERROR` или вводить состояние «остановлен по лимиту» с кнопкой продолжения.

**Решение (2026-04, репозиторий `ailit-agent`):** в `agent_core` по-прежнему `SessionState.ERROR` и `reason="max_turns_exceeded"` — без нового enum-значения, чтобы не ломать контракт исполнителей и тестов. В продуктовом слое (`ailit chat`) это трактуется как **мягкая остановка по политике цикла**: отдельный `st.warning` после прогона + человекочитаемое сообщение в истории (см. N.1), а не как «сырая» техническая ошибка API. Отдельное состояние `STOPPED_BY_LIMIT` и кнопка «продолжить с лимитом» без повторной отправки — отложены до приоритета UX/TUI (см. этап P).

**Статус:** выполнено (решение зафиксировано в этом документе; UI — см. N.1; коммит `docs(plan)+feat(chat): N.3`).

**Чекпоинт этапа N:**

- Пользователь без чтения исходников понимает разницу между лимитом шагов сессии и лимитом токенов ответа API.
- При `max_turns_exceeded` есть явная подсказка, как продолжить работу (увеличить лимит / пресет).

**Статус в репозитории (2026-04):** закрыты **N.1–N.3** — человекочитаемый текст и баннер при `max_turns_exceeded`, счётчик шага в диагностике чата, политика «мягкий стоп» в `ailit chat` при сохранении `ERROR` в `agent_core`.

---

### Этап O. Наблюдаемость токенов и кеша (prompt cache / usage), ориентир OpenCode

**Цель:** пользователь и CI видят **сколько токенов** ушло в провайдера и (где API отдаёт поля) разбиение: input / output / reasoning, а также **cache read / cache write** (или эквиваленты вроде `cache_read_input_tokens`, `cache_creation_input_tokens` у Anthropic) — без путаницы с «ручными» оценками.

**Исследование (обязательный подэтап):**

- Зафиксировать для каждого поддерживаемого провайдера, какие поля приходят в `usage` (non-stream и stream-final chunk): OpenAI-совместимые (`prompt_tokens`, `completion_tokens`, расширения), Anthropic Messages (`usage` + `cache_*`), DeepSeek — что реально отдаётся в проде.
- **Hit/miss в буквальном виде** API обычно не отдаёт; отдаются счётчики **прочитанного из кеша** и **записи в кеш**. «Hit rate» при необходимости вычислять в UI как производную от последовательности запросов (документировать формулу и ограничения).

**Ориентир UX/модели данных (репозиторий-референс):** `/home/artem/reps/opencode` — нормализованное представление токенов ассистента, в т.ч. `tokens.cache.read` / `tokens.cache.write` в витрине (см. `packages/web/src/components/Share.tsx`, `packages/sdk/js/src/v2/gen/types.gen.ts` — поля `cache_read` / `cache_write` в cost/tokens).

#### Задача O.1 — Расширить `NormalizedUsage` и разбор `usage` в нормализаторах

**Сделать:** явные поля под cache read/write (и сырой «хвост» в `provider_metadata` при неизвестных ключах). Агрегировать по сессии в `SessionRunner` / budget events (сумма за прогон + последний чанк).

**Критерии:** разбор проверен на статичных примерах ответов API (mock payload / ручная проверка); неизвестные поля `usage` не теряются полностью (прозрачный хвост в метаданных или логе).

#### Задача O.2 — `ailit chat`: строка/панель usage в UI

**Сделать:** после ответа (и при стриминге — по мере обновления финального usage) показывать: **всего**, input, output, reasoning (если есть), cache read/write (если есть). Не дублировать сырой JSON в основной колонке — только компактные числа + expander «подробности».

**Критерии:** при mock-провайдере видны нули/заглушки; при реальном провайдере с полями — заполненные числа.

#### Задача O.3 — `ailit agent`: отображение токенов «по команде»

**Сделать:** подкоманда или флаг (например `ailit agent run … --usage-summary` или `ailit agent usage last`) читает последний JSONL / агрегаты процесса и печатает **тот же** нормализованный формат, что и чат (единый форматтер в `tools/ailit` или `agent_core`).

**Критерии:** один источник правды для чисел между chat и CLI.

**Чекпоинт этапа O:**

- Документ «какие поля чего значат» на 1 страницу в существующем плане или в `docs/` по решению команды (без обязательного нового README в корне).
- Чат и CLI согласованы по подписи метрик.

**Статус в репозитории (2026-04):** закрыты O.1–O.3 — `NormalizedUsage` + нормализация/cache, панель токенов в `ailit chat`, `ailit agent usage last`, `docs/usage-fields.md`.

---

### Этап P. TUI-режим `ailit` / `ailit agent` (чат в терминале, slash-команды)

**Цель:** полноценный текстовый интерфейс (TUI) для интерактива **как у чата**: ввод сообщений, история, вызов tools через тот же `SessionRunner`, без обязательного Streamlit.

**Best practices (референсы для анализа, не копипаста):**

- **Claude Code:** палитра slash-команд (`/model`, `/compact`, …), быстрый доступ к настройкам и контексту сессии.
- **OpenCode:** TUI/CLI паттерны сессии, идемпотентные команды, человекочитаемые статусы (см. их CLI и пакет `opencode`).

#### Задача P.1 — Выбор стека TUI и каркас подкоманды

**Сделать:** зафиксировать библиотеку (например `textual` / `prompt_toolkit` — критерий: поддержка вложенных экранов, клавиатура, Windows по желанию). `ailit tui` или `ailit chat --tui` — один вход, описанный в `--help`.

**Реализация в репозитории:** **Textual** (`>=0.47`), optional extra `[tui]` в `pyproject.toml`, вход **`ailit tui`** (без дублирования `ailit chat --tui`).

**Критерии:** запуск из любого каталога с project root; тот же merge конфига, что у `ailit chat`.

#### Задача P.2 — Реестр slash-команд `/`

**Сделать:** минимальный набор: `/help`, `/model`, `/max_turns`, `/project`, `/quit` + делегирование в общий обработчик (один класс регистрации команд, расширяемый плагинами позже).

**Критерии:** команды не попадают в LLM как пользовательский текст (фильтрация до отправки).

#### Задача P.3 — Подключение session loop и логов

**Сделать:** тот же `diag_sink` / JSONL процесса, что у Streamlit; опционально копирование последних строк в статус-бар TUI.

**Чекпоинт этапа P:**

- Инженер может пройти типовой сценарий «спросить модель + вызвать list_dir» только из TUI.

**Статус в репозитории (2026-04):** закрыты P.1–P.3 — `ailit tui` на **Textual** (`pip install -e '.[tui]'`), slash-реестр, тот же `SessionRunner` + `ensure_process_log("chat")` и строка usage в подзаголовке.

---

### Этап Q. Мульти-контекст в TUI (killer feature) + токены по контексту

**Цель:** в одном TUI-приложении переключаться между **несколькими именованными контекстами** (отдельные цепочки сообщений / привязка к `project_root` / `agent_id`), быстро сравнивать расход токенов и не смешивать истории.

**Модель контекста (минимум):**

- Короткое **имя** (≤ 20 символов, уникально в сессии TUI), отображаемое в заголовке/табе.
- Атрибуты: `project_root`, `agent_id`, опционально `workflow_ref`, метка времени последнего использования.
- Per-context **накопленный usage** (сумма `NormalizedUsage` по завершённым model.response в этом контексте).

#### Задача Q.1 — Хранилище контекстов в памяти + переключатель

**Сделать:** структура «стек контекстов», команды `/ctx new|list|switch|rename`, горячие клавиши по согласованию.

**Критерии:** переключение не теряет несохранённый ввод в буфере (явное правило в UX).

#### Задача Q.2 — Отображение usage по активному и сводка по всем

**Сделать:** статус-строка: активный контекст + последний запрос input/output/cache; команда `/ctx stats` — таблица по всем контекстам.

**Критерии:** числа согласованы с этапом O (тот же агрегатор).

#### Задача Q.3 (опционально) — Сохранение контекстов на диск

**Сделать:** сериализация под `.ailit/tui-sessions/` (gitignored) для восстановления после рестарта.

**Чекпоинт этапа Q:**

- Разработчик ведёт два проекта (два `project_root`) в одном TUI, переключается по имени, видит раздельный учёт токенов.

**Статус в репозитории (2026-04):** закрыты **Q.1–Q.3** — `TuiContextManager`, `/ctx list|new|switch|rename|stats|save`, Ctrl+Shift+Left/Right, накопленный usage на контекст, подзаголовок с **last** и **Σ**, `/ctx stats` как markdown-таблица, снимок в `~/.ailit/tui-sessions/state.json` (автосохранение при выходе из TUI), тесты `tests/test_tui_context_manager.py`, `tests/test_tui_context_stats.py`, `tests/test_tui_context_persistence.py`.

---

## 10. Сводная таблица этапов и критериев «готово этапа»

| Этап | Коротко | Готово когда |
|------|-----------|--------------|
| G | Глобальные пути + merge + G.3 | `agent`/`chat` не требуют клон для user secrets; проектный yaml ищется вверх по дереву |
| H | CLI `config` | пользователь настраивает без YAML |
| I | Подключение merge в runtime | один resolver везде |
| J | Human chat | нет обязательного JSON в основном UI |
| K | Task input + e2e | произвольный ввод + тест на внешнем tmp проекте |
| L | Teams | mailbox + tool + UI панель |
| M | Plugins MVP | установка + импорт skills |
| N | Лимиты цикла + UX | понятны `max_turns`, подсказки при исчерпании, диагностика шагов |
| O | Токены + cache usage | нормализация usage, чат и `ailit agent` показывают согласованные метрики |
| P | TUI чат + `/` | интерактив в терминале, slash-команды, тот же session loop |
| Q | Мульти-контекст TUI | именованные контексты, переключение, usage по контексту |

---

## 11. Риски и ограничения

1. **Юридически и технически** нельзя «встроить» несовместимую лицензию кода из `claude-code`; использовать как **архитектурный** референс и переписывать у себя.
2. **Плагины Claude** — форматы могут меняться; MVP должен быть **явно версионирован** (`ailit-plugin.yaml` schema version).
3. **URL в task** — обязательны лимиты размера, таймаут, политика SSRF (по умолчанию только https, запрет private IP).
4. **`max_turns` vs API** — путаница лимита шагов с `max_tokens` провайдера; этап **N** снижает риск за счёт подсказок в `ailit chat`, но документация продукта всё равно должна явно разделять понятия.
5. **Сырой wire-format моделей** (DSML и т.п.) может дублироваться в `content` при наличии структурных `tool_calls`; без санитайза и тестов на нормализацию human chat деградирует (см. `agent_core.normalization.content_sanitize`, этап J/O).

---

## 12. Правила закрытия этапа (git, установка, команды для пользователя)

Эти правила **обязательны** для работы по данному документу с этого момента и для всех будущих этапов (в т.ч. N.1–N.3, O.1–O.3, P.1–P.3, Q.1–Q.3).

1. **Git:** после каждого завершённого этапа (или логически завершённой подзадачи из §9) — **отдельный коммит** в репозитории `ailit-agent` с сообщением, из которого ясно, какой этап/задача закрыт (например `feat(ailit): H.2 config set …`).
2. **Сообщение пользователю по завершении этапа** всегда должно включать два блока команд (кроме случаев, когда этап не затрагивает CLI вообще — тогда указать это явно):
   - **Установка / обновление из исходников** — по умолчанию **`./scripts/install`**: editable-установка в `.venv` репозитория и **симлинк** `~/.local/bin/ailit` → `<клон>/.venv/bin/ailit`, чтобы вызывать `ailit` из любого каталога **без** `source` (нужен `~/.local/bin` в `PATH`; на многих Linux он уже добавлен). Отключить симлинк: `AILIT_INSTALL_NO_SHIM=1 ./scripts/install`.
   - **Проверка «как у уже установленного приложения»** — команды в предположении, что `ailit` в `PATH` (через shim или активацию `.venv`), **без** `PYTHONPATH=tools` и **без** `python3 -m ailit.cli`, если только этап специально не про разработку без установки.
3. **Допустимая сноска для контрибьюторов:** если нужно прогнать что-то без установки пакета, отдельной строкой можно дать эквивалент с `PYTHONPATH=tools python3 -m ailit.cli …` из корня репозитория — но **основной** сценарий проверки остаётся установленным `ailit` после `./scripts/install`.

Пример формулировки установки (корень репозитория):

```bash
cd /путь/к/клону/ailit-agent
./scripts/install
# при необходимости один раз: export PATH="${HOME}/.local/bin:${PATH}"
```

Эквивалент вручную (тот же порядок зависимостей):

```bash
cd /путь/к/клону/ailit-agent
pip install -e .
pip install -e '.[dev]'
pip install -e '.[chat]'
```

Пример проверки уже реализованных на момент публикации правил подкоманд конфигурации:

```bash
ailit config path
ailit config show
ailit --help
```

---

## 13. Следующий шаг для команды

По документу §9 на **2026-04** в коде закрыты этапы **G** (включая **G.3**), **H**, **I**, **J**, **K**, **L**, **M**, **N**, **O**, **P**, **Q** — см. строки «**Статус:** выполнено» и «**Статус в репозитории**» у соответствующих задач и чекпоинтов.

Дальнейшая работа **не выводится автоматически из этого файла**: нужны **research** и **постановка** новых этапов (отдельный PR в план, ветка `plan/project-orchestrator-strategy.md`, задачи из `plan/agent-core-workflow.md` и т.д.) — см. также [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

Вернуться к оглавлению: [`docs/INDEX.md`](../docs/INDEX.md)
