# ailit-agent

Репозиторий CLI и runtime-ядра **`ailit`**: пакеты в каталоге **`ailit/`** — `ailit_base`, `agent_work`, `agent_memory`, `ailit_runtime`, `ailit_cli`, `workflow_engine`; глобальный конфиг; продуктовый UI **`ailit desktop`** (Linux); команда **`ailit agent`**; пример дерева конфига — [`ailit/config-example/STRUCTURE.md`](ailit/config-example/STRUCTURE.md).

## Статус разработки (2026-04)

| Область | Состояние |
|---------|-----------|
| **Target algorithm: AgentMemory (канон для start-feature)** | **Утверждён (2026-05-03):** [`context/algorithms/agent-memory/INDEX.md`](context/algorithms/agent-memory/INDEX.md) — целевой алгоритм, LLM protocol, граф ссылок, события, failure/retry; исторический runtime-план остаётся в [`plan/14-agent-memory-runtime.md`](plan/14-agent-memory-runtime.md). |
| **Workflow 14 (AgentMemory planner command contract)** | **Суперсeding:** [`plan/14-agent-memory-planner-command-contract.md`](plan/14-agent-memory-planner-command-contract.md) — историческая ветка G14.1–G14.6; **нормативный** runtime — [`plan/14-agent-memory-runtime.md`](plan/14-agent-memory-runtime.md) (W14R). |
| **Workflow 14 (AgentMemory runtime W14, command protocol)** | **Закрыт (G14R.0–G14R.11):** [`plan/14-agent-memory-runtime.md`](plan/14-agent-memory-runtime.md) — W14: `plan_traversal` / `finish_decision`, `payload.agent_memory_result`, без G13 `requested_reads`/`c_upserts` в планере; G14R.6 legacy C quarantine; интеграционные тесты `test_g14r11_w14_integration.py`. |
| **Workflow 13 (AgentMemory contract recovery)** | **Закрыт (G13.0–G13.8):** [`plan/13-agent-memory-contract-recovery.md`](plan/13-agent-memory-contract-recovery.md) — `PagGraphWriteService`, `memory.query_context` + `MemoryLlmOptimizationPolicy`, `memory.change_feedback`, C-идентичность, link claims, единый desktop graph store, regression (`tests/test_g13_*.py`, `test_g13_agent_memory_contract_integration.py::test_llm_to_c_edge_trace_desktop_parser_path`, `pagGraphSessionStore`); **финальные схемы** — `context/proto/runtime-event-contract.md`. |
| **Workflow 12 (PAG trace + desktop sync)** | **Архив (исходная попытка, пересечение с W13):** [`plan/12-pag-trace-delta-desktop-sync.md`](plan/12-pag-trace-delta-desktop-sync.md) — ввод дельт trace / `graph_rev` / desktop; **фактический сквозной runtime/LLM/desktop контракт** закреплён в W13. Канон процесса: [`.cursor/rules/project-workflow.mdc`](.cursor/rules/project-workflow.mdc). |
| Актуальная стратегия продукта | [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md): этапы **DP-1…DP-5** закрыты; проект перешёл в **этап тестирования** (сбор багов → фиксы). |
| Bash / shell в runtime | [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md): **B–E**, **D.4**, **F.1–F.2** — `run_shell` и file tools включены по умолчанию, `bash:` в `project.yaml`, **H** — сессионный shell позже. |
| [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md) | Этапы **G–Q** закрыты; документ архивен как ориентир закрытой ветки. |
| Токен-экономия и внешняя память (ветка) | **Порядок:** [`plan/workflow-token-economy-recipe.md`](plan/workflow-token-economy-recipe.md) (TE) → [`plan/workflow-hybrid-memory-mcp.md`](plan/workflow-hybrid-memory-mcp.md) (H0–H4) → [`plan/workflow-memory-3.md`](plan/workflow-memory-3.md) (M3, закрыто) → [**`plan/workflow-memory-4.md`**](plan/workflow-memory-4.md) (**M4:** runtime‑память + loop‑guards; M4‑1.2 / M4‑3.2 закрыты). |
| Режимы/permissions (как у доноров) | [**`plan/5-workflow-perm.md`**](plan/5-workflow-perm.md) — **perm‑5** реализован (классификатор, enforcement, UI not_sure, `ailit agent run --perm-tool-mode`, срез `subsystems.perm_mode`). |
| **Чтение + память (read‑6)** | **Закрыто:** протокол grep→range-read, `read_symbol` (.py), метрика duplicate read, KB-first hints при `memory.enabled`, прозрачность N/100 в чате, R4.4 digest после `kb_fetch`. |
| **Граф архитектуры проекта + GUI «ailit memory» (workflow 7)** | [**`plan/7-workflow-project-architecture-graph.md`**](plan/7-workflow-project-architecture-graph.md) — **закрыто:** PAG, автоиндексация, `ailit memory`, `AgentMemory` / `AgentWork`, post-edit sync. **Индексация:** merge C/B/A при sync, W14 summaries без привязки к goal — [`context/proto/pag-stable-indexing.md`](context/proto/pag-stable-indexing.md). |
| **Low-level agents runtime + broker supervisor (workflow 8)** | [**`plan/8-agents-runtime.md`**](plan/8-agents-runtime.md) — **закрыто:** этапы **G8.0–G8.8** (supervisor/broker/subprocess agents, `MemoryGrant` enforcement, desktop viewer + trace tab, `scripts/install` с `systemd --user`, e2e readiness/деградации). |
| **Standalone UI `ailit desktop` (workflow 9)** | [**`plan/9-ailit-ui.md`**](plan/9-ailit-ui.md) — **закрыт (G9.9):** Linux-only Electron, `ailit project add`, runtime bridge, отчёты MD/JSON, PAG graph. Чеклист: [`docs/g9-9-release-checklist.md`](docs/g9-9-release-checklist.md). |
| **Context Ledger + Memory 3D highlights (workflow 10)** | [**`plan/10-context-ledger-memory-highlights.md`**](plan/10-context-ledger-memory-highlights.md) — **закрыто (G10.8):** `AgentMemory` actor, Context Fill, D-level compact/restore и Memory 3D highlights по нодам, реально попавшим в prompt. **Расширение (G16):** W14 `memory.w14.graph_highlight` в trace + 3D (см. `context/proto/runtime-event-contract.md`, `pag_graph_trace.py`, `pagHighlightFromTrace.ts`). |
| **AgentMemory LLM + journal (workflow 11)** | [**`plan/11-agent-memory-llm-journal.md`**](plan/11-agent-memory-llm-journal.md) — **закрыто (G11.9):** global `AgentMemory`, LLM A→B→C loop, query-driven PAG growth, journal UI и real multi-project Memory 3D. |
| **Desktop memory graph 3dmvc (plan 18)** | **G1–G4 в коде (2026-05-13):** [`plan/18-desktop-memory-graph-3dmvc.md`](plan/18-desktop-memory-graph-3dmvc.md) — **G4** (**D-PERF-1**): bounded trace replay + `desktop.trace.replay.*`, throttle `desktop.graph.refresh` / C2, pair-log batch + `desktop.pairlog.append`, компактные `desktop.pag_slice.*` в main; канон — [`context/algorithms/desktop/realtime-graph-client.md`](context/algorithms/desktop/realtime-graph-client.md). Ручной smoke §6 плана — **verification_gap** / `blocked_by_environment` в среде агентов (как для G3). |
| **Desktop stack: чат, freeze, PAG rev (target-doc Cycle D)** | **Утверждён (2026-05-13):** [`context/algorithms/desktop-stack/INDEX.md`](context/algorithms/desktop-stack/INDEX.md) — submit/trace/PAG rev, ветка `chat_logs_enabled`, диагностика OR-D6; план — [`plan/19-desktop-stack-chat-freeze-pag-trace.md`](plan/19-desktop-stack-chat-freeze-pag-trace.md). **G19.5:** в `desktop/` зелёные `npm run test`, `npm run lint`, `npm run typecheck`; статическая проверка ветки `chat_logs_enabled` не отключает durable/live trace и subscribe после `broker_connect` (см. `DesktopSessionContext.tsx`). Ручной smoke из канона §Commands — у оператора с Desktop или `blocked_by_environment` без подмены на «passed». |

