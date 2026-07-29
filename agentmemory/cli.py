"""CLI for local checkpoint persistence."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional, Sequence

from .openviking import OpenVikingError, retrieve_project_knowledge
from .schema import RecordValidationError
from .storage import (
    StorageConflictError,
    StorageError,
    StoragePathError,
    create_checkpoint,
    create_candidate,
    review_candidate,
    render_continuity,
    get_status,
    initialize_repository,
    load_trusted_experiences,
)
from .render import render_experience_match


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
    return parser


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

        if args.command == "checkpoint":
            if args.checkpoint_command != "create":
                _emit_error("error: unsupported checkpoint command")
                return 2

            try:
                content = _parse_content_json(args.content_json)
            except ValueError:
                _emit_error("error: invalid content-json")
                return 2

            payload = create_checkpoint(
                args.repo,
                summary=args.summary,
                content=content,
                paths=args.path,
                record_id=args.id,
            )
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
                payload = create_candidate(
                    args.repo,
                    kind=args.kind,
                    summary=args.summary,
                    content=content,
                    paths=args.path,
                    semantic_role=args.semantic_role,
                    record_id=args.id,
                    experience=experience,
                )
                payload["created"] = bool(payload.get("created", True))
                _print_json(payload)
                return 0

            _emit_error("error: unsupported candidate command")
            return 2

        if args.command == "review":
            payload = review_candidate(args.repo, candidate_id=args.candidate_id)
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
            _print_json(payload)
            return 0

        _emit_error("error: unsupported command")
        return 2

    except (OpenVikingError, RecordValidationError, StorageConflictError, StorageError, ValueError):
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
