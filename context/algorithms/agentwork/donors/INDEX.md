# Donors / внешние идеи

Пакет описывает **внутреннюю** реализацию ailit-agent. Отдельный donor-research под AgentWork не проводился.

| Статус | Источник | Комментарий |
|--------|----------|-------------|
| **Not researched** | Репозитории из таблицы «Локальные репозитории» в `.cursor/rules/project/project-workflow.mdc` | При полноценном target-doc можно пройти Claude Code / OpenCode на предмет loop+tools+compaction и занести сюда Taken/Rejected. |
| **Internal SoT** | `tools/agent_core/runtime/subprocess_agents/work_agent.py`, `work_orchestrator.py` | Фактическое поведение AgentWork. |