## Как работать по проекту

1. **AgentMemory / PAG / desktop (Workflow 14 W14R):** [`plan/14-agent-memory-runtime.md`](plan/14-agent-memory-runtime.md) — **закрыт** (G14R.0–G14R.11). Старый план [`plan/14-agent-memory-planner-command-contract.md`](plan/14-agent-memory-planner-command-contract.md) — **архив/суперсeded** W14R. **Workflow 13** [`plan/13-agent-memory-contract-recovery.md`](plan/13-agent-memory-contract-recovery.md) — **закрыт**; канон контракта: `context/proto/runtime-event-contract.md` (W13 + секция W14R journal), карта UI: `context/arch/visual-monitoring-ui-map.md` (экран J). Workflow 12 — архивная ветка до recovery.
2. **Workflow:** обязательный порядок задач и правило «конец workflow → research и постановка» — в [`.cursor/rules/project-workflow.mdc`](.cursor/rules/project-workflow.mdc).
3. **Стратегия и критерии этапов:** [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md) (актуально); bash/shell — [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md); закрытая ветка — [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md).
4. **Workflow 11 (`AgentMemory LLM + journal`)** закрыт по [`plan/11-agent-memory-llm-journal.md`](plan/11-agent-memory-llm-journal.md). **Workflow 13** закрыт (см. п.1). Workflow 10 закрыт по [`plan/10-context-ledger-memory-highlights.md`](plan/10-context-ledger-memory-highlights.md). Токен-экономия и память: M3 закрыта; runtime M4 — [`plan/workflow-memory-4.md`](plan/workflow-memory-4.md). Сводка M3: [`docs/ailit-ai-memory-implementation.md`](docs/ailit-ai-memory-implementation.md).
5. **Оглавление документации:** [`docs/INDEX.md`](docs/INDEX.md).

