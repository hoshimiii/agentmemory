"""Pure contracts for opt-in scheduled memory candidate distillation.

This module deliberately has no filesystem, subprocess, or CLI dependency.  It
keeps provider input/output contracts small and testable; storage and execution
are responsible for applying these contracts later.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .schema import canonical_json_dumps
from .security import SecretScanError, scan_for_secrets


SCHEDULER_SCHEMA_VERSION = 1
PROVIDERS = ("codex", "claude", "gemini")
CODEX_REASONING_EFFORTS = (
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra",
)
PROPOSAL_KINDS = ("decision", "incident", "constraint", "strategy", "warning")
PROPOSAL_SEMANTIC_ROLES = ("fact", "inference")
MAX_CRON_LENGTH = 128
MAX_TIMEZONE_LENGTH = 64
MAX_MODEL_LENGTH = 128
MAX_PROVIDER_OUTPUT_BYTES = 64 * 1024
MAX_PROPOSALS = 5
MAX_BATCH_SUMMARY_CHARS = 2048

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
_IDENTITY_RE = re.compile(r"^[a-f0-9]{64}$")
_HEAD_RE = re.compile(r"^(?:[a-f0-9]{40}|UNBORN)$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class SchedulerValidationError(ValueError):
    """Raised when an untrusted scheduler value violates its narrow contract."""


def _fail(message: str) -> None:
    raise SchedulerValidationError(message)


def _require_exact_keys(value: Any, fields: Iterable[str], label: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        _fail(label + " has unexpected fields")
    return value


def _reject_json_constant(_: str) -> None:
    _fail("invalid JSON")


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("invalid JSON")
        result[key] = value
    return result


def parse_strict_json(raw: Any, *, max_bytes: int = MAX_PROVIDER_OUTPUT_BYTES) -> Any:
    """Parse one bounded JSON value, refusing duplicates and non-finite values."""

    if not isinstance(raw, str):
        _fail("invalid JSON")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SchedulerValidationError("invalid JSON") from exc
    if len(encoded) > max_bytes:
        _fail("provider output exceeds limit")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, SchedulerValidationError):
            raise
        raise SchedulerValidationError("invalid JSON") from exc


def _validate_identity(identity: Mapping[str, Any], *, require_head: bool) -> Dict[str, str]:
    if not isinstance(identity, Mapping):
        _fail("invalid repository identity")
    required = {"repository_id", "worktree_id"}
    if require_head:
        required.add("head")
    if not required.issubset(identity):
        _fail("invalid repository identity")
    result: Dict[str, str] = {}
    for key in ("repository_id", "worktree_id"):
        value = identity.get(key)
        if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
            _fail("invalid repository identity")
        result[key] = value
    if require_head:
        head = identity.get("head")
        if not isinstance(head, str) or not _HEAD_RE.fullmatch(head):
            _fail("invalid repository identity")
        result["head"] = head
        branch = identity.get("branch")
        if not isinstance(branch, str) or not branch or len(branch) > 255 or _CONTROL_RE.search(branch):
            _fail("invalid repository identity")
        result["branch"] = branch
    return result


def _validate_model(value: Any) -> str:
    if not isinstance(value, str) or not _MODEL_RE.fullmatch(value):
        _fail("invalid model")
    return value


def _validate_timezone(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_TIMEZONE_LENGTH or _CONTROL_RE.search(value):
        _fail("invalid timezone")
    return value


def _parse_cron_number(token: str, minimum: int, maximum: int) -> int:
    if not token.isascii() or not token.isdecimal():
        _fail("invalid cron field")
    value = int(token)
    if value < minimum or value > maximum:
        _fail("cron value out of range")
    return value


def _parse_cron_base(token: str, minimum: int, maximum: int) -> None:
    if token == "*":
        return
    if "-" in token:
        if token.count("-") != 1:
            _fail("invalid cron range")
        lower, upper = token.split("-", 1)
        if _parse_cron_number(lower, minimum, maximum) > _parse_cron_number(upper, minimum, maximum):
            _fail("invalid cron range")
        return
    _parse_cron_number(token, minimum, maximum)


def _parse_cron_atom(token: str, minimum: int, maximum: int) -> None:
    if not token or token.count("/") > 1:
        _fail("invalid cron field")
    if "/" not in token:
        _parse_cron_base(token, minimum, maximum)
        return
    base, step = token.split("/", 1)
    _parse_cron_base(base, minimum, maximum)
    if _parse_cron_number(step, 1, maximum - minimum + 1) == 0:
        _fail("invalid cron step")


def parse_cron(expression: Any) -> Tuple[str, str, str, str, str]:
    """Validate the supported numeric five-field POSIX cron subset."""

    if not isinstance(expression, str) or not expression or len(expression) > MAX_CRON_LENGTH:
        _fail("invalid cron")
    if not expression.isascii() or "\t" in expression or "\n" in expression or "\r" in expression:
        _fail("invalid cron")
    fields = expression.split(" ")
    if len(fields) != 5 or any(not field for field in fields):
        _fail("cron must contain five fields")
    ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
    for field, (minimum, maximum) in zip(fields, ranges):
        for atom in field.split(","):
            _parse_cron_atom(atom, minimum, maximum)
    return tuple(fields)  # type: ignore[return-value]


def validate_scheduler_config(config: Any, identity: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a deep-copied exact, identity-bound scheduler configuration."""

    fields = {
        "schema_version", "repository_id", "worktree_id", "enabled", "provider", "model",
        "cron", "timezone", "reasoning_effort",
    }
    value = _require_exact_keys(copy.deepcopy(config), fields, "scheduler config")
    expected = _validate_identity(identity, require_head=False)
    if value["schema_version"] != SCHEDULER_SCHEMA_VERSION or type(value["schema_version"]) is not int:
        _fail("unsupported scheduler schema")
    if value["repository_id"] != expected["repository_id"] or value["worktree_id"] != expected["worktree_id"]:
        _fail("scheduler configuration identity mismatch")
    if type(value["enabled"]) is not bool:
        _fail("invalid enabled value")
    provider = value["provider"]
    if provider not in PROVIDERS:
        _fail("invalid provider")
    value["model"] = _validate_model(value["model"])
    parse_cron(value["cron"])
    value["timezone"] = _validate_timezone(value["timezone"])
    effort = value["reasoning_effort"]
    if provider == "codex":
        if effort not in CODEX_REASONING_EFFORTS:
            _fail("invalid reasoning effort")
    elif effort is not None:
        _fail("reasoning effort is only valid for codex")
    try:
        scan_for_secrets(value)
    except SecretScanError as exc:
        raise SchedulerValidationError("invalid scheduler configuration") from exc
    return value


