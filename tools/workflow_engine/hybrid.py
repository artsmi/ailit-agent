"""Hybrid режим: policy markdown только как метаданные (без исполнения в коде)."""

from __future__ import annotations

from typing import Any

from .graph import Workflow


def hybrid_event_payload(workflow: Workflow) -> dict[str, Any]:
    """Поля для события `project.policy.ref` (MVP)."""
    return {
        "hybrid": workflow.hybrid,
        "policy_ref": workflow.policy_ref,
        "workflow_id": workflow.workflow_id,
    }
