"""Deterministic continuity rendering helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .schema import canonical_json_dumps

CONTINUITY_GENERATED_HEADER = "# AgentMemory continuity (generated)\n\n"
CONTINUITY_BRANCH_PREFIX = "# Branch: "
CONTINUITY_EMPTY_STATE_TEXT = "No confirmed project records found for this branch.\n"


def _sort_project_records(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(records, key=lambda item: item["id"])


def render_continuity_markdown(
    records: Sequence[Dict[str, Any]],
    *,
    branch: str,
) -> str:
    lines: List[str] = [CONTINUITY_GENERATED_HEADER, f"{CONTINUITY_BRANCH_PREFIX}{branch}\n\n"]
    if not records:
        lines.append(CONTINUITY_EMPTY_STATE_TEXT)
        return "".join(lines)

    for record in _sort_project_records(records):
        lines.append("```json\n")
        lines.append(canonical_json_dumps(record))
        lines.append("\n```\n")
    return "".join(lines)


__all__ = [
    "CONTINUITY_GENERATED_HEADER",
    "CONTINUITY_BRANCH_PREFIX",
    "CONTINUITY_EMPTY_STATE_TEXT",
    "render_continuity_markdown",
]
