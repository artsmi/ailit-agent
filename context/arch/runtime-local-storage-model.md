# Runtime Local Storage Model

## Назначение

Зафиксировать local-first модель данных runtime `ailit-agent`, чтобы:

- UI и resume опирались на предсказуемые файлы;
- event log оставался источником истины об исполнении;
- `context/*` не подменялся runtime артефактами.

## Главный принцип

Runtime persistence — это **append-friendly** локальное хранилище рядом с проектом.

`context/*` остается canonical knowledge.  
Runtime хранит только факты исполнения, проекции и телеметрию.

## Корневой каталог данных

Рекомендуемый корень:

```text
<project_root>/.ailit/
```

Почему так:

- данные явно отделены от git-tracked `context/*`;
- проще сделать `.gitignore` и operator hygiene;
- путь стабилен для UI и CLI.

Альтернатива для multi-repo workspace (будущее расширение): `XDG_STATE_HOME/ailit/...`, но базовый контракт этапа фиксирует **project-local** `.ailit/` как default.

## Идентификаторы

Минимальный набор идентификаторов:

- `run_id`: одно исполнение (одна сессия operator-facing run);
- `workflow_id`: логический workflow;
- `workflow_revision`: версия определения workflow (hash или semver);
- `stage_id`, `task_id`: элементы графа workflow layer;
- `agent_id`: логическая роль агента;
- `session_id`: provider-facing session unit внутри `run_id` (может быть 1:1 или 1:N).

## Дерево каталогов (канонический каркас)

```text
.ailit/
  runs/
    <run_id>/
      manifest.json
      state.json
      events.jsonl
      snapshots/
        <snapshot_id>.json
      artifacts/
        index.json
        blobs/
          <sha256>
      telemetry/
        usage.jsonl
        cost.jsonl
      episodic/
        summaries.jsonl
      workflows/
        resolved.json
        definitions/
          <workflow_id>@<workflow_revision>.json
```

## Что хранится и зачем

### `manifest.json`

Стабильные метаданные run:

- `schema_version`;
- `created_at`, `finished_at` (optional);
- `project_root` (абсолютный путь, только для локального UX);
- `workflow_id`, `workflow_revision`;
- `git` metadata (optional, best-effort): commit, dirty flag;
- `config_fingerprint` (hash нормализованного runtime config).

### `state.json`

**Проекция** для UI/resume:

- текущий `stage_id`, `task_id`;
- статусы: running/blocked/paused/failed/succeeded;
- последние известные counters: tokens, cost estimates;
- указатели: `last_event_id`, `last_snapshot_id`;
- `blocked_reason` структурированно (не свободный текст).

Инвариант: `state.json` всегда может быть восстановлен из `events.jsonl` + `manifest.json` (пусть даже медленно).

### `events.jsonl`

Источник истины по исполнению:

- append-only;
- одна строка = одно событие JSON;
- строгий envelope + payload (см. `../proto/runtime-event-contract.md`).

### `snapshots/`

Периодические срезы для:

- быстрого старта UI;
- дешевого resume;
- отладки без полного replay.

Инвариант: snapshot — **денормализованная проекция**, а не второй источник истины.

### `artifacts/`

Key artifacts и большие блобы:

- `index.json` хранит метадату (имя, тип, hash, ссылки на producer events);
- `blobs/<sha256>` хранит содержимое (content-addressed).

### `telemetry/`

Нормализованная телеметрия:

- `usage.jsonl`: tokens, latency, provider ids;
- `cost.jsonl`: нормализованные cost signals (даже если часть полей estimate).

### `episodic/summaries.jsonl`

Короткие episodic summaries, которые:

- помогают operator memory;
- **не** заменяют `context/*`;
- всегда имеют ссылки на первичные события/артефакты.

### `workflows/`

Workflow definitions как runtime видит их:

- `resolved.json`: итоговая конфигурация после project layer merge;
- `definitions/*`: копия/нормализованный snapshot определения на момент run.

Инвариант: это не замена репозиторных workflow-определений, а **materialized** версия для воспроизводимости.

## Форматы и совместимость

- JSON файлы: UTF-8, стабильные ключи, явные `null` только если поле семантически optional.
- JSONL: одна запись = один JSON объект без pretty printing.
- Версионирование: `schema_version` в `manifest.json` + в event envelope.

## Запись и целостность

Минимальные требования к реализации (когда появится код):

- атомарная запись через temp+rename для `state.json` и `manifest.json`;
- fsync policy: best-effort на event boundaries (операторский режим);
- crash recovery: UI умеет предложить replay последних событий.

## Граница с `context/*`

Запрещено:

- записывать runtime state в `context/*` автоматически;
- использовать snapshots как canonical knowledge.

Разрешено:

- явный human-driven `promote to context` как отдельный workflow (не часть базового storage model).

## Связанные документы

- [`state-and-persistence.md`](state-and-persistence.md)
- [`../proto/runtime-event-contract.md`](../proto/runtime-event-contract.md)
- [`visual-monitoring-ui-map.md`](visual-monitoring-ui-map.md)
- [`../INDEX.md`](../INDEX.md)
