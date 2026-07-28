"""Git repository/worktree identity helpers for AgentMemory."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union


GIT_IDENTITY_ERROR = "unable to resolve git repository identity"


class GitIdentityError(RuntimeError):
    """Raised when repository identity cannot be safely resolved."""


def _safe_path(raw: str, base: Path) -> str:
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    try:
        normalized = path.resolve()
    except OSError as exc:
        raise GitIdentityError(GIT_IDENTITY_ERROR) from exc
    return str(normalized).replace("\\", "/")


def _run_git(args: Sequence[str], cwd: Path, timeout: float) -> List[str]:
    command = ["git", "-C", str(cwd), *args]
    try:
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="strict",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - environment specific failures
        raise GitIdentityError(GIT_IDENTITY_ERROR) from exc
    if result.returncode != 0:
        raise GitIdentityError(GIT_IDENTITY_ERROR)
    return [line.strip() for line in result.stdout.splitlines()]


def _run_git_required(args: List[str], cwd: Path, timeout: float) -> str:
    output = _run_git(args, cwd, timeout)
    if len(output) != 1:
        raise GitIdentityError(GIT_IDENTITY_ERROR)
    value = output[0]
    if not value:
        raise GitIdentityError(GIT_IDENTITY_ERROR)
    return value


def _run_git_optional(args: List[str], cwd: Path, timeout: float) -> Optional[str]:
    try:
        return _run_git_required(args, cwd, timeout)
    except GitIdentityError:
        return None


def _safe_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_git_identity(path: Optional[Union[Path, str]] = None) -> Dict[str, str]:
    """Return repository identity and checked-out state for a local worktree."""

    repo_root = Path(path if path is not None else os.getcwd())
    repo_root = repo_root.resolve()
    timeout = 1.5

    raw_toplevel = _run_git_required(["rev-parse", "--show-toplevel"], repo_root, timeout)
    raw_common_dir = _run_git_required(["rev-parse", "--git-common-dir"], repo_root, timeout)
    is_bare = _run_git_required(["rev-parse", "--is-bare-repository"], repo_root, timeout).lower()
    branch = _run_git_optional(["symbolic-ref", "--short", "HEAD"], repo_root, timeout)

    if is_bare != "false":
        raise GitIdentityError(GIT_IDENTITY_ERROR)
    if branch is None:
        branch = "DETACHED"

    head = _run_git_optional(["rev-parse", "--verify", "HEAD"], repo_root, timeout)
    if head is None:
        if branch == "DETACHED":
            raise GitIdentityError(GIT_IDENTITY_ERROR)
        head = "UNBORN"
    else:
        head = head.lower()
        if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
            raise GitIdentityError(GIT_IDENTITY_ERROR)

    toplevel = _safe_path(raw_toplevel, repo_root)
    common_dir = _safe_path(raw_common_dir, repo_root)

    return {
        "toplevel": toplevel,
        "common_dir": common_dir,
        "repository_id": _safe_sha256(common_dir),
        "worktree_id": _safe_sha256(toplevel),
        "branch": branch,
        "head": head,
    }