def _validate_proposal(proposal: Any) -> Dict[str, Any]:
    fields = {"kind", "summary", "semantic_role", "content", "paths", "experience"}
    value = _require_exact_keys(copy.deepcopy(proposal), fields, "proposal")
    if value["kind"] not in PROPOSAL_KINDS:
        _fail("invalid proposal kind")
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        _fail("invalid proposal summary")
    if value["semantic_role"] not in PROPOSAL_SEMANTIC_ROLES:
        _fail("invalid proposal semantic role")
    if not isinstance(value["content"], dict):
        _fail("invalid proposal content")
    if not isinstance(value["paths"], list) or any(not isinstance(path, str) for path in value["paths"]):
        _fail("invalid proposal paths")
    is_experience = value["kind"] in ("strategy", "warning")
    if is_experience and not isinstance(value["experience"], dict):
        _fail("experience is required for strategy and warning")
    if not is_experience and value["experience"] is not None:
        _fail("experience is only valid for strategy and warning")
    try:
        canonical_json_dumps(value)
        scan_for_secrets(value)
    except (SecretScanError, ValueError) as exc:
        raise SchedulerValidationError("invalid proposal") from exc
    return value


def validate_candidate_batch(payload: Any) -> Dict[str, Any]:
    """Validate the bounded provider proposal contract before candidate writes."""

    value = _require_exact_keys(copy.deepcopy(payload), {"summary", "proposals"}, "candidate batch")
    if not isinstance(value["summary"], str) or len(value["summary"]) > MAX_BATCH_SUMMARY_CHARS:
        _fail("invalid batch summary")
    if not isinstance(value["proposals"], list) or len(value["proposals"]) > MAX_PROPOSALS:
        _fail("invalid proposal batch")
    value["proposals"] = [_validate_proposal(proposal) for proposal in value["proposals"]]
    try:
        canonical_json_dumps(value)
        scan_for_secrets(value)
    except (SecretScanError, ValueError) as exc:
        raise SchedulerValidationError("invalid candidate batch") from exc
    return value


