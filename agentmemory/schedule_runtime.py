"""Bounded local runtime for scheduled, human-reviewed memory candidates."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .identity import get_git_identity
from .scheduler import (
    MAX_PROVIDER_OUTPUT_BYTES, PROVIDERS, SchedulerValidationError, build_distillation_prompt,
    build_provider_argv, candidate_batch_schema, candidate_id_for,
    extract_provider_payload, normalize_proposal, validate_candidate_envelope,
)
from .storage import StorageError, checkout_identity_matches, create_candidate, load_scheduler_config, preflight_candidate, write_scheduler_config

_TIMEOUT_SECONDS = 300


class ScheduleRuntimeError(RuntimeError):
    pass


def _error(message: str) -> None:
    raise ScheduleRuntimeError(message)


def configure_schedule(repo_path: Optional[str], *, provider: str, model: str, cron: str,
                       timezone: str = "local", reasoning_effort: Optional[str] = None,
                       enabled: bool = False) -> Dict[str, Any]:
    try:
        identity = get_git_identity(repo_path)
        config = {"schema_version": 1, "repository_id": identity["repository_id"],
                  "worktree_id": identity["worktree_id"], "enabled": enabled, "provider": provider,
                  "model": model, "cron": cron, "timezone": timezone,
                  "reasoning_effort": reasoning_effort}
        if provider == "codex" and reasoning_effort is None:
            config["reasoning_effort"] = "medium"
        return write_scheduler_config(repo_path, config)
    except Exception as exc:
        raise ScheduleRuntimeError("invalid scheduler configuration") from exc


def schedule_status(repo_path: Optional[str]) -> Dict[str, Any]:
    try:
        config = load_scheduler_config(repo_path)
    except Exception as exc:
        raise ScheduleRuntimeError("invalid scheduler configuration") from exc
    if config is None:
        return {"configured": False, "enabled": False}
    return {"configured": True, "enabled": config["enabled"], "provider": config["provider"],
            "model": config["model"], "cron": config["cron"], "timezone": config["timezone"]}


def _executable(provider: str) -> Optional[str]:
    if provider not in PROVIDERS:
        return None
    found = shutil.which(provider)
    return str(Path(found).absolute()) if found else None


def schedule_plan(repo_path: Optional[str]) -> Dict[str, Any]:
    try:
        config = load_scheduler_config(repo_path)
        identity = get_git_identity(repo_path)
    except Exception as exc:
        raise ScheduleRuntimeError("scheduler plan unavailable") from exc
    if config is None:
        return {"configured": False, "enabled": False, "runnable": False}
    executable = _executable(config["provider"])
    return {"configured": True, "enabled": config["enabled"], "runnable": executable is not None,
            "provider": config["provider"], "model": config["model"], "cron": config["cron"],
            "timezone": config["timezone"], "cwd": identity["toplevel"], "max_candidates": 5,
            "argv": build_provider_argv(config)}


def _runtime_argv(config: Mapping[str, Any], executable: str, schema_path: Path, final_path: Path) -> List[str]:
    argv = build_provider_argv(config)
    argv[0] = executable
    replacements = {"<distillation-prompt>": build_distillation_prompt(),
                    "<output-schema-file>": str(schema_path), "<final-output-file>": str(final_path),
                    "<output-schema-json>": json.dumps(candidate_batch_schema(), separators=(",", ":"))}
    return [replacements.get(item, item) for item in argv]


def _read_bounded(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_PROVIDER_OUTPUT_BYTES + 1)
        if len(payload) > MAX_PROVIDER_OUTPUT_BYTES:
            _error("provider execution failed")
        return payload.decode("utf-8", "strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise ScheduleRuntimeError("provider execution failed") from exc


def _run_provider(config: Mapping[str, Any], cwd: str) -> Any:
    executable = _executable(config["provider"])
    if executable is None:
        _error("provider execution failed")
    paths: List[Path] = []
    process = None
    try:
        for suffix in ("schema.json", "final.json", "stdout", "stderr"):
            handle = tempfile.NamedTemporaryFile(delete=False, suffix="." + suffix)
            handle.close()
            paths.append(Path(handle.name))
        schema_path, final_path, stdout_path, stderr_path = paths
        schema_path.write_text(json.dumps(candidate_batch_schema(), separators=(",", ":")), encoding="utf-8")
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(_runtime_argv(config, executable, schema_path, final_path), cwd=cwd,
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, shell=False)
            deadline = time.monotonic() + _TIMEOUT_SECONDS
            while process.poll() is None:
                if any(path.stat().st_size > MAX_PROVIDER_OUTPUT_BYTES for path in (stdout_path, stderr_path, final_path)):
                    process.kill()
                    process.wait()
                    _error("provider execution failed")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    _error("provider execution failed")
                time.sleep(0.02)
        if process.returncode != 0:
            _error("provider execution failed")
        _read_bounded(stderr_path)
        raw = _read_bounded(final_path) if config["provider"] == "codex" else _read_bounded(stdout_path)
        return extract_provider_payload(config["provider"], raw)
    except (OSError, SchedulerValidationError, ScheduleRuntimeError) as exc:
        if isinstance(exc, ScheduleRuntimeError):
            raise
        raise ScheduleRuntimeError("provider execution failed") from exc
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for path in paths:
            try:
                path.unlink()
            except OSError:
                pass


def run_schedule(repo_path: Optional[str], *, dry_run: bool = False) -> Dict[str, Any]:
    plan = schedule_plan(repo_path)
    if dry_run:
        return plan
    if not plan.get("configured") or not plan.get("enabled") or not plan.get("runnable"):
        _error("schedule is not runnable")
    try:
        config = load_scheduler_config(repo_path)
        if config is None or not config["enabled"]:
            _error("schedule is not runnable")
        before = get_git_identity(repo_path)
        payload = validate_candidate_envelope(_run_provider(config, before["toplevel"]))
    except (StorageError, SchedulerValidationError, ScheduleRuntimeError) as exc:
        if isinstance(exc, ScheduleRuntimeError): raise
        raise ScheduleRuntimeError("provider execution failed") from exc
    try:
        after = get_git_identity(repo_path)
        if not checkout_identity_matches(before, after):
            _error("provider execution failed")
        prepared = []
        duplicates = []
        seen_candidate_ids = set()
        rejections = []
        for proposal_index, item in enumerate(payload["proposals"]):
            try:
                proposal = normalize_proposal(item)
                candidate_id = candidate_id_for(before, proposal)
                if candidate_id in seen_candidate_ids:
                    duplicates.append(candidate_id)
                    continue
                seen_candidate_ids.add(candidate_id)
                preflight_candidate(repo_path, proposal["kind"], proposal["summary"], proposal["content"], proposal["paths"],
                    semantic_role=proposal["semantic_role"], record_id=candidate_id, experience=proposal["experience"], source="scheduled-ai")
                prepared.append({"id": candidate_id, "proposal": proposal})
            except (StorageError, SchedulerValidationError):
                rejections.append({"proposal_index": proposal_index, "category": "invalid_proposal"})
        # All candidates pass preflight before the first persistence operation.
        candidates = []
        for item in prepared:
            proposal = item["proposal"]
            result = create_candidate(repo_path, proposal["kind"], proposal["summary"], proposal["content"], proposal["paths"],
                semantic_role=proposal["semantic_role"], record_id=item["id"], experience=proposal["experience"], expected_identity=before, source="scheduled-ai")
            candidates.append({"id": item["id"], "kind": proposal["kind"], "summary": proposal["summary"],
                               "created": result["created"], "idempotent": not result["created"]})
    except (StorageError, SchedulerValidationError) as exc:
        raise ScheduleRuntimeError("candidate persistence failed") from exc
    return {"provider": config["provider"], "model": config["model"], "cron": config["cron"], "timezone": config["timezone"],
            "status": "completed", "summary": payload["summary"], "candidates": candidates,
            "duplicate_ids": duplicates, "duplicate_count": len(duplicates), "rejections": rejections,
            "rejected_count": len(rejections),
            "requires_human_review": True, "reviewed": False, "promoted": False}
