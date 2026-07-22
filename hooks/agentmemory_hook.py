#!/usr/bin/env python3
"""Dispatcher hook for AgentMemory M0."""

from __future__ import annotations

import json
import sys


FAILURE_OUTPUT = "agentmemory hook input rejected."


def fail(message: str = FAILURE_OUTPUT) -> None:
    sys.stderr.write(message)
    sys.exit(2)


def load_event_payload() -> dict:
    raw = sys.stdin.read()

    def reject_non_standard_json_constant(_constant: str) -> None:
        raise ValueError("invalid JSON constant")

    try:
        payload = json.loads(raw, parse_constant=reject_non_standard_json_constant)
    except (json.JSONDecodeError, ValueError):
        fail()

    if not isinstance(payload, dict):
        fail()

    return payload


def format_session_start_response() -> str:
    return json.dumps(
        {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "AgentMemory M0 hook active. "
                    "This probe does not restore or persist memory."
                ),
            },
        },
        separators=(",", ":"),
    )


def format_pre_compact_response() -> str:
    return json.dumps({"continue": True}, separators=(",", ":"))


def run() -> None:
    if len(sys.argv) != 2:
        fail()

    action = sys.argv[1]
    payload = load_event_payload()
    hook_event_name = payload.get("hook_event_name")

    if action == "session-start":
        if hook_event_name != "SessionStart":
            fail()
        sys.stdout.write(format_session_start_response())
        return

    if action == "pre-compact":
        if hook_event_name != "PreCompact":
            fail()
        sys.stdout.write(format_pre_compact_response())
        return

    fail()


if __name__ == "__main__":
    run()
