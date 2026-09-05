"""Local, privacy-minimized observability primitives for AgentMemory."""

from __future__ import annotations

import os
import secrets
import tempfile
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .locking import FileLock
from .schema import canonical_json_dumps
from .scheduler import SchedulerValidationError, parse_strict_json
from .security import SecretScanError, scan_for_secrets
from .storage import _ensure_initialized_for_checkpoint, _load_identity, _resolve_layout, _validate_path_set, _validate_within_root


OBSERVABILITY_SCHEMA_VERSION = 1
MAX_EVENT_BYTES = 8 * 1024
MAX_LOG_BYTES = 10 * 1024 * 1024
RETENTION_DAYS = 30
EVENT_TYPES = ("write_attempt", "write_result", "retrieval", "injection", "outcome")
_ID_FIELDS = ("candidate_id", "record_id", "memory_id")
_OUTCOME_FIELDS = ("used_by_agent", "affected_decision", "task_success", "user_corrections", "retries", "turns", "tool_calls", "token_cost")
_CONFLICT_REASONS = (None, "none", "missing", "conflict", "truncated")
_WRITE_OPERATIONS = ("checkpoint", "candidate", "review")
_RETRIEVAL_LIFECYCLES = (None, "candidate", "active", "deprecated", "superseded", "stale")
_RETRIEVAL_FILTERS = (None, "exact_context", "project", "experience", "cross_project", "conflict")
_RETRIEVAL_SOURCES = ("experience", "openviking")
_WRITE_TRIGGERS = ("cli", "schedule", "hook")
_WRITE_SOURCES = ("cli", "scheduled-ai", "explicit-review")
_WRITE_SCOPES = ("local", "project")
_WRITE_STATUSES = ("created", "idempotent", "rejected", "failure", "success")
_WRITE_REASONS = (None, "none", "invalid", "conflict", "identity_changed", "storage_failure")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ObservabilityError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise ObservabilityError(message)


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_correlation_id() -> str:
    return "cor-" + secrets.token_hex(16)


def _parse_date(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) != 10:
        _fail("invalid date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ObservabilityError("invalid date") from exc


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("invalid observed_at")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ObservabilityError("invalid observed_at") from exc


def _parse_bound(value: Optional[str], *, end: bool) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str) and len(value) == 10:
        result = _parse_date(value)
        return result + timedelta(days=1) - timedelta(microseconds=1) if end else result
    return _parse_timestamp(value)


def _layout(repo_path: Optional[Union[str, Path]]) -> tuple[Dict[str, str], Dict[str, Path], Dict[str, Path]]:
    identity = _load_identity(repo_path)
    base = _resolve_layout(identity)
    root = base["repo_root"]
    directory = root / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "observability"
    result = {"config": base["repo_root"] / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "observability.json",
              "directory": directory, "events": directory / "events.jsonl",
              "lock": base["local"] / "locks" / ("observability-" + identity["worktree_id"] + ".lock")}
    _validate_path_set(base, root)
    _validate_observability_paths(base, result)
    return identity, base, result


def _validate_observability_paths(base: Mapping[str, Path], paths: Mapping[str, Path]) -> None:
    root = base["repo_root"]
    for key in ("config", "directory", "events", "lock"):
        _validate_within_root(root, paths[key], target_is_file=key != "directory")


def _config(identity: Mapping[str, Any], enabled: Any) -> Dict[str, Any]:
    if type(enabled) is not bool:
        _fail("invalid observability configuration")
    return {"schema_version": OBSERVABILITY_SCHEMA_VERSION, "repository_id": identity["repository_id"],
            "worktree_id": identity["worktree_id"], "enabled": enabled}


def _validate_config(value: Any, identity: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "repository_id", "worktree_id", "enabled"}:
        _fail("invalid observability configuration")
    if value["schema_version"] != OBSERVABILITY_SCHEMA_VERSION or value["repository_id"] != identity["repository_id"] or value["worktree_id"] != identity["worktree_id"]:
        _fail("invalid observability configuration")
    return _config(identity, value["enabled"])


