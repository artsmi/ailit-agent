#!/usr/bin/env python3
# flake8: noqa: E501
"""Generate start_feature_execution_plan.md from frozen target_doc artifacts."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "context/artifacts/target_doc"
OUT = REPO / "context/algorithms/agent-memory/start_feature_execution_plan.md"

RESEARCH_WAVES: dict = {
    "produced_by": "20_target_doc_synthesizer",
    "target_topic": "agent-memory",
    "synthesis_file": "context/artifacts/target_doc/synthesis.md",
    "research_waves": [
        {
            "wave_id": "current_repo_1",
            "parallel": True,
            "depends_on": [],
            "barrier": "all_jobs_completed",
            "jobs": [
                {
                    "job_id": "cr_agent_memory_entrypoints_cli",
                    "kind": "current_repo",
                    "agent": "19_current_repo_researcher",
                    "research_question": (
                        "Entrypoints AgentMemory, CLI memory init, broker subprocess vs in-process."
                    ),
                    "output_file": (
                        "context/artifacts/target_doc/current_state/agent_memory_entrypoints_cli.md"
                    ),
                },
                {
                    "job_id": "cr_agent_work_memory_payload",
                    "kind": "current_repo",
                    "agent": "19_current_repo_researcher",
                    "research_question": (
                        "AgentWork memory.query_context payload, caps, grants, agent_memory_result."
                    ),
                    "output_file": (
                        "context/artifacts/target_doc/current_state/agent_work_memory_integration.md"
                    ),
                },
                {
                    "job_id": "cr_agent_memory_query_pipeline",
                    "kind": "current_repo",
                    "agent": "19_current_repo_researcher",
                    "research_question": (
                        "AgentMemoryQueryPipeline: W14 commands, repair, runtime states vs journal."
                    ),
                    "output_file": (
                        "context/artifacts/target_doc/current_state/agent_memory_query_pipeline.md"
                    ),
                },
                {
                    "job_id": "cr_pag_kb_memory_persistence",
                    "kind": "current_repo",
                    "agent": "19_current_repo_researcher",
                    "research_question": "PAG/KB models, sqlite paths, A/B/C/D node ids.",
                    "output_file": (
                        "context/artifacts/target_doc/current_state/pag_kb_memory_state_models.md"
                    ),
                },
                {
                    "job_id": "cr_memory_journal_trace_chat",
                    "kind": "current_repo",
                    "agent": "19_current_repo_researcher",
                    "research_question": "Journal, trace, compact.log, event_name contract vs D-OBS.",
                    "output_file": (
                        "context/artifacts/target_doc/current_state/memory_journal_trace_observability.md"
                    ),
                },
                {
                    "job_id": "cr_tests_plan14_runtime_contracts",
                    "kind": "current_repo",
                    "agent": "19_current_repo_researcher",
                    "research_question": "Pytest names and alignment with plan/14 vs repo reality.",
                    "output_file": (
                        "context/artifacts/target_doc/current_state/tests_plan14_alignment.md"
                    ),
                },
            ],
        },
        {
            "wave_id": "donors_1",
            "parallel": True,
            "depends_on": ["current_repo_1"],
            "barrier": "all_jobs_completed",
            "jobs": [
                {
                    "job_id": "donor_opencode_typed_events",
                    "kind": "donor_repo",
                    "agent": "14_donor_researcher",
                    "donor_repo_path": "/home/artem/reps/opencode",
                    "research_question": (
                        "Как donor регистрирует typed session или bus events и связывает type с "
                        "payload schema; применимо ли к external-protocol AgentMemory без копирования кода."
                    ),
                    "output_file": (
                        "context/artifacts/target_doc/donor/opencode_typed_events_for_memory_protocol.md"
                    ),
                },
                {
                    "job_id": "donor_claude_code_agent_memory_scopes",
                    "kind": "donor_repo",
                    "agent": "14_donor_researcher",
                    "donor_repo_path": "/home/artem/reps/claude-code",
                    "research_question": (
                        "Как donor разделяет path ownership и scopes в agent memory tool, что "
                        "переносимо в контракт AgentWork-owned request vs AgentMemory-owned writes?"
                    ),
                    "output_file": (
                        "context/artifacts/target_doc/donor/claude_code_agent_memory_ownership.md"
                    ),
                },
                {
                    "job_id": "donor_letta_memory_compact_limits",
                    "kind": "donor_repo",
                    "agent": "14_donor_researcher",
                    "donor_repo_path": "/home/artem/reps/letta",
                    "research_question": (
                        "Как donor описывает memory blocks с metadata и лимитами размера, применимо ли "
                        "к compact agent_memory_result и event payloads?"
                    ),
                    "output_file": (
                        "context/artifacts/target_doc/donor/letta_memory_blocks_compact_pattern.md"
                    ),
                },
            ],
        },
    ],
}


def _read(name: str) -> str:
    return (ART / name).read_text(encoding="utf-8")


def _block(title: str, body: str) -> str:
    # Вложенные ``` в копируемых артефактах — используем четыре backtick-а.
    return f"\n## {title}\n\n````markdown\n{body}\n````\n"


def main() -> None:
    bodies = {n: _read(n) for n in (
        "human_review_packet.md",
        "start_feature_handoff.md",
        "reader_review.md",
        "open_gaps_and_waivers.md",
        "source_request_coverage.md",
        "target_doc_quality_matrix.md",
        "target_algorithm_draft.md",
    )}
    waves_json = json.dumps(RESEARCH_WAVES, ensure_ascii=False, indent=2)

    head = """# План выполнения start-feature / start-fix: AgentMemory