## Установка и быстрая проверка

Из корня клона:

```bash
./scripts/install          # prod: venv в ~/.local/share/ailit (см. план DP-5)
# или:  ./scripts/install dev    # editable + .venv в клоне
# при необходимости: export PATH="${HOME}/.local/bin:${PATH}"
ailit --help
```

Начиная с [`workflow 8`](plan/8-agents-runtime.md), `scripts/install` должен также устанавливать и обновлять user-service runtime supervisor:

```bash
systemctl --user status ailit.service
journalctl --user -u ailit.service -f
```

### `ailit desktop` и проекты (workflow 9)

- Реестр проектов **глобальный**: `~/.ailit/config.yaml` (active) и `~/.ailit/projects/<project_id>/config.yaml` на проект. В каталоге репозитория **не** создаётся `.ailit` для registry.
- Регистрация: `ailit project add` (текущий каталог) или `ailit project add /abs/path`.
- Индексация PAG для памяти: `ailit memory index --project-root PATH` (подсказка печатается после `project add`).
- Запуск UI: после `./scripts/install` — `ailit desktop`; без собранного AppImage — `ailit desktop --dev` из клона (нужен Node.js, каталог `desktop/`).
- Runtime: `ailit runtime status` (если сокета нет — в stderr подсказки `systemctl` / `journalctl` для `ailit.service`).

**Диагностика desktop:** нет бинарника в `~/.local/share/ailit/desktop/ailit-desktop.AppImage` — повторить `./scripts/install`, либо `ailit desktop --dev`. Переменная `AILIT_INSTALL_PREFIX` задаёт префикс, как в `scripts/install`.

Тесты (без e2e, если в окружении нет зависимостей вроде `httpx` для полного прогона):

```bash
./.venv/bin/python -m pytest tests/ -q --ignore=tests/e2e/
```
