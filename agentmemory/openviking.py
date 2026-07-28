"""Read-only, project-scoped OpenViking retrieval."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Sequence, Union
from urllib.parse import unquote

from .identity import GitIdentityError, get_git_identity
from .security import SecretScanError, scan_for_secrets


RETRIEVAL_ERROR = "openviking retrieval failed"
DEFAULT_LIMIT = 3
MAX_LIMIT = 5
MAX_QUERY_CHARS = 1024
MAX_URI_CHARS = 4096
MAX_TEXT_CHARS = 2048
MAX_SERVER_TIME_CHARS = 128
MAX_OUTPUT_BYTES = 256 * 1024
MAX_PAYLOAD_BYTES = 64 * 1024
COMMAND_TIMEOUT_SECONDS = 5.0
OPENVIKING_CLI_CONFIG_ENV = "OPENVIKING_CLI_CONFIG_FILE"
_WRAPPER_SUFFIXES = {".cmd", ".bat", ".ps1"}
_REPOSITORY_ID = re.compile(r"^[0-9a-f]{64}$")
_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


class OpenVikingError(RuntimeError):
    """Raised when untrusted OpenViking retrieval cannot be verified."""


def _fail() -> None:
    raise OpenVikingError(RETRIEVAL_ERROR)


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")


def _strict_json(raw: str, allowed_echo: str = "") -> Any:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_OUTPUT_BYTES:
        _fail()
    if raw.startswith("cmd: "):
        lines = raw.splitlines()
        expected = "cmd: ov " + allowed_echo + " "
        if not allowed_echo or len(lines) != 2 or not lines[0].startswith(expected):
            _fail()
        raw = lines[1]
    try:
        return json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc


def _run_json(
    command: Sequence[str],
    working_directory: Path,
    environment: Dict[str, str],
    allowed_echo: str = "",
) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(working_directory),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=COMMAND_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc

    if (
        completed.returncode != 0
        or not isinstance(completed.stdout, str)
        or not isinstance(completed.stderr, str)
        or len(completed.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES
        or len(completed.stderr.encode("utf-8")) > MAX_OUTPUT_BYTES
    ):
        _fail()
    payload = _strict_json(completed.stdout, allowed_echo)
    if not isinstance(payload, dict) or set(payload) != {"ok", "result"} or payload["ok"] is not True:
        _fail()
    if not isinstance(payload["result"], dict):
        _fail()
    return payload["result"]


def _native_executable(raw_path: Union[str, Path]) -> Path:
    try:
        path = Path(raw_path)
    except (TypeError, ValueError) as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    if not path.is_absolute() or path.suffix.lower() in _WRAPPER_SUFFIXES:
        _fail()
    return path


def _config_file(raw_path: Union[str, Path]) -> Path:
    try:
        path = Path(raw_path)
        if not path.is_absolute():
            _fail()
        file_stat = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    if stat.S_ISLNK(file_stat.st_mode) or _is_reparse_point(file_stat) or not resolved.is_file():
        _fail()
    return resolved


def _project_root(identity: Dict[str, str]) -> tuple[Path, str, str]:
    repository_id = identity.get("repository_id")
    toplevel = identity.get("toplevel")
    if not isinstance(repository_id, str) or not _REPOSITORY_ID.fullmatch(repository_id):
        _fail()
    if not isinstance(toplevel, str) or not toplevel:
        _fail()
    try:
        repo_root = Path(toplevel).resolve(strict=True)
    except OSError as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    if not repo_root.is_dir():
        _fail()
    return repo_root, repository_id, "viking://resources/projects/repo-" + repository_id


def _validated_query(query: str) -> str:
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > MAX_QUERY_CHARS
        or any(ord(character) < 32 for character in query)
    ):
        _fail()
    try:
        scan_for_secrets(query)
    except SecretScanError as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    return query


def _validated_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        _fail()
    return limit


def _uri_parts(uri: str, project_uri: str) -> List[str]:
    prefix = project_uri + "/"
    if not isinstance(uri, str) or len(uri) > MAX_URI_CHARS or not uri.startswith(prefix):
        _fail()
    suffix = uri[len(prefix) :]
    if not suffix or "?" in suffix or "#" in suffix or "\\" in suffix:
        _fail()

    parts: List[str] = []
    for raw_part in suffix.split("/"):
        if not raw_part or _PERCENT_ESCAPE.search(raw_part):
            _fail()
        try:
            part = unquote(raw_part, encoding="utf-8", errors="strict")
        except UnicodeError as exc:
            raise OpenVikingError(RETRIEVAL_ERROR) from exc
        if (
            not part
            or part in {".", ".."}
            or "%" in part
            or "/" in part
            or "\\" in part
            or "\x00" in part
            or ":" in part
            or PurePosixPath(part).is_absolute()
            or PureWindowsPath(part).is_absolute()
        ):
            _fail()
        parts.append(part)
    return parts


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(file_stat, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _validate_path_snapshot(snapshot: Sequence[tuple[Path, int, int]]) -> None:
    try:
        for path, device, inode in snapshot:
            current = path.lstat()
            if (
                stat.S_ISLNK(current.st_mode)
                or _is_reparse_point(current)
                or current.st_dev != device
                or current.st_ino != inode
            ):
                _fail()
    except OSError as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc


def _current_local_evidence(repo_root: Path, uri: str, project_uri: str) -> Dict[str, str]:
    candidate = repo_root.joinpath(*_uri_parts(uri, project_uri))
    path_snapshot: List[tuple[Path, int, int]] = []
    try:
        current = repo_root
        for part in candidate.relative_to(repo_root).parts:
            current = current / part
            current_stat = current.lstat()
            if stat.S_ISLNK(current_stat.st_mode) or _is_reparse_point(current_stat):
                _fail()
            path_snapshot.append((current, current_stat.st_dev, current_stat.st_ino))
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
        before = resolved.lstat()
    except (OSError, ValueError) as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    if not stat.S_ISREG(before.st_mode) or _is_reparse_point(before):
        _fail()

    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(resolved), flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            _validate_path_snapshot(path_snapshot)
            current_path = resolved.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_ISLNK(current_path.st_mode)
                or _is_reparse_point(current_path)
                or opened.st_dev != current_path.st_dev
                or opened.st_ino != current_path.st_ino
            ):
                _fail()
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(source.fileno())
        _validate_path_snapshot(path_snapshot)
        final_path = resolved.lstat()
    except OSError as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    if (
        not stat.S_ISREG(after.st_mode)
        or stat.S_ISLNK(final_path.st_mode)
        or _is_reparse_point(final_path)
        or opened.st_dev != after.st_dev
        or opened.st_ino != after.st_ino
        or opened.st_mtime_ns != after.st_mtime_ns
        or opened.st_size != after.st_size
        or after.st_dev != final_path.st_dev
        or after.st_ino != final_path.st_ino
    ):
        _fail()

    return {
        "path": resolved.relative_to(repo_root).as_posix(),
        "mtime_utc": datetime.fromtimestamp(after.st_mtime, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "sha256": digest.hexdigest(),
        "hash_kind": "current_local_file_sha256",
    }


def _resource_result(
    resource: Any,
    repo_root: Path,
    project_uri: str,
    executable: Path,
    working_directory: Path,
    environment: Dict[str, str],
) -> Dict[str, Any]:
    if not isinstance(resource, dict):
        _fail()
    uri = resource.get("uri")
    if (
        resource.get("context_type") != "resource"
        or isinstance(resource.get("level"), bool)
        or resource.get("level") != 2
    ):
        _fail()
    _uri_parts(uri, project_uri)
    server = _run_json(
        [str(executable), "stat", uri, "-o", "json"],
        working_directory,
        environment,
    )
    mod_time = server.get("modTime")
    if (
        not isinstance(mod_time, str)
        or not mod_time
        or len(mod_time) > MAX_SERVER_TIME_CHARS
        or server.get("isDir") is not False
    ):
        _fail()

    output: Dict[str, Any] = {
        "uri": uri,
        "server_mod_time": mod_time,
        "current_local_evidence": _current_local_evidence(repo_root, uri, project_uri),
    }
    for key in ("abstract", "overview"):
        value = resource.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > MAX_TEXT_CHARS:
            _fail()
        output[key] = value
    try:
        scan_for_secrets(output)
    except SecretScanError as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    return output


def retrieve_project_knowledge(
    repo_path: Union[str, Path],
    query: str,
    openviking_executable: Union[str, Path],
    openviking_config: Union[str, Path],
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """Retrieve only untrusted resources under the current repository URI."""

    try:
        executable = _native_executable(openviking_executable)
        config = _config_file(openviking_config)
        environment = os.environ.copy()
        environment[OPENVIKING_CLI_CONFIG_ENV] = str(config)
        validated_query = _validated_query(query)
        validated_limit = _validated_limit(limit)
        identity = get_git_identity(repo_path)
        repo_root, repository_id, project_uri = _project_root(identity)

        health = _run_json(
            [str(executable), "health", "-o", "json"],
            config.parent,
            environment,
        )
        if health.get("healthy") is not True:
            _fail()
        found = _run_json(
            [
                str(executable),
                "find",
                validated_query,
                "--uri",
                project_uri,
                "--limit",
                str(validated_limit),
                "--level",
                "2",
                "--context-type",
                "resource",
                "-o",
                "json",
                "--compact",
                "true",
            ],
            config.parent,
            environment,
            "find",
        )
        memories = found.get("memories")
        skills = found.get("skills")
        resources = found.get("resources")
        if memories != [] or skills != [] or not isinstance(resources, list) or len(resources) > validated_limit:
            _fail()

        results = [
            _resource_result(
                resource,
                repo_root,
                project_uri,
                executable,
                config.parent,
                environment,
            )
            for resource in resources
        ]
        payload: Dict[str, Any] = {
            "read_only": True,
            "untrusted": True,
            "repository_id": repository_id,
            "project_uri": project_uri,
            "results": results,
        }
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            _fail()
        scan_for_secrets(payload)
        scan_for_secrets(serialized)
        return payload
    except OpenVikingError:
        raise
    except (GitIdentityError, SecretScanError, OSError, TypeError, ValueError, UnicodeError) as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
    except Exception as exc:
        raise OpenVikingError(RETRIEVAL_ERROR) from exc