def validate_candidate_envelope(payload: Any) -> Dict[str, Any]:
    """Validate only the batch boundary so individual proposals can be rejected later."""

    value = _require_exact_keys(copy.deepcopy(payload), {"summary", "proposals"}, "candidate batch")
    if not isinstance(value["summary"], str) or len(value["summary"]) > MAX_BATCH_SUMMARY_CHARS:
        _fail("invalid batch summary")
    if not isinstance(value["proposals"], list) or len(value["proposals"]) > MAX_PROPOSALS:
        _fail("invalid proposal batch")
    try:
        scan_for_secrets(value["summary"])
    except SecretScanError as exc:
        raise SchedulerValidationError("invalid candidate batch") from exc
    return value


def candidate_batch_schema() -> Dict[str, Any]:
    """Return the exact JSON Schema supplied to structured-output providers."""

    proposal = {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "summary", "semantic_role", "content", "paths", "experience"],
        "properties": {
            "kind": {"enum": list(PROPOSAL_KINDS)},
            "summary": {"type": "string"},
            "semantic_role": {"enum": list(PROPOSAL_SEMANTIC_ROLES)},
            "content": {"type": "object"},
            "paths": {"type": "array", "items": {"type": "string"}},
            "experience": {"type": ["object", "null"]},
        },
        "allOf": [{
            "if": {"properties": {"kind": {"enum": ["strategy", "warning"]}}},
            "then": {"properties": {"experience": {"type": "object"}}},
            "else": {"properties": {"experience": {"type": "null"}}},
        }],
    }
    return {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "proposals"],
        "properties": {
            "summary": {"type": "string", "maxLength": MAX_BATCH_SUMMARY_CHARS},
            "proposals": {"type": "array", "maxItems": MAX_PROPOSALS, "items": proposal},
        },
    }


def extract_provider_payload(provider: str, raw: str) -> Any:
    """Extract the single allowed proposal source without validating proposals."""

    if provider not in PROVIDERS:
        _fail("invalid provider")
    outer = parse_strict_json(raw)
    if provider == "codex":
        return outer
    if not isinstance(outer, dict):
        _fail("invalid provider envelope")
    if provider == "claude":
        if "structured_output" not in outer or not isinstance(outer["structured_output"], dict):
            _fail("missing structured provider output")
        return outer["structured_output"]
    if "error" in outer or not isinstance(outer.get("response"), str):
        _fail("invalid provider envelope")
    return parse_strict_json(outer["response"])


def parse_provider_output(provider: str, raw: str) -> Dict[str, Any]:
    """Extract one provider-specific structured output source and validate it."""

    if provider not in PROVIDERS:
        _fail("invalid provider")
    outer = parse_strict_json(raw)
    if provider == "codex":
        return validate_candidate_batch(outer)
    if not isinstance(outer, dict):
        _fail("invalid provider envelope")
    if provider == "claude":
        if "structured_output" not in outer or not isinstance(outer["structured_output"], dict):
            _fail("missing structured provider output")
        return validate_candidate_batch(outer["structured_output"])
    if "error" in outer or not isinstance(outer.get("response"), str):
        _fail("invalid provider envelope")
    return validate_candidate_batch(parse_strict_json(outer["response"]))


