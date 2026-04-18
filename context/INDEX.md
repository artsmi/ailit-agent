# Context Index

## Назначение

`context/*` хранит каноническое знание о текущей платформенной стратегии `ailit-agent`.

На `Этапе 1` здесь зафиксированы:

- трехслойная архитектура;
- layout репозитория;
- границы state and persistence;
- внешний workflow shell;
- roadmap интерфейсов целевой платформы.

## Разделы

### `arch/`

- `system-overview.md`
- `repository-layout.md`
- `state-and-persistence.md`

### `proto/`

- `external-workflow-and-cli.md`
- `target-platform-interfaces-roadmap.md`

## Главный принцип

`context/*` остается canonical source of truth о проекте.  
Runtime state и events не подменяют эти документы.
