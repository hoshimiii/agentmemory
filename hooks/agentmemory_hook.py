#!/usr/bin/env python3
"""Dispatcher hook for AgentMemory M0."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
from pathlib import Path


FAILURE_OUTPUT = "agentmemory hook input rejected."
CONTINUE_RESPONSE = json.dumps({"continue": True}, separators=(",", ":"))
SESSION_START_EVENT = "SessionStart"
PRE_COMPACT_EVENT = "PreCompact"


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


def format_session_start_response(additional_context: str) -> str:
    return json.dumps(
        {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": additional_context,
            },
        },
        separators=(",", ":"),
    )


def format_pre_compact_response() -> str:
    return CONTINUE_RESPONSE


def run() -> None:
    if len(sys.argv) != 2:
        fail()

    action = sys.argv[1]
    payload = load_event_payload()
    hook_event_name = payload.get("hook_event_name")

    if action == "session-start":
        if hook_event_name != SESSION_START_EVENT:
            fail()
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd.strip():
            sys.stdout.write(CONTINUE_RESPONSE)
            return

        plugin_root = Path(__file__).resolve().parents[1]
        if str(plugin_root) not in sys.path:
            sys.path.insert(0, str(plugin_root))

        try:
            from agentmemory.storage import load_resume_state
            from agentmemory.render import render_resume_capsule
        except Exception:
            sys.stdout.write(CONTINUE_RESPONSE)
            return

        try:
            resume_state = load_resume_state(cwd)
            capsule = render_resume_capsule(resume_state)
        except Exception:
            sys.stdout.write(CONTINUE_RESPONSE)
            return

        if capsule is None:
            sys.stdout.write(CONTINUE_RESPONSE)
            return

        sys.stdout.write(format_session_start_response(capsule))
        return

    if action == "pre-compact":
        if hook_event_name != PRE_COMPACT_EVENT:
            fail()
        sys.stdout.write(format_pre_compact_response())
        return

    fail()


if __name__ == "__main__":
    run()