Produced by: 24_start_feature_execution_planner

Этот файл — **долгоживущий** артефакт в `context/algorithms/agent-memory/`. Каталог
`context/artifacts/target_doc/` может быть удалён; ниже в приложениях перенесены **полные копии**
ключевых документов gate и исполненных research waves (JSON), чтобы не потерять контекст.

## Назначение

- Дать `01_orchestrator` / человеку **порядок работ** после утверждения канона.
- Зафиксировать **риски** неверной реализации и типичные отклонения от контракта.
- Согласовать с pipeline: читать вместе с `INDEX.md`, `runtime-flow.md`, …; slices S1–S5 не смешивать.

## Входы после удаления `context/artifacts/target_doc`

Использовать:

1. Пакет `context/algorithms/agent-memory/*.md` (канон поведения).
2. **Этот файл** — план, риски и замороженные копии gate/research/draft.

## Порядок выполнения для start-feature / start-fix

| Шаг | Кто | Действие | Зависит от |
|-----|-----|----------|------------|
| 1 | Человек / `01` | Прочитать `INDEX.md`, этот план, приложения A–H. | — |
| 2 | `02_analyst` | ТЗ и контракт задачи только в терминах канона и OR-id из приложения G. | шаг 1 |
| 3 | `06_planner` | Разбить на задачи по **S1→S5** (приложение B); одна задача не покрывает весь граф + CLI + grants. | шаг 2 |
| 4 | `08_developer` | Реализация slice; не подменять `plan/14` каноном поведения (см. приложение B Forbidden). | шаг 3 |
| 5 | `11_test_runner` | Pytest имена из `failure-retry-observability.md` §Acceptance; venv проекта. | шаг 4 |
| 6 | `09_code_reviewer` | Проверка границ payload LLM, grants, journal compact. | шаг 4–5 |
| 7 | `13_tech_writer` | Обновление канона только при **намеренном** сдвиге целевого поведения после OK. | по необходимости |

Рекомендуемый **технический** порядок slices (см. приложение B): **S1 → S3 → S2 → S5 → S4**
(сначала контракт команд и ссылок, затем события, затем статусы результата, затем CLI UX),
если `06` не видит блокирующих зависимостей между S2 и S3.

## Риски и некорректная реализация

| ID | Риск | Некорректное проявление | Проверка / смягчение |
|----|------|-------------------------|---------------------|
| R1 | Широкий PR | Один PR «весь AgentMemory» | План `06` режет по S1–S5; ревью отклоняет scope |
| R2 | LLM пишет граф напрямую | Рёбра без runtime validation | Код должен отклонять; тесты на reject path |
| R3 | CoT / raw prompts в compact | Утечка в journal/stdout | Grep/markers; `prompts.md` anti-patterns |
| R4 | Игнор `agent_memory_result` | Continuation по top-level mirror | Интеграционные тесты AgentWork (см. приложение G) |
| R5 | Grants не enforced | Чтение файлов вне slice | Slice S2/S5 + тесты на read path |
| R6 | A-id дрейф | Два шаблона A node_id | Явная миграция/один канон перед массовой индексацией |
| R7 | Неверные pytest имена | Ссылки на несуществующие `*_prompt_contains_*` | Список из `failure-retry-observability.md` |
| R8 | CLI `blocked` смешан с `aborted` | Неверный UX при LLM fail | Slice S4; сравнение с приложением A backlog |
| R9 | События без `event_type` / schema | Ломается Desktop | Slice S2; discriminant обязателен |
| R10 | Repair loop >1 | Нарушение bounded repair | Юнит-тесты pipeline |

## Соответствие target-doc pipeline

- `20` → research waves (приложение H) → `19`/`14` → `20` → `21` → `22` → `23` → **`24`** (этот документ) → user approval (`18`).
- `24` не запускает других агентов; результат — только этот файл в `context/algorithms/`.

---
"""
    chunks: list[str] = [head]
    order = (
        ("Приложение A — полная копия `human_review_packet.md`", "human_review_packet.md"),
        ("Приложение B — полная копия `start_feature_handoff.md`", "start_feature_handoff.md"),
        ("Приложение C — полная копия `reader_review.md`", "reader_review.md"),
        ("Приложение D — полная копия `open_gaps_and_waivers.md`", "open_gaps_and_waivers.md"),
        ("Приложение E — полная копия `source_request_coverage.md`", "source_request_coverage.md"),
        ("Приложение F — полная копия `target_doc_quality_matrix.md`", "target_doc_quality_matrix.md"),
        ("Приложение G — полная копия `target_algorithm_draft.md`", "target_algorithm_draft.md"),
    )
    for title, key in order:
        chunks.append(_block(title, bodies[key]))
    chunks.append(
        "\n## Приложение H — исполненные research waves (`research_waves.json`)\n\n"
        "Снимок соответствует `wave_execution_report.md` и не должен затираться пустым массивом "
        "после barrier.\n\n```json\n"
        f"{waves_json}\n```\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(chunks), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