def _atomic_write(root: Path, path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_within_root(root, path, target_is_file=True)
    fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=".o.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _validate_within_root(root, path, target_is_file=True)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def load_config(repo_path: Optional[Union[str, Path]]) -> Optional[Dict[str, Any]]:
    identity, _, paths = _layout(repo_path)
    if not paths["config"].exists():
        return None
    try:
        with paths["config"].open("rb") as stream:
            encoded = stream.read(MAX_EVENT_BYTES + 1)
        if len(encoded) > MAX_EVENT_BYTES:
            _fail("invalid observability configuration")
        return _validate_config(parse_strict_json(encoded.decode("utf-8", "strict"), max_bytes=MAX_EVENT_BYTES), identity)
    except (OSError, UnicodeError, SchedulerValidationError, ObservabilityError) as exc:
        raise ObservabilityError("invalid observability configuration") from exc


def configure(repo_path: Optional[Union[str, Path]], *, enabled: bool) -> Dict[str, Any]:
    identity, base, paths = _layout(repo_path)
    value = _config(identity, enabled)
    _ensure_initialized_for_checkpoint(base, base["repo_root"])
    _validate_observability_paths(base, paths)
    with FileLock(paths["lock"]):
        _validate_observability_paths(base, paths)
        _atomic_write(base["repo_root"], paths["config"], canonical_json_dumps(value))
    return value


def _validate_payload(event_type: str, payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        _fail("invalid event payload")
    if event_type == "write_attempt":
        fields = {"operation", "trigger", "source", "kind", "scope"}
        valid = (payload.get("operation") in _WRITE_OPERATIONS and payload.get("trigger") in _WRITE_TRIGGERS and
                 payload.get("source") in _WRITE_SOURCES and (payload.get("kind") is None or payload["kind"] in ("checkpoint", "decision", "incident", "constraint", "strategy", "warning")) and
                 payload.get("scope") in _WRITE_SCOPES)
    elif event_type == "write_result":
        fields = {"operation", "trigger", "source", "kind", "scope", "status", "reason"}
        valid = (payload.get("operation") in _WRITE_OPERATIONS and payload.get("trigger") in _WRITE_TRIGGERS and
                 payload.get("source") in _WRITE_SOURCES and (payload.get("kind") is None or payload["kind"] in ("checkpoint", "decision", "incident", "constraint", "strategy", "warning")) and
                 payload.get("scope") in _WRITE_SCOPES and payload.get("status") in _WRITE_STATUSES and payload.get("reason") in _WRITE_REASONS)
    elif event_type == "retrieval":
        fields = {"source", "query_digest", "result_ids", "ranks", "scores", "lifecycle", "filter", "activated_relation_count", "byte_budget", "byte_count", "omitted_count"}
        valid = (isinstance(payload.get("query_digest"), str) and len(payload["query_digest"]) == 64 and
                 all(char in "0123456789abcdef" for char in payload["query_digest"]) and
                 payload.get("source") in _RETRIEVAL_SOURCES and isinstance(payload.get("result_ids"), list) and all(isinstance(item, str) and _OPAQUE_ID_RE.fullmatch(item) for item in payload["result_ids"]) and
                 isinstance(payload.get("ranks"), list) and all(type(item) is int and item >= 0 for item in payload["ranks"]) and
                 isinstance(payload.get("scores"), list) and all(item is None or (type(item) in (int, float) and not isinstance(item, bool)) for item in payload["scores"]) and
                 len(payload["result_ids"]) == len(payload["ranks"]) == len(payload["scores"]) and
                 payload.get("lifecycle") in _RETRIEVAL_LIFECYCLES and payload.get("filter") in _RETRIEVAL_FILTERS and
                 all(payload.get(name) is None or (type(payload[name]) is int and payload[name] >= 0) for name in ("activated_relation_count", "byte_budget", "byte_count", "omitted_count")))
    elif event_type == "injection":
        fields = {"memory_ids", "order", "bytes", "budget", "truncated", "conflict_reason"}
        valid = (isinstance(payload.get("memory_ids"), list) and all(isinstance(item, str) and _OPAQUE_ID_RE.fullmatch(item) for item in payload["memory_ids"]) and
                 isinstance(payload.get("order"), list) and all(type(item) is int and item >= 0 for item in payload["order"]) and
                 type(payload.get("bytes")) is int and payload["bytes"] >= 0 and type(payload.get("budget")) is int and payload["budget"] >= 0 and
                 type(payload.get("truncated")) is bool and payload.get("conflict_reason") in _CONFLICT_REASONS)
    else:
        fields = set(_OUTCOME_FIELDS) | {"source"}
        valid = payload.get("source") == "human" and all(payload.get(name) is None or type(payload[name]) is bool for name in _OUTCOME_FIELDS[:3]) and all(payload.get(name) is None or (type(payload[name]) is int and payload[name] >= 0) for name in _OUTCOME_FIELDS[3:])
    if set(payload) != fields or not valid:
        _fail("invalid event payload")
    if event_type == "write_result" and ((payload["status"] in ("created", "idempotent", "success") and payload["reason"] not in (None, "none")) or (payload["status"] in ("rejected", "failure") and payload["reason"] in (None, "none"))):
        _fail("invalid event payload")
    try:
        scan_for_secrets(payload)
    except SecretScanError as exc:
        raise ObservabilityError("invalid event payload") from exc
    return dict(payload)


def validate_event(event: Any) -> Dict[str, Any]:
    base = {"schema_version", "event_id", "correlation_id", "event_type", "observed_at", "repository_id", "worktree_id", "branch", "head", *_ID_FIELDS, "payload"}
    if not isinstance(event, dict) or set(event) != base or event.get("schema_version") != OBSERVABILITY_SCHEMA_VERSION or event.get("event_type") not in EVENT_TYPES:
        _fail("invalid observability event")
    if not all(isinstance(event.get(name), str) and _OPAQUE_ID_RE.fullmatch(event[name]) for name in ("event_id", "correlation_id", "repository_id", "worktree_id", "head")):
        _fail("invalid observability event")
    if not isinstance(event.get("branch"), str) or not 0 < len(event["branch"]) <= 128 or any(ord(char) < 32 or ord(char) == 127 for char in event["branch"]):
        _fail("invalid observability event")
    if any(event.get(name) is not None and (not isinstance(event[name], str) or not _OPAQUE_ID_RE.fullmatch(event[name])) for name in _ID_FIELDS):
        _fail("invalid observability event")
    _parse_timestamp(event["observed_at"])
    value = dict(event)
    value["payload"] = _validate_payload(value["event_type"], value["payload"])
    try:
        scan_for_secrets(value)
        rendered = canonical_json_dumps(value)
    except Exception as exc:
        raise ObservabilityError("invalid observability event") from exc
    if len(rendered.encode("utf-8")) + 1 > MAX_EVENT_BYTES:
        _fail("observability event exceeds limit")
    return value


def _read_events(paths: Mapping[str, Path]) -> List[Dict[str, Any]]:
    if not paths["events"].exists():
        return []
    try:
        if paths["events"].stat().st_size > MAX_LOG_BYTES:
            _fail("invalid observability event store")
        with paths["events"].open("rb") as stream:
            encoded = stream.read(MAX_LOG_BYTES + 1)
        if len(encoded) > MAX_LOG_BYTES:
            _fail("invalid observability event store")
        rows = encoded.splitlines(keepends=True)
        if any(len(row) > MAX_EVENT_BYTES or not row.endswith(b"\n") for row in rows):
            _fail("invalid observability event store")
        return [validate_event(parse_strict_json(row[:-1].decode("utf-8", "strict"), max_bytes=MAX_EVENT_BYTES)) for row in rows if row]
    except (OSError, UnicodeError, SchedulerValidationError, ObservabilityError) as exc:
        raise ObservabilityError("invalid observability event store") from exc


def _compact(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    retained = [event for event in events if _parse_timestamp(event["observed_at"]) >= cutoff]
    kept: List[Dict[str, Any]] = []
    total = 0
    for event in reversed(retained):
        size = len(canonical_json_dumps(event).encode("utf-8")) + 1
        if total + size <= MAX_LOG_BYTES:
            kept.append(event)
            total += size
    return list(reversed(kept))


def _event(identity: Mapping[str, Any], *, event_type: str, payload: Mapping[str, Any], correlation_id: Optional[str],
           candidate_id: Optional[str], record_id: Optional[str], memory_id: Optional[str]) -> Dict[str, Any]:
    return validate_event({"schema_version": OBSERVABILITY_SCHEMA_VERSION, "event_id": "evt-" + secrets.token_hex(16),
        "correlation_id": correlation_id or "cor-" + secrets.token_hex(16), "event_type": event_type, "observed_at": _timestamp_utc(),
        "repository_id": identity["repository_id"], "worktree_id": identity["worktree_id"], "branch": identity["branch"], "head": identity["head"],
        "candidate_id": candidate_id, "record_id": record_id, "memory_id": memory_id, "payload": dict(payload)})


def _append_event(base: Mapping[str, Path], paths: Mapping[str, Path], event: Mapping[str, Any], events: Optional[List[Dict[str, Any]]] = None) -> None:
    appended = _compact(_read_events(paths) if events is None else events)
    appended.append(dict(event))
    appended = _compact(appended)
    text = "".join(canonical_json_dumps(item) + "\n" for item in appended)
    if len(text.encode("utf-8")) > MAX_LOG_BYTES:
        _fail("observability event store exceeds limit")
    _atomic_write(base["repo_root"], paths["events"], text)


def emit(repo_path: Optional[Union[str, Path]], *, event_type: str, payload: Mapping[str, Any], correlation_id: Optional[str] = None, candidate_id: Optional[str] = None, record_id: Optional[str] = None, memory_id: Optional[str] = None) -> bool:
    """Best-effort automatic emission; observability failures never escape."""
    try:
        identity, _, paths = _layout(repo_path)
        config = load_config(repo_path)
        if config is None or not config["enabled"]:
            return False
        event = _event(identity, event_type=event_type, payload=payload, correlation_id=correlation_id,
                       candidate_id=candidate_id, record_id=record_id, memory_id=memory_id)
        _, base, paths = _layout(repo_path)
        _validate_observability_paths(base, paths)
        with FileLock(paths["lock"], timeout=0.1):
            _validate_observability_paths(base, paths)
            current = load_config(repo_path)
            if current is None or not current["enabled"]:
                return False
            _append_event(base, paths, event)
        return True
    except Exception:
        return False


def export(repo_path: Optional[Union[str, Path]], *, since: Optional[str] = None, until: Optional[str] = None) -> Dict[str, Any]:
    identity, base, paths = _layout(repo_path)
    _ensure_initialized_for_checkpoint(base, base["repo_root"])
    config = load_config(repo_path)
    if config is None:
        return {"enabled": False, "events": []}
    _validate_observability_paths(base, paths)
    with FileLock(paths["lock"]):
        _validate_observability_paths(base, paths)
        events = _read_events(paths)
    if any(event["repository_id"] != identity["repository_id"] or event["worktree_id"] != identity["worktree_id"] for event in events):
        _fail("observability identity mismatch")
    start, end = _parse_bound(since, end=False), _parse_bound(until, end=True)
    if start is not None and end is not None and start > end:
        _fail("invalid export range")
    events = [event for event in events if (start is None or _parse_timestamp(event["observed_at"]) >= start) and (end is None or _parse_timestamp(event["observed_at"]) <= end)]
    return {"enabled": config["enabled"], "events": events}


def report(repo_path: Optional[Union[str, Path]], *, day: str) -> Dict[str, Any]:
    _parse_date(day)
    events = [event for event in export(repo_path)["events"] if event["observed_at"][:10] == day]
    counts = {kind: sum(event["event_type"] == kind for event in events) for kind in EVENT_TYPES}
    correlations = {kind: {event["correlation_id"] for event in events if event["event_type"] == kind} for kind in EVENT_TYPES}
    results = {status: sum(event["event_type"] == "write_result" and event["payload"]["status"] == status for event in events) for status in _WRITE_STATUSES}
    outcomes = [event["payload"] for event in events if event["event_type"] == "outcome"]
    metrics = {name: sum(payload[name] for payload in outcomes if type(payload[name]) is int) for name in _OUTCOME_FIELDS[3:]}
    flags = {name: {"true": sum(payload[name] is True for payload in outcomes), "false": sum(payload[name] is False for payload in outcomes), "null": sum(payload[name] is None for payload in outcomes)} for name in _OUTCOME_FIELDS[:3]}
    return {"day": day, "counts": counts, "write_result_statuses": results, "coverage": {
        "retrieval_with_injection": len(correlations["retrieval"] & correlations["injection"]),
        "injection_with_outcome": len(correlations["injection"] & correlations["outcome"]),
    }, "explicit_outcomes": {"count": len(outcomes), "flags": flags, "metrics": metrics}, "stage_gaps": {
        "write_attempt_without_result": len(correlations["write_attempt"] - correlations["write_result"]),
        "retrieval_without_injection": len(correlations["retrieval"] - correlations["injection"]),
        "injection_without_outcome": len(correlations["injection"] - correlations["outcome"]),
    }}


def annotate_outcome(repo_path: Optional[Union[str, Path]], *, correlation_id: str, confirm: bool, **outcome: Any) -> bool:
    if confirm is not True or not isinstance(correlation_id, str) or not correlation_id:
        _fail("outcome annotation requires confirmation")
    if not _OPAQUE_ID_RE.fullmatch(correlation_id):
        _fail("outcome annotation requires confirmation")
    identity, base, paths = _layout(repo_path)
    _ensure_initialized_for_checkpoint(base, base["repo_root"])
    config = load_config(repo_path)
    if config is None or not config["enabled"]:
        _fail("observability is disabled")
    event = _event(identity, event_type="outcome", correlation_id=correlation_id, payload={"source": "human", **outcome},
                   candidate_id=None, record_id=None, memory_id=None)
    _validate_observability_paths(base, paths)
    with FileLock(paths["lock"]):
        _validate_observability_paths(base, paths)
        current = load_config(repo_path)
        if current is None or not current["enabled"]:
            _fail("observability is disabled")
        events = _read_events(paths)
        if not any(item["correlation_id"] == correlation_id for item in events):
            _fail("unknown outcome correlation")
        _append_event(base, paths, event, events)
    return True


def delete(repo_path: Optional[Union[str, Path]], *, confirm: bool, all_events: bool = False, before: Optional[str] = None) -> int:
    if confirm is not True or (all_events == (before is not None)):
        _fail("observability deletion requires confirmation and one target")
    if before is not None:
        _parse_date(before)
    _, base, paths = _layout(repo_path)
    _ensure_initialized_for_checkpoint(base, base["repo_root"])
    _validate_observability_paths(base, paths)
    with FileLock(paths["lock"]):
        _validate_observability_paths(base, paths)
        events = _read_events(paths)
        retained = [] if all_events else [event for event in events if event["observed_at"][:10] >= before]
        _atomic_write(base["repo_root"], paths["events"], "".join(canonical_json_dumps(item) + "\n" for item in retained))
    return len(events) - len(retained)