def normalize_proposal(proposal: Any) -> Dict[str, Any]:
    """Return the canonical identity representation for one already-valid proposal."""

    value = _validate_proposal(proposal)
    value["paths"] = sorted(value["paths"])
    return value


def candidate_id_for(identity: Mapping[str, Any], proposal: Any) -> str:
    """Derive a retry-stable candidate ID within the existing 64-character limit."""

    current = _validate_identity(identity, require_head=True)
    normalized = normalize_proposal(proposal)
    payload = (
        b"agentmemory/scheduled-candidate/v1\0"
        + current["repository_id"].encode("ascii") + b"\0"
        + current["worktree_id"].encode("ascii") + b"\0"
        + current["branch"].encode("utf-8") + b"\0"
        + current["head"].encode("ascii") + b"\0"
        + canonical_json_dumps(normalized).encode("utf-8")
    )
    return "cand-ai-" + hashlib.sha256(payload).hexdigest()[:56]


def deduplicate_proposals(identity: Mapping[str, Any], proposals: Sequence[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Keep the first normalized occurrence and return duplicate candidate IDs."""

    accepted: List[Dict[str, Any]] = []
    duplicates: List[str] = []
    seen = set()
    for proposal in proposals:
        normalized = normalize_proposal(proposal)
        candidate_id = candidate_id_for(identity, normalized)
        if candidate_id in seen:
            duplicates.append(candidate_id)
            continue
        seen.add(candidate_id)
        accepted.append({"id": candidate_id, "proposal": normalized})
    return accepted, duplicates


def build_provider_argv(config: Mapping[str, Any]) -> List[str]:
    """Render an argv-only, read-only provider plan with inert placeholders."""

    if not isinstance(config, Mapping):
        _fail("scheduler config has unexpected fields")
    identity = {
        "repository_id": config.get("repository_id"),
        "worktree_id": config.get("worktree_id"),
    }
    value = validate_scheduler_config(config, identity)
    provider = value["provider"]
    model = value["model"]
    if provider == "codex":
        argv = [
            "<codex>", "exec", "--ephemeral", "--sandbox", "read-only", "--model", model,
            "--output-schema", "<output-schema-file>", "--output-last-message", "<final-output-file>",
        ]
        argv.extend(["-c", "model_reasoning_effort=" + value["reasoning_effort"]])
        return argv + ["<distillation-prompt>"]
    if provider == "claude":
        return [
            "<claude>", "-p", "<distillation-prompt>", "--no-session-persistence",
            "--permission-mode", "plan", "--model", model, "--output-format", "json",
            "--json-schema", "<output-schema-json>",
        ]
    return [
        "<gemini>", "-p", "<distillation-prompt>", "--approval-mode", "plan",
        "--model", model, "--output-format", "json",
    ]


def build_distillation_prompt() -> str:
    """Return the invariant read-only prompt used by every provider adapter."""

    return (
        "Analyze only the current Git repository's verifiable Git state, code, tests, "
        "specifications, and CONTEXT.md. Do not edit files, run network queries, read "
        "transcripts, transcript_path, PLUGIN_DATA, platform memory, user-home data, "
        "credentials, or other projects. Do not review, promote, create receipts, or claim "
        "a durable-memory ID. Return only JSON matching this schema: "
        "{\"summary\":string,\"proposals\":[{\"kind\":\"decision|incident|constraint|strategy|warning\","
        "\"summary\":string,\"semantic_role\":\"fact|inference\",\"content\":object,"
        "\"paths\":[string],\"experience\":object|null}]}. At most five proposals. "
        "For strategy and warning, experience must satisfy the existing v2 experience contract; "
        "for all other kinds it must be null. Empty proposals is valid."
    )
