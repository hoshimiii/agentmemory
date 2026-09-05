"""CLI for local checkpoint persistence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any, Optional, Sequence

from .openviking import OpenVikingError, retrieve_project_knowledge
from . import observability
from .schema import RecordValidationError
from .storage import (
    StorageConflictError,
    StorageError,
    StoragePathError,
    create_checkpoint,
    create_candidate,
    disable_scheduler_config,
    enable_scheduler_config,
    review_candidate,
    render_continuity,
    get_status,
    initialize_repository,
    load_trusted_experiences,
)
from .render import render_experience_match
from .schedule_runtime import (
    ScheduleRuntimeError,
    configure_schedule,
    run_schedule,
    schedule_plan,
    schedule_status,
)


def _parse_content_json(raw: str) -> dict:
    def reject_non_standard_json_constant(_value: str) -> None:
        raise ValueError("invalid content-json")

    try:
        loaded = json.loads(raw, parse_constant=reject_non_standard_json_constant)
    except (json.JSONDecodeError, ValueError):
        raise ValueError("invalid content-json")
    if not isinstance(loaded, dict):
        raise ValueError("invalid content-json")
    return loaded


def _parse_experience_json(raw: str) -> dict:
    try:
        return _parse_content_json(raw)
    except ValueError as exc:
        raise ValueError("invalid experience-json") from exc


def _print_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def _emit_error(message: str) -> None:
    if not message.endswith("\n"):
        message = message + "\n"
    sys.stderr.write(message)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse contract
        _emit_error("error: invalid arguments")
        raise SystemExit(2)

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        if status != 0:
            _emit_error("error: invalid arguments")
            raise SystemExit(status)
        raise SystemExit(status)


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="agentmemory")
    parser.add_argument("--repo", default=None)
    command = parser.add_subparsers(dest="command", required=True)

    command.add_parser("init")
    command.add_parser("status")

    checkpoint = command.add_parser("checkpoint")
    checkpoint_command = checkpoint.add_subparsers(dest="checkpoint_command", required=True)

    create = checkpoint_command.add_parser("create")
    create.add_argument("--summary", required=True)
    create.add_argument("--content-json", dest="content_json", required=True)
    create.add_argument("--path", action="append", default=[])
    create.add_argument("--id")

    candidate = command.add_parser("candidate")
    candidate_command = candidate.add_subparsers(dest="candidate_command", required=True)

    propose = candidate_command.add_parser("propose")
    propose.add_argument("--kind", required=True, choices=["decision", "incident", "constraint", "strategy", "warning"])
    propose.add_argument("--summary", required=True)
    propose.add_argument("--content-json", dest="content_json", required=True)
    propose.add_argument(
        "--semantic-role",
        dest="semantic_role",
        choices=["fact", "inference"],
        default="inference",
    )
    propose.add_argument("--path", action="append", default=[])
    propose.add_argument("--id")
    propose.add_argument("--experience-json", dest="experience_json")

    review = command.add_parser("review")
    review.add_argument("--candidate", dest="candidate_id", required=True)
    review.add_argument("--confirm", action="store_true", required=True)

    command.add_parser("render")

    experience = command.add_parser("experience")
    experience_command = experience.add_subparsers(dest="experience_command", required=True)
    match = experience_command.add_parser("match")
    match.add_argument("--task-type", action="append", default=[])
    match.add_argument("--signal", action="append", default=[])
    match.add_argument("--error-pattern", action="append", default=[])
    match.add_argument("--path", action="append", default=[])
    match.add_argument("--max-bytes", type=int)

    retrieve = command.add_parser("retrieve")
    retrieve.add_argument("--query", required=True)
    retrieve.add_argument("--openviking-cli", dest="openviking_cli", required=True)
    retrieve.add_argument("--openviking-config", dest="openviking_config", required=True)
    retrieve.add_argument("--limit", type=int, choices=range(1, 6), default=3)

    schedule = command.add_parser("schedule")
    schedule_command = schedule.add_subparsers(dest="schedule_command", required=True)
    configure = schedule_command.add_parser("configure")
    configure.add_argument("--provider", required=True, choices=["codex", "claude", "gemini"])
    configure.add_argument("--model", required=True)
    configure.add_argument("--cron", required=True)
    configure.add_argument("--timezone", default="local")
    configure.add_argument("--reasoning-effort", choices=["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"])
    configure.add_argument("--enable", action="store_true")
    schedule_command.add_parser("enable")
    schedule_command.add_parser("disable")
    schedule_command.add_parser("status")
    schedule_command.add_parser("plan")
    run_schedule_parser = schedule_command.add_parser("run")
    run_schedule_parser.add_argument("--dry-run", action="store_true")

    observe = command.add_parser("observability")
    observe_command = observe.add_subparsers(dest="observability_command", required=True)
    observe_command.add_parser("enable")
    observe_command.add_parser("disable")
    observe_command.add_parser("status")
    export = observe_command.add_parser("export")
    export.add_argument("--since")
    export.add_argument("--until")
    report = observe_command.add_parser("report")
    report.add_argument("--date", required=True)
    delete = observe_command.add_parser("delete")
    targets = delete.add_mutually_exclusive_group(required=True)
    targets.add_argument("--all", action="store_true", dest="all_events")
    targets.add_argument("--before")
    delete.add_argument("--confirm", action="store_true", required=True)
    outcome = observe_command.add_parser("outcome")
    outcome_command = outcome.add_subparsers(dest="outcome_command", required=True)
    annotate = outcome_command.add_parser("annotate")
    annotate.add_argument("--correlation-id", required=True)
    for name in ("used-by-agent", "affected-decision", "task-success"):
        annotate.add_argument("--" + name, choices=["true", "false", "unknown"], required=True)
    for name in ("user-corrections", "retries", "turns", "tool-calls", "token-cost"):
        annotate.add_argument("--" + name, type=int)
    annotate.add_argument("--confirm", action="store_true", required=True)
    return parser


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nullable_bool(value: str) -> Any:
    return {"true": True, "false": False, "unknown": None}[value]


def _trace_write(repo: Optional[str], *, operation: str, trigger: str, source: str, kind: Optional[str], scope: str, identity_field: Optional[str], action: Any) -> Any:
    correlation = observability.new_correlation_id()
    base = {"operation": operation, "trigger": trigger, "source": source, "kind": kind, "scope": scope}
    observability.emit(repo, event_type="write_attempt", correlation_id=correlation, payload=base)
    try:
        result = action()
    except StorageConflictError:
        observability.emit(repo, event_type="write_result", correlation_id=correlation, payload={**base, "status": "failure", "reason": "conflict"})
        raise
    except (StorageError, RecordValidationError, ValueError):
        observability.emit(repo, event_type="write_result", correlation_id=correlation, payload={**base, "status": "failure", "reason": "storage_failure"})
        raise
    status = "success" if operation == "review" else ("created" if result.get("created", True) else "idempotent")
    identifiers = {identity_field: result["id"]} if identity_field and isinstance(result.get("id"), str) else {}
    observability.emit(repo, event_type="write_result", correlation_id=correlation, payload={**base, "status": status, "reason": None}, **identifiers)
    return result


def _trace_experience(repo: Optional[str], payload: str, args: Any) -> None:
    try:
        rendered = json.loads(payload)
        selected = rendered.get("selected", [])
        selector = json.dumps({"error_patterns": args.error_pattern, "paths": args.path, "signals": args.signal, "task_types": args.task_type}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        observability.emit(repo, event_type="retrieval", payload={"source": "experience", "query_digest": _digest(selector), "result_ids": [item["id"] for item in selected], "ranks": list(range(len(selected))), "scores": [None] * len(selected), "lifecycle": "active", "filter": "experience", "activated_relation_count": rendered.get("activated_relation_count"), "byte_budget": rendered.get("byte_budget"), "byte_count": rendered.get("byte_count"), "omitted_count": rendered.get("omitted_count")})
    except Exception:
        pass


def _trace_openviking(repo: Optional[str], query: str, payload: Any) -> None:
    try:
        results = payload.get("results", [])
        observability.emit(repo, event_type="retrieval", payload={"source": "openviking", "query_digest": _digest(query), "result_ids": ["ov-" + _digest(item["uri"]) for item in results], "ranks": list(range(len(results))), "scores": [None] * len(results), "lifecycle": None, "filter": "project", "activated_relation_count": None, "byte_budget": None, "byte_count": None, "omitted_count": None})
    except Exception:
        pass


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1

    try:
        if args.command == "init":
            payload = initialize_repository(args.repo)
            _print_json(payload)
            return 0

        if args.command == "status":
            payload = get_status(args.repo)
            _print_json(payload)
            return 0

        if args.command == "observability":
            if args.observability_command == "enable":
                payload = observability.configure(args.repo, enabled=True)
            elif args.observability_command == "disable":
                payload = observability.configure(args.repo, enabled=False)
            elif args.observability_command == "status":
                config = observability.load_config(args.repo)
                payload = {"configured": config is not None, "enabled": bool(config and config["enabled"])}
            elif args.observability_command == "export":
                payload = observability.export(args.repo, since=args.since, until=args.until)
            elif args.observability_command == "report":
                payload = observability.report(args.repo, day=args.date)
            elif args.observability_command == "delete":
                payload = {"deleted": observability.delete(args.repo, confirm=args.confirm, all_events=args.all_events, before=args.before)}
            elif args.observability_command == "outcome" and args.outcome_command == "annotate":
                metrics = {name: getattr(args, name) for name in ("user_corrections", "retries", "turns", "tool_calls", "token_cost")}
                if any(value is not None and value < 0 for value in metrics.values()):
                    raise ValueError("invalid outcome metrics")
                payload = {"annotated": observability.annotate_outcome(args.repo, correlation_id=args.correlation_id, confirm=args.confirm,
                    used_by_agent=_nullable_bool(args.used_by_agent), affected_decision=_nullable_bool(args.affected_decision), task_success=_nullable_bool(args.task_success), **metrics)}
            else:
                _emit_error("error: invalid arguments")
                return 2
            _print_json(payload)
            return 0

        if args.command == "checkpoint":
            if args.checkpoint_command != "create":
                _emit_error("error: unsupported checkpoint command")
                return 2

            try:
                content = _parse_content_json(args.content_json)
            except ValueError:
                _emit_error("error: invalid content-json")
                return 2

            payload = _trace_write(args.repo, operation="checkpoint", trigger="cli", source="cli", kind="checkpoint", scope="local", identity_field="record_id", action=lambda: create_checkpoint(args.repo, summary=args.summary, content=content, paths=args.path, record_id=args.id))
            payload["created"] = bool(payload.get("created", True))
            _print_json(payload)
            return 0

        if args.command == "candidate":
            if args.candidate_command == "propose":
                try:
                    content = _parse_content_json(args.content_json)
                except ValueError:
                    _emit_error("error: invalid content-json")
                    return 2
                if args.kind in ("strategy", "warning"):
                    if args.experience_json is None:
                        _emit_error("error: invalid experience-json")
                        return 2
                    try:
                        experience = _parse_experience_json(args.experience_json)
                    except ValueError:
                        _emit_error("error: invalid experience-json")
                        return 2
                elif args.experience_json is not None:
                    _emit_error("error: invalid arguments")
                    return 2
                else:
                    experience = None
                payload = _trace_write(args.repo, operation="candidate", trigger="cli", source="cli", kind=args.kind, scope="local", identity_field="candidate_id", action=lambda: create_candidate(args.repo, kind=args.kind, summary=args.summary, content=content, paths=args.path, semantic_role=args.semantic_role, record_id=args.id, experience=experience))
                payload["created"] = bool(payload.get("created", True))
                _print_json(payload)
                return 0

            _emit_error("error: unsupported candidate command")
            return 2

        if args.command == "review":
            payload = _trace_write(args.repo, operation="review", trigger="cli", source="explicit-review", kind=None, scope="project", identity_field="record_id", action=lambda: review_candidate(args.repo, candidate_id=args.candidate_id))
            _print_json(payload)
            return 0

        if args.command == "render":
            payload = render_continuity(args.repo)
            _print_json(payload)
            return 0

        if args.command == "experience":
            if args.experience_command != "match":
                _emit_error("error: invalid arguments")
                return 2
            payload = render_experience_match(
                load_trusted_experiences(args.repo), task_types=args.task_type, signals=args.signal,
                error_patterns=args.error_pattern, paths=args.path, max_bytes=args.max_bytes,
            )
            if payload is None:
                raise StorageError("experience rendering failed")
            _trace_experience(args.repo, payload, args)
            sys.stdout.write(payload)
            return 0

        if args.command == "retrieve":
            payload = retrieve_project_knowledge(
                args.repo,
                args.query,
                args.openviking_cli,
                args.openviking_config,
                limit=args.limit,
            )
            _trace_openviking(args.repo, args.query, payload)
            _print_json(payload)
            return 0

        if args.command == "schedule":
            if args.schedule_command == "configure":
                payload = configure_schedule(
                    args.repo, provider=args.provider, model=args.model, cron=args.cron,
                    timezone=args.timezone, reasoning_effort=args.reasoning_effort, enabled=args.enable,
                )
            elif args.schedule_command == "enable":
                payload = enable_scheduler_config(args.repo)
            elif args.schedule_command == "disable":
                payload = disable_scheduler_config(args.repo)
            elif args.schedule_command == "status":
                payload = schedule_status(args.repo)
            elif args.schedule_command == "plan":
                payload = schedule_plan(args.repo)
            elif args.schedule_command == "run":
                if args.dry_run:
                    payload = run_schedule(args.repo, dry_run=True)
                else:
                    correlation = observability.new_correlation_id()
                    base = {"operation": "candidate", "trigger": "schedule", "source": "scheduled-ai", "kind": None, "scope": "local"}
                    observability.emit(args.repo, event_type="write_attempt", correlation_id=correlation, payload=base)
                    try:
                        payload = run_schedule(args.repo, dry_run=False)
                    except Exception:
                        observability.emit(args.repo, event_type="write_result", correlation_id=correlation, payload={**base, "status": "failure", "reason": "storage_failure"})
                        raise
                    rejected = payload.get("rejected_count", 0)
                    succeeded = bool(payload.get("candidates"))
                    observability.emit(args.repo, event_type="write_result", correlation_id=correlation, payload={**base, "status": "rejected" if rejected and not succeeded else "success", "reason": "invalid" if rejected and not succeeded else None})
            else:
                _emit_error("error: invalid arguments")
                return 2
            _print_json(payload)
            return 0

        _emit_error("error: unsupported command")
        return 2

    except (OpenVikingError, RecordValidationError, StorageConflictError, StorageError, ScheduleRuntimeError, ValueError):
        _emit_error("error: operation failed")
        return 1

    except (StoragePathError, RuntimeError):
        _emit_error("error: operation failed")
        return 1

    except Exception:
        _emit_error("error")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
