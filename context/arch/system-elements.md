# Процессы ОС и верхнеуровневые элементы

Согласовано с инвариантом «один долгоживущий процесс ОС — один архитектурный элемент» (см. правило `architecture-os-process-invariant.mdc`). Краткосрочные вызовы CLI — одно PID-пространство на инвокацию.

| ID | Элемент | Точка входа / триггер | Ключевые пути |
|----|---------|----------------------|---------------|
| P1 | **CLI `ailit`** (короткоживущие команды) | `pyproject.toml` → `ailit.cli:main` → `tools/ailit/cli.py` | Подкоманды регистрируются из `register_*_parser` (`runtime_cli`, `project_cli`, `desktop_cli`, …) и встроенных парсеров (`doctor`, `session`, `chat`, `tui`, `agent`, `memory`, …). |
| P2 | **Runtime supervisor** | `ailit runtime supervisor` (`tools/ailit/runtime_cli.py` → `run_supervisor_server`) | Долгоживущий; user unit из `scripts/install`. |
| P3 | **Broker и worker-процессы** | Под P2: `ailit runtime broker` (internal), дочерние процессы агентов из `tools/agent_core/runtime/` | Отдельные PID; см. [`../proto/supervisor-json-socket.md`](../proto/supervisor-json-socket.md) и broker Unix socket. UC 2.4 (Work → Memory pathless, пост-guards в `memory_agent`): trace, инжект и W14-ветки — [`../proto/broker-memory-work-inject.md`](../proto/broker-memory-work-inject.md). |
| P4 | **Desktop Electron** | `desktop/package.json` `main`; dev: `npm run dev`; prod: AppImage | `desktop/src/main/`, `desktop/src/renderer/`; UI — Chromium renderer. |
| P5 | **TUI** | `ailit tui`, ветка `ailit agent` без `run` — Textual (`[project.optional-dependencies]` `tui`) | Зависимость: `pip install -e '.[tui]'`. |
| P6 | **Streamlit / legacy chat** | `ailit chat` → Streamlit (`[project.optional-dependencies]` `chat`) | `tools/ailit/chat_app.py` и связанные модули. |

## Исходящие связи

- P4 → P2/P3: IPC из main-процесса к `supervisor.sock` и broker socket; вызовы `ailit` для PAG slice (см. proto).
- P1 → P2: клиентские команды `ailit runtime status|brokers|stop-broker` и т.д.
- Тесты: `tests/conftest.py` изолируют пути `AILIT_*` от пользовательского `~/.ailit`.

Доменные детали PAG / Memory 3D / W14 — в [`desktop-pag-graph-snapshot.md`](desktop-pag-graph-snapshot.md) и [`w14-graph-highlight-m1.md`](w14-graph-highlight-m1.md); этот файл — каркас learn по процессам.
