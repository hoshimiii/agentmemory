import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from unittest import mock

from agentmemory import schema
from agentmemory.identity import get_git_identity
from agentmemory.render import (
    MAX_RESUME_CAPSULE_CHARS,
    RESUME_CAPSULE_SAFETY_PREFIX,
    render_resume_capsule,
)
from agentmemory.storage import (
    create_candidate,
    create_checkpoint,
    initialize_repository,
    review_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "hooks" / "agentmemory_hook.py"
FALLBACK_OUTPUT = '{"continue":true}'
SENSITIVE_FIELDS = {
    "cwd": "C:\\Users\\agent\\agentmemory-secret-cwd",
    "transcript_path": "C:\\Users\\agent\\transcripts\\agentmemory_secret_session.jsonl",
    "source": "source://agentmemory/sensitive-token-7f4",
    "session_id": "session-secret-2026-07-23",
}


def _run_git(args: Iterable[str], cwd: Path, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if env:
        environment.update(env)

    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())
    return result


def _init_git_repo(path: Path) -> None:
    _run_git(["init", "--initial-branch=main"], path)
    _run_git(["config", "user.name", "agentmemory"], path)
    _run_git(["config", "user.email", "agentmemory@example.com"], path)
    _run_git(["commit", "--allow-empty", "-m", "init"], path)


def _run_hook(
    action: str,
    payload: Dict[str, Any],
    cwd: Path,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DISPATCHER), action],
        text=True,
        input=json.dumps(payload),
        capture_output=True,
        env={**os.environ, **(env or {})},
        cwd=str(cwd),
    )


def _snapshot(path: Path) -> Dict[str, str]:
    states: Dict[str, str] = {}
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        rel = child.relative_to(path).as_posix()
        if child.is_file():
            states[rel] = f"file:{hashlib.sha256(child.read_bytes()).hexdigest()}"
        elif child.is_dir():
            states[rel] = "dir"
    return states


def _parse_context(result: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
    payload = json.loads(result.stdout)
    return json.loads(payload["hookSpecificOutput"]["additionalContext"])


class TestAgentMemoryHookRuntime(unittest.TestCase):
    def assert_no_sensitive_leak(self, stdout: str, stderr: str) -> None:
        for _, value in SENSITIVE_FIELDS.items():
            self.assertNotIn(value, stdout)
            self.assertNotIn(value, stderr)

        combined = stdout + stderr
        self.assertNotIn("traceback", combined.lower())

    def test_checkpoint_select_by_created_at_and_id_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                side_effect=[
                    "2026-07-23T00:00:01Z",
                    "2026-07-23T00:00:01Z",
                    "2026-07-23T00:00:01Z",
                ],
            ):
                create_checkpoint(repo, "first", {"value": 1}, record_id="cp-bbb")
                create_checkpoint(repo, "second", {"value": 2}, record_id="cp-aaa")
                create_checkpoint(repo, "latest", {"value": 3}, record_id="cp-zzz")

            create_candidate(
                repo,
                kind="decision",
                summary="project c",
                content={"value": "v3"},
                record_id="cand-c",
            )
            create_candidate(
                repo,
                kind="decision",
                summary="project a",
                content={"value": "v1"},
                record_id="cand-a",
            )
            create_candidate(
                repo,
                kind="decision",
                summary="project b",
                content={"value": "v2"},
                record_id="cand-b",
            )
            review_candidate(repo, "cand-a")
            review_candidate(repo, "cand-b")
            review_candidate(repo, "cand-c")

            payload = {
                "hook_event_name": "SessionStart",
                "cwd": str(repo),
                "session_id": "runtime-a",
                "payload": {"matcher": "startup"},
            }
            before = _snapshot(repo)
            first = _run_hook("session-start", payload, repo)
            after = _snapshot(repo)
            second = _run_hook("session-start", payload, repo)

            self.assertEqual(first.returncode, 0)
            self.assertEqual(first.stderr, "")
            self.assertEqual(second.stderr, "")
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(first.stdout, second.stdout)
            self.assertNotEqual(first.stdout, FALLBACK_OUTPUT)
            self.assertEqual(before, after)

            self.assert_no_sensitive_leak(first.stdout, first.stderr)
            capsule = _parse_context(first)
            self.assertEqual(capsule["checkpoint"]["id"], "cp-zzz")
            self.assertEqual(capsule["stale_head"], False)
            self.assertEqual(capsule["safety"], RESUME_CAPSULE_SAFETY_PREFIX)
            context = json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(len(context), MAX_RESUME_CAPSULE_CHARS)
            self.assertLessEqual(len(context.encode("utf-8")), MAX_RESUME_CAPSULE_CHARS)

            project_record_ids = [record["id"] for record in capsule["project_records"]]
            self.assertEqual(project_record_ids, sorted(project_record_ids))

    def test_branch_filter_and_detached_head_rule(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            create_checkpoint(repo, "main checkpoint", {"value": 1}, record_id="cp-main")
            create_candidate(
                repo,
                kind="decision",
                summary="main first",
                content={"value": "main"},
                record_id="cand-main-a",
            )
            create_candidate(
                repo,
                kind="decision",
                summary="main second",
                content={"value": "main"},
                record_id="cand-main-b",
            )
            review_candidate(repo, "cand-main-a")
            review_candidate(repo, "cand-main-b")

            main_result = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(repo),
                    "session_id": "runtime-branch-main",
                    "payload": {"matcher": "startup"},
                },
                repo,
            )
            self.assertEqual(main_result.returncode, 0)
            self.assertNotEqual(main_result.stdout, FALLBACK_OUTPUT)
            main_capsule = _parse_context(main_result)
            self.assertEqual(main_capsule["branch"], "main")
            self.assertFalse(main_capsule["stale_head"])
            self.assertEqual(len(main_capsule["project_records"]), 2)
            main_ids = [record["id"] for record in main_capsule["project_records"]]
            self.assertEqual(main_ids, sorted(main_ids))

            _run_git(["checkout", "--detach", "HEAD"], repo)
            detached_head_before = _run_git(["rev-parse", "HEAD"], repo).stdout.strip()
            self.assertTrue(detached_head_before)

            create_checkpoint(
                repo,
                "detached checkpoint one",
                {"value": "detached one"},
                record_id="cp-det1",
            )
            create_candidate(
                repo,
                kind="incident",
                summary="detached old",
                content={"value": "det-old"},
                record_id="cand-det-old",
            )
            review_candidate(repo, "cand-det-old")

            _run_git(["commit", "--allow-empty", "-m", "detached progress"], repo)
            detached_head_after = _run_git(["rev-parse", "HEAD"], repo).stdout.strip()
            self.assertNotEqual(detached_head_after, detached_head_before)

            create_checkpoint(
                repo,
                "detached checkpoint two",
                {"value": "detached two"},
                record_id="cp-det2",
            )
            create_candidate(
                repo,
                kind="incident",
                summary="detached new",
                content={"value": "det-new"},
                record_id="cand-det-new",
            )
            review_candidate(repo, "cand-det-new")

            detached_result = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(repo),
                    "session_id": "runtime-branch-detached",
                    "payload": {"matcher": "startup"},
                },
                repo,
            )
            self.assertEqual(detached_result.returncode, 0)
            self.assertNotEqual(detached_result.stdout, FALLBACK_OUTPUT)
            detached_capsule = _parse_context(detached_result)
            self.assertEqual(detached_capsule["branch"], "DETACHED")
            self.assertEqual(detached_capsule["head"], detached_head_after)
            self.assertEqual(detached_capsule["checkpoint"]["id"], "cp-det2")
            self.assertEqual(len(detached_capsule["project_records"]), 1)
            self.assertEqual(detached_capsule["project_records"][0]["summary"], "detached new")

            self.assert_no_sensitive_leak(detached_result.stdout, detached_result.stderr)

    def test_no_checkpoint_and_uninitialized_repos_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            initialized_repo = Path(workdir) / "initialized"
            initialized_repo.mkdir()
            _init_git_repo(initialized_repo)
            initialize_repository(initialized_repo)

            no_checkpoint = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(initialized_repo),
                    "session_id": "runtime-no-checkpoint",
                },
                initialized_repo,
            )
            self.assertEqual(no_checkpoint.returncode, 0)
            self.assertEqual(no_checkpoint.stdout, FALLBACK_OUTPUT)
            self.assertEqual(no_checkpoint.stderr, "")

            uninitialized = Path(workdir) / "uninitialized"
            uninitialized.mkdir()
            _run_git(["init", "--initial-branch=main"], uninitialized)
            bad = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(uninitialized),
                    "session_id": "runtime-uninitialized",
                },
                uninitialized,
            )
            self.assertEqual(bad.returncode, 0)
            self.assertEqual(bad.stdout, FALLBACK_OUTPUT)
            self.assertEqual(bad.stderr, "")
            self.assert_no_sensitive_leak(bad.stdout, bad.stderr)

    def test_stale_head_capsule_has_no_checkpoint_and_ignores_candidate_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            identity = get_git_identity(repo)
            candidate_dir = (
                repo
                / ".continuity"
                / "local"
                / "worktrees"
                / identity["worktree_id"]
                / "candidates"
            )
            candidate_dir.mkdir(parents=True, exist_ok=True)

            create_checkpoint(repo, "main checkpoint", {"value": "value"}, record_id="cp-main")
            create_candidate(
                repo,
                kind="decision",
                summary="confirmed project",
                content={"value": "confirmed"},
                record_id="cand-main",
            )
            review_candidate(repo, "cand-main")

            continuity = repo / ".continuity" / "CONTINUITY.md"
            continuity.write_text(
                "arbitrary user content that the resume hook must not read or replace\n",
                encoding="utf-8",
            )

            (candidate_dir / "bad-candidate.json").write_text(
                '{"secret":"sk-abc123456789012345678901234567890"}',
                encoding="utf-8",
            )

            outside = repo.parent / "outside-candidate.json"
            outside.write_text("{}", encoding="utf-8")
            try:
                (candidate_dir / "symlink-candidate.json").symlink_to(outside)
            except OSError:
                pass

            _run_git(["commit", "--allow-empty", "-m", "advance head"], repo)
            stale = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(repo),
                    "session_id": "runtime-stale",
                    "transcript_path": SENSITIVE_FIELDS["transcript_path"],
                },
                repo,
            )
            self.assertEqual(stale.returncode, 0)
            self.assertNotEqual(stale.stdout, FALLBACK_OUTPUT)
            stale_capsule = _parse_context(stale)
            self.assertTrue(stale_capsule["stale_head"])
            self.assertNotIn("checkpoint", stale_capsule)
            self.assertNotIn("summary", stale_capsule)
            self.assertNotIn("content", stale_capsule)
            self.assertNotIn("paths", stale_capsule)
            self.assertNotIn("id", stale_capsule)
            self.assertEqual(len(stale_capsule["project_records"]), 1)
            self.assertEqual(stale_capsule["project_records"][0]["summary"], "confirmed project")
            self.assertEqual(
                continuity.read_text(encoding="utf-8"),
                "arbitrary user content that the resume hook must not read or replace\n",
            )
            self.assert_no_sensitive_leak(stale.stdout, stale.stderr)

    def test_resume_renderer_rejects_inconsistent_or_secret_bearing_state(self) -> None:
        base = {
            "branch": "main",
            "head": "a" * 40,
            "stale_head": False,
            "checkpoint": {"id": "cp-main", "token": "short-secret"},
            "project_records": [],
        }
        self.assertIsNone(render_resume_capsule(base))
        self.assertIsNone(
            render_resume_capsule(
                {
                    **base,
                    "stale_head": True,
                }
            )
        )
        self.assertIsNone(
            render_resume_capsule(
                {
                    **base,
                    "checkpoint": {"id": "cp-main"},
                    "project_records": ["not-a-record"],
                }
            )
        )

    def test_checkpoint_failure_modes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            create_checkpoint(repo, "base", {"value": 1}, record_id="cp-base")
            cases = [
                "malformed",
                "wrong_extension",
                "wrong_type",
                "cross_repo",
                "cross_worktree",
                "filename_mismatch",
                "symlink",
            ]

            for name in cases:
                with self.subTest(name=name):
                    with tempfile.TemporaryDirectory() as nested:
                        nested_repo = Path(nested) / "repo"
                        nested_repo.mkdir()
                        _init_git_repo(nested_repo)
                        initialize_repository(nested_repo)
                        create_checkpoint(
                            nested_repo,
                            "base",
                            {"value": 1},
                            record_id="cp-base",
                        )

                        nested_identity = get_git_identity(nested_repo)
                        nested_checkpoint_dir = (
                            nested_repo
                            / ".continuity"
                            / "local"
                            / "worktrees"
                            / nested_identity["worktree_id"]
                            / "checkpoints"
                        )
                        nested_payload_path = nested_checkpoint_dir / "cp-base.json"

                        nested_check_payload = json.loads(
                            nested_payload_path.read_text(encoding="utf-8")
                        )

                        if name == "malformed":
                            nested_payload_path.write_text("{", encoding="utf-8")
                        elif name == "wrong_extension":
                            nested_payload_path.rename(nested_checkpoint_dir / "cp-base.txt")
                        elif name == "filename_mismatch":
                            nested_payload_path.rename(nested_checkpoint_dir / "other.json")
                        elif name == "symlink":
                            target = nested_repo.parent / "outside-checkpoint.json"
                            target.write_text(
                                json.dumps(
                                    nested_check_payload,
                                    separators=(",", ":"),
                                ),
                                encoding="utf-8",
                            )
                            nested_payload_path.unlink()
                            try:
                                nested_payload_path.symlink_to(target)
                            except OSError:
                                self.skipTest("filesystem does not allow symlinks")
                        elif name == "wrong_type":
                            nested_check_payload["record_type"] = "project_record"
                            nested_payload_path.write_text(
                                json.dumps(
                                    schema.annotate_with_integrity(
                                        nested_check_payload,
                                        version=1,
                                    ),
                                    separators=(",", ":"),
                                ),
                                encoding="utf-8",
                            )
                        elif name == "cross_repo":
                            nested_check_payload["applies_to"] = {
                                **nested_check_payload["applies_to"],
                                "repository_id": "f" * 64,
                            }
                            nested_payload_path.write_text(
                                json.dumps(
                                    schema.annotate_with_integrity(
                                        nested_check_payload,
                                        version=1,
                                    ),
                                    separators=(",", ":"),
                                ),
                                encoding="utf-8",
                            )
                        elif name == "cross_worktree":
                            nested_check_payload["applies_to"] = {
                                **nested_check_payload["applies_to"],
                                "worktree_id": "f" * 64,
                            }
                            nested_payload_path.write_text(
                                json.dumps(
                                    schema.annotate_with_integrity(
                                        nested_check_payload,
                                        version=1,
                                    ),
                                    separators=(",", ":"),
                                ),
                                encoding="utf-8",
                            )

                        result = _run_hook(
                            "session-start",
                            {
                                "hook_event_name": "SessionStart",
                                "cwd": str(nested_repo),
                                "session_id": "runtime-fail-" + name,
                            },
                            nested_repo,
                        )
                        self.assertEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, FALLBACK_OUTPUT)
                        self.assertEqual(result.stderr, "")
                        self.assert_no_sensitive_leak(result.stdout, result.stderr)

    def test_shared_cross_repo_and_invalid_branch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            create_checkpoint(repo, "checkpoint", {"value": 1}, record_id="cp-main")
            create_candidate(
                repo,
                kind="decision",
                summary="shared project",
                content={"value": "project"},
                record_id="cand-main",
            )
            result = review_candidate(repo, "cand-main")
            shared_record = (
                repo
                / ".continuity"
                / "shared"
                / "records"
                / f"{result['id']}.json"
            )
            payload = json.loads(shared_record.read_text(encoding="utf-8"))

            with self.subTest("cross_repo"):
                payload["applies_to"] = {
                    **payload["applies_to"],
                    "repository_id": "f" * 64,
                }
                shared_record.write_text(
                    json.dumps(schema.annotate_with_integrity(payload, version=1), separators=(",", ":")),
                    encoding="utf-8",
                )

                cross_repo = _run_hook(
                    "session-start",
                    {
                        "hook_event_name": "SessionStart",
                        "cwd": str(repo),
                        "session_id": "runtime-shared-cross-repo",
                    },
                    repo,
                )
                self.assertEqual(cross_repo.returncode, 0)
                self.assertEqual(cross_repo.stdout, FALLBACK_OUTPUT)
                self.assertEqual(cross_repo.stderr, "")

            with self.subTest("invalid_branch"):
                payload["applies_to"] = {
                    **payload["applies_to"],
                    "repository_id": get_git_identity(repo)["repository_id"],
                    "branch": "invalid branch",
                }
                shared_record.write_text(
                    json.dumps(schema.annotate_with_integrity(payload, version=1), separators=(",", ":")),
                    encoding="utf-8",
                )
                invalid = _run_hook(
                    "session-start",
                    {
                        "hook_event_name": "SessionStart",
                        "cwd": str(repo),
                        "session_id": "runtime-shared-invalid-branch",
                    },
                    repo,
                )
                self.assertEqual(invalid.returncode, 0)
                self.assertEqual(invalid.stdout, FALLBACK_OUTPUT)
                self.assertEqual(invalid.stderr, "")
                self.assert_no_sensitive_leak(invalid.stdout, invalid.stderr)

    def test_large_project_set_and_checkpoint_budget_limits(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            create_checkpoint(repo, "base", {"value": 1}, record_id="cp-base")
            for index in range(40):
                create_candidate(
                    repo,
                    kind="decision",
                    summary=f"project-{index:03d}",
                    content={"value": "x" * 250},
                    record_id=f"cand-{index:03d}",
                )
                review_candidate(repo, f"cand-{index:03d}")

            result = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(repo),
                    "session_id": "runtime-large-projects",
                },
                repo,
            )
            self.assertEqual(result.returncode, 0)
            self.assertNotEqual(result.stdout, FALLBACK_OUTPUT)
            capsule = _parse_context(result)
            context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(len(context), MAX_RESUME_CAPSULE_CHARS)
            self.assertLessEqual(len(context.encode("utf-8")), MAX_RESUME_CAPSULE_CHARS)
            self.assertIn("omitted_project_record_count", capsule)
            self.assertEqual(
                capsule["omitted_project_record_count"],
                40 - len(capsule["project_records"]),
            )
            self.assertEqual(capsule["project_records"][0]["record_type"], "project_record")

            json.loads(result.stdout)

            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                side_effect=[
                    "2026-07-23T00:00:01Z",
                    "2026-07-23T00:00:02Z",
                ],
            ):
                create_checkpoint(
                    repo,
                    "small base",
                    {"value": "small"},
                    record_id="cp-small",
                )
                create_checkpoint(
                    repo,
                    "huge checkpoint",
                    {"payload": "x" * 6500},
                    record_id="cp-huge",
                )

            huge = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(repo),
                    "session_id": "runtime-huge",
                },
                repo,
            )
            self.assertEqual(huge.stdout, FALLBACK_OUTPUT)

    def test_precompact_payload_is_idempotent_and_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            before = _snapshot(repo)
            payload = {
                "hook_event_name": "PreCompact",
                "session_id": "runtime-precompact",
                "payload": {"matcher": "auto"},
            }
            first = _run_hook("pre-compact", payload, repo)
            second = _run_hook("pre-compact", payload, repo)

            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 0)
            self.assertEqual(first.stdout, FALLBACK_OUTPUT)
            self.assertEqual(second.stdout, FALLBACK_OUTPUT)
            self.assertEqual(first.stderr, "")
            self.assertEqual(second.stderr, "")
            self.assertEqual(_snapshot(repo), before)
            self.assertEqual(first.stdout, second.stdout)
            self.assert_no_sensitive_leak(first.stdout + second.stdout, first.stderr + second.stderr)

    def test_runtime_payloads_do_not_leak_sensitive_information(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            initialize_repository(repo)

            result = _run_hook(
                "session-start",
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(repo),
                    "session_id": SENSITIVE_FIELDS["session_id"],
                    "transcript_path": SENSITIVE_FIELDS["transcript_path"],
                    "payload": {"notes": SENSITIVE_FIELDS["source"]},
                    "source": SENSITIVE_FIELDS["source"],
                },
                repo,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, FALLBACK_OUTPUT)
            self.assertEqual(result.stderr, "")

            compact = _run_hook(
                "pre-compact",
                {
                    "hook_event_name": "PreCompact",
                    "session_id": SENSITIVE_FIELDS["session_id"],
                    "transcript_path": SENSITIVE_FIELDS["transcript_path"],
                    "source": SENSITIVE_FIELDS["source"],
                },
                repo,
            )
            self.assertEqual(compact.returncode, 0)
            self.assertEqual(compact.stdout, FALLBACK_OUTPUT)
            self.assertEqual(compact.stderr, "")

            self.assert_no_sensitive_leak(result.stdout, result.stderr)
            self.assert_no_sensitive_leak(compact.stdout, compact.stderr)
            combined = result.stdout + result.stderr + compact.stdout + compact.stderr
            self.assertNotIn("traceback", combined.lower())


if __name__ == "__main__":
    unittest.main()
