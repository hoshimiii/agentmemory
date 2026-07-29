from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock

from agentmemory import schema
from agentmemory import identity, render, storage
from agentmemory.storage import (
    StorageConflictError,
    StorageError,
    CONTINUITY_PLACEHOLDER,
    create_candidate,
    create_checkpoint,
    get_status,
    initialize_repository,
    load_resume_state,
    review_candidate,
    render_continuity,
)


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = str(ROOT)


def _run_git(
    args: list[str],
    cwd: Path,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    process = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=command_env,
        text=True,
        check=False,
        capture_output=True,
    )
    if process.returncode != 0:
        raise AssertionError(process.stderr.strip() or process.stdout.strip())
    return process


def _run_cli(
    argv: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "agentmemory", *argv]
    command_env = os.environ.copy()
    if "PYTHONPATH" in command_env:
        command_env["PYTHONPATH"] = f"{SRC_ROOT}{os.pathsep}{command_env['PYTHONPATH']}"
    else:
        command_env["PYTHONPATH"] = SRC_ROOT
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=command_env,
        text=True,
        capture_output=True,
        check=False,
    )


def _make_git_repo(path: Path) -> Path:
    _run_git(["init", "--initial-branch=main"], cwd=path)
    _run_git(["config", "user.name", "agentmemory"], cwd=path)
    _run_git(["config", "user.email", "agentmemory@example"], cwd=path)
    _run_git(["commit", "--allow-empty", "-m", "init"], cwd=path)
    return path


def _candidate_path(repo: Path, candidate_id: str) -> Path:
    git_identity = identity.get_git_identity(repo)
    return (
        repo
        / ".continuity"
        / "local"
        / "worktrees"
        / git_identity["worktree_id"]
        / "candidates"
        / f"{candidate_id}.json"
    )


def _project_records(repo: Path) -> list[Path]:
    return sorted((repo / ".continuity" / "shared" / "records").glob("*.json"))


def _receipt_path(repo: Path, record_id: str) -> Path:
    git_identity = identity.get_git_identity(repo)
    return (
        repo
        / ".continuity"
        / "local"
        / "worktrees"
        / git_identity["worktree_id"]
        / "receipts"
        / f"{record_id}.json"
    )


def _experience_path(repo: Path, record_id: str) -> Path:
    return repo / ".continuity" / "shared" / "experiences" / f"{record_id}.json"


def _write_experience_receipt(repo: Path, record: Dict[str, Any]) -> None:
    payload = {
        "schema_version": 1,
        "repository_id": identity.get_git_identity(repo)["repository_id"],
        "worktree_id": identity.get_git_identity(repo)["worktree_id"],
        "record_id": record["id"],
        "content_hash": record["integrity"]["content_hash"],
    }
    path = _receipt_path(repo, record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schema.canonical_json_dumps(payload), encoding="utf-8")


def _continuity_path(repo: Path) -> Path:
    return repo / ".continuity" / "CONTINUITY.md"


def _extract_continuity_record_ids(text: str) -> list[str]:
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    records = [json.loads(block) for block in blocks]
    return [record["id"] for record in records]


def _project_id_for_candidate(repo: Path, candidate_id: str) -> str:
    for path in _project_records(repo):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("record_type") == "project_record" and payload.get("provenance", {}).get("source_record_id") == candidate_id:
            return payload["id"]
    raise AssertionError("project record not found")


def _experience(*, supersedes: Optional[list[str]] = None, deprecates: Optional[list[str]] = None, strategy_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "applicability": {"task_types": ["bugfix"], "signals": [], "error_patterns": []},
        "evidence": {"checks": []},
        "lineage": {"supersedes": supersedes or [], "deprecates": deprecates or []},
        "relation": {"strategy_id": strategy_id},
    }


class TestAgentMemoryReview(unittest.TestCase):
    def test_v2_experience_review_sidecar_and_receipt_gated_loading(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            before = _continuity_path(repo).read_bytes()
            create_candidate(repo, "strategy", "receipt repair", {"body": "verify receipt first"},
                             record_id="cand-exp", experience=_experience())
            reviewed = review_candidate(repo, "cand-exp")
            sidecar = repo / ".continuity" / "shared" / "experiences" / f"{reviewed['id']}.json"
            self.assertTrue(sidecar.exists())
            self.assertEqual(_continuity_path(repo).read_bytes(), before)
            loaded = storage.load_trusted_experiences(repo)
            self.assertEqual([(item["id"], item["lifecycle"]) for item in loaded], [(reviewed["id"], "active")])
            sidecar_bytes = sidecar.read_bytes()
            receipt_bytes = _receipt_path(repo, reviewed["id"]).read_bytes()
            self.assertFalse(review_candidate(repo, "cand-exp")["created"])
            self.assertEqual(sidecar.read_bytes(), sidecar_bytes)
            self.assertEqual(_receipt_path(repo, reviewed["id"]).read_bytes(), receipt_bytes)
            _receipt_path(repo, reviewed["id"]).unlink()
            self.assertEqual(storage.load_trusted_experiences(repo), [])

    def test_v2_lifecycle_is_derived_and_predecessor_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(repo, "strategy", "old", {"body": "old"}, record_id="cand-old", experience=_experience())
            old = review_candidate(repo, "cand-old")["id"]
            old_path = repo / ".continuity" / "shared" / "experiences" / f"{old}.json"
            old_bytes = old_path.read_bytes()
            create_candidate(repo, "strategy", "new", {"body": "new"}, record_id="cand-new", experience=_experience(supersedes=[old]))
            new = review_candidate(repo, "cand-new")["id"]
            states = {item["id"]: item["lifecycle"] for item in storage.load_trusted_experiences(repo)}
            self.assertEqual(states, {old: "superseded", new: "active"})
            self.assertEqual(old_path.read_bytes(), old_bytes)

    def test_v2_rejects_untrusted_lineage_target_and_v1_resume_rejects_misplaced_v2(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(repo, "strategy", "base", {"body": "base"}, record_id="cand-base", experience=_experience())
            base = review_candidate(repo, "cand-base")["id"]
            _receipt_path(repo, base).unlink()
            create_candidate(repo, "strategy", "next", {"body": "next"}, record_id="cand-next", experience=_experience(supersedes=[base]))
            with self.assertRaises(StorageError):
                review_candidate(repo, "cand-next")
            source = repo / ".continuity" / "shared" / "experiences" / f"{base}.json"
            misplaced = repo / ".continuity" / "shared" / "records" / f"{base}.json"
            misplaced.write_bytes(source.read_bytes())
            create_checkpoint(repo, "checkpoint", {"value": 1}, record_id="cp-v2")
            with self.assertRaises(StorageError):
                load_resume_state(repo)

    def test_v2_deprecation_precedence_and_duplicate_transition_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(repo, "strategy", "base", {"body": "base"}, record_id="cand-base", experience=_experience())
            base = review_candidate(repo, "cand-base")["id"]
            create_candidate(repo, "strategy", "next", {"body": "next"}, record_id="cand-next", experience=_experience(supersedes=[base]))
            review_candidate(repo, "cand-next")
            create_candidate(repo, "strategy", "duplicate", {"body": "duplicate"}, record_id="cand-duplicate", experience=_experience(supersedes=[base]))
            with self.assertRaises(StorageError):
                review_candidate(repo, "cand-duplicate")
            create_candidate(repo, "strategy", "deprecated", {"body": "deprecated"}, record_id="cand-deprecated", experience=_experience(deprecates=[base]))
            review_candidate(repo, "cand-deprecated")
            states = {record["id"]: record["lifecycle"] for record in storage.load_trusted_experiences(repo)}
            self.assertEqual(states[base], "deprecated")

    def test_v2_projection_overflow_is_rejected_before_candidate_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            strategy_id = "cand-near-strategy"
            strategy_direct = {"id": strategy_id, "kind": "strategy", "summary": "near limit", "body": "", "activation": "direct", "related_from": None}
            strategy_body = "x" * (schema.MAX_EXPERIENCE_PROJECTION_BYTES - len(schema.canonical_json_dumps(strategy_direct).encode("utf-8")))
            with self.assertRaises(StorageError):
                create_candidate(repo, "strategy", "near limit", {"body": strategy_body}, record_id=strategy_id, experience=_experience())
            self.assertFalse(_candidate_path(repo, strategy_id).exists())

            warning_id = "cand-near-warning"
            final_direct = {"id": "f" * 64, "kind": "warning", "summary": "near limit", "body": "", "activation": "direct", "related_from": None}
            warning_body = "x" * (schema.MAX_EXPERIENCE_PROJECTION_BYTES - len(schema.canonical_json_dumps(final_direct).encode("utf-8")))
            self.assertTrue(create_candidate(repo, "warning", "near limit", {"body": warning_body}, record_id=warning_id, experience=_experience())["created"])
            self.assertTrue(_candidate_path(repo, warning_id).exists())

            related_id = "cand-near-related-warning"
            with self.assertRaises(StorageError):
                create_candidate(repo, "warning", "near limit", {"body": warning_body}, record_id=related_id, experience=_experience(strategy_id="strategy-id"))
            self.assertFalse(_candidate_path(repo, related_id).exists())

    def test_v2_load_rejects_warning_relation_to_non_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(repo, "strategy", "strategy", {"body": "strategy"}, record_id="cand-strategy", experience=_experience())
            strategy = review_candidate(repo, "cand-strategy")["id"]
            create_candidate(repo, "warning", "target", {"body": "target"}, record_id="cand-target", experience=_experience())
            target = review_candidate(repo, "cand-target")["id"]
            create_candidate(repo, "warning", "attached", {"body": "attached"}, record_id="cand-attached", experience=_experience(strategy_id=strategy))
            attached = review_candidate(repo, "cand-attached")["id"]
            record = json.loads(_experience_path(repo, attached).read_text(encoding="utf-8"))
            record["experience"]["relation"]["strategy_id"] = target
            record = schema.annotate_with_integrity(record)
            _experience_path(repo, attached).write_text(schema.canonical_json_dumps(record), encoding="utf-8")
            _write_experience_receipt(repo, record)
            with self.assertRaises(StorageError):
                storage.load_trusted_experiences(repo)

    def test_v2_review_rejects_untrusted_precreated_sidecar_and_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(repo, "warning", "untrusted", {"body": "untrusted"}, record_id="cand-untrusted", experience=_experience(strategy_id="unknown-strategy"))
            candidate = json.loads(_candidate_path(repo, "cand-untrusted").read_text(encoding="utf-8"))
            project_id = storage._compute_project_record_id(candidate)
            precreated = storage._build_experience_project_record(candidate=candidate, project_id=project_id, timestamp="2026-07-29T00:00:00Z")
            _experience_path(repo, project_id).parent.mkdir(parents=True, exist_ok=True)
            _experience_path(repo, project_id).write_text(schema.canonical_json_dumps(precreated), encoding="utf-8")
            with self.assertRaises(StorageError):
                review_candidate(repo, "cand-untrusted")
            self.assertFalse(_receipt_path(repo, project_id).exists())

            create_candidate(repo, "strategy", "old", {"body": "old"}, record_id="cand-old", experience=_experience())
            old = review_candidate(repo, "cand-old")["id"]
            create_candidate(repo, "strategy", "next", {"body": "next"}, record_id="cand-next", experience=_experience(supersedes=[old]))
            next_id = review_candidate(repo, "cand-next")["id"]
            old_record = json.loads(_experience_path(repo, old).read_text(encoding="utf-8"))
            old_record["experience"]["lineage"]["supersedes"] = [next_id]
            old_record = schema.annotate_with_integrity(old_record)
            _experience_path(repo, old).write_text(schema.canonical_json_dumps(old_record), encoding="utf-8")
            _write_experience_receipt(repo, old_record)
            with self.assertRaises(StorageError):
                storage.load_trusted_experiences(repo)

    def test_v2_receipt_sidecar_timestamp_and_fanout_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(repo, "strategy", "base", {"body": "base"}, record_id="cand-base", experience=_experience())
            base = review_candidate(repo, "cand-base")["id"]
            for index in range(8):
                candidate_id = f"cand-warning-{index}"
                create_candidate(repo, "warning", candidate_id, {"body": candidate_id}, record_id=candidate_id, experience=_experience(strategy_id=base))
                review_candidate(repo, candidate_id)
            self.assertEqual(sum(record["kind"] == "warning" for record in storage.load_trusted_experiences(repo)), 8)

            create_candidate(repo, "warning", "overflow", {"body": "overflow"}, record_id="cand-overflow", experience=_experience(strategy_id=base))
            with self.assertRaises(StorageConflictError):
                review_candidate(repo, "cand-overflow")
            overflow_candidate = json.loads(_candidate_path(repo, "cand-overflow").read_text(encoding="utf-8"))
            overflow_id = storage._compute_project_record_id(overflow_candidate)
            self.assertFalse(_receipt_path(repo, overflow_id).exists())
            overflow = storage._build_experience_project_record(candidate=overflow_candidate, project_id=overflow_id, timestamp="2026-07-29T00:00:00Z")
            _experience_path(repo, overflow_id).write_text(schema.canonical_json_dumps(overflow), encoding="utf-8")
            _write_experience_receipt(repo, overflow)
            with self.assertRaises(StorageError):
                storage.load_trusted_experiences(repo)

            _experience_path(repo, overflow_id).unlink()
            _receipt_path(repo, overflow_id).unlink()
            base_record = json.loads(_experience_path(repo, base).read_text(encoding="utf-8"))
            bad_receipt = json.loads(_receipt_path(repo, base).read_text(encoding="utf-8"))
            bad_receipt["content_hash"] = "sha256:" + "0" * 64
            _receipt_path(repo, base).write_text(schema.canonical_json_dumps(bad_receipt), encoding="utf-8")
            with self.assertRaises(StorageError):
                storage.load_trusted_experiences(repo)
            _write_experience_receipt(repo, base_record)
            warning_path = _experience_path(repo, storage._compute_project_record_id(json.loads(_candidate_path(repo, "cand-warning-0").read_text(encoding="utf-8"))))
            warning_bytes = warning_path.read_bytes()
            warning_path.write_text("{", encoding="utf-8")
            with self.assertRaises(StorageError):
                storage.load_trusted_experiences(repo)
            warning_path.write_bytes(warning_bytes)
            base_record["created_at"] = "2026-07-28T00:00:00Z"
            base_record = schema.annotate_with_integrity(base_record)
            _experience_path(repo, base).write_text(schema.canonical_json_dumps(base_record), encoding="utf-8")
            _write_experience_receipt(repo, base_record)
            with self.assertRaises(StorageError):
                storage.load_trusted_experiences(repo)

    def test_v2_detached_and_cross_project_visibility_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(repo, "strategy", "main", {"body": "main"}, record_id="cand-main", experience=_experience())
            main = review_candidate(repo, "cand-main")["id"]
            head = _run_git(["rev-parse", "HEAD"], repo).stdout.strip()
            _run_git(["checkout", "--detach", head], repo)
            self.assertEqual(storage.load_trusted_experiences(repo), [])
            _run_git(["checkout", "main"], repo)
            self.assertEqual(storage.load_trusted_experiences(repo)[0]["id"], main)

            other = Path(workdir) / "other"
            other.mkdir()
            _make_git_repo(other)
            initialize_repository(other)
            create_candidate(other, "strategy", "other", {"body": "other"}, record_id="cand-other", experience=_experience())
            other_id = review_candidate(other, "cand-other")["id"]
            _experience_path(repo, other_id).write_bytes(_experience_path(other, other_id).read_bytes())
            with self.assertRaises(StorageError):
                storage.load_trusted_experiences(repo)
    def test_candidate_path_schema_and_scaffold_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            payload = create_candidate(
                repo,
                kind="decision",
                summary="proposal",
                content={"value": 1},
                paths=["notes/main.md"],
                record_id="cand-review-path",
            )
            candidate = _candidate_path(repo, payload["id"])

            self.assertTrue(candidate.exists())
            self.assertTrue(payload["created"])
            schema.validate_record(json.loads(candidate.read_text(encoding="utf-8")))
            self.assertEqual(
                candidate.parent.as_posix(),
                (repo / ".continuity" / "local" / "worktrees" / identity.get_git_identity(repo)["worktree_id"] / "candidates").as_posix(),
            )
            self.assertEqual(_project_records(repo), [])
            self.assertEqual(_continuity_path(repo).read_text(encoding="utf-8"), CONTINUITY_PLACEHOLDER)
            _run_git(["add", ".gitignore", ".continuity/manifest.json", ".continuity/CONTINUITY.md"], repo)
            _run_git(["commit", "-m", "initialize continuity"], repo)
            self.assertEqual(_run_git(["status", "--short"], repo).stdout, "")

            ignored = create_candidate(
                repo,
                kind="decision",
                summary="ignored proposal",
                content={"value": 2},
                record_id="cand-ignored",
            )
            self.assertTrue(ignored["created"])
            self.assertEqual(_run_git(["status", "--short"], repo).stdout, "")

    def test_secret_and_invalid_candidate_inputs_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            candidate_file = _candidate_path(repo, "cand-stable")

            with mock.patch("agentmemory.storage._atomic_write_text") as write_hook:
                with self.assertRaises(StorageError):
                    create_candidate(
                        repo,
                        kind="decision",
                        summary="secret",
                        content={"api_key": "sk-12345678901234567890"},
                        record_id="cand-secret",
                    )
                write_hook.assert_not_called()

            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                side_effect=["2026-07-23T00:00:01Z", "2026-07-23T00:00:02Z"],
            ):
                first = create_candidate(
                    repo,
                    kind="decision",
                    summary="stable",
                    content={"value": 1},
                    record_id="cand-stable",
                )
                second = create_candidate(
                    repo,
                    kind="decision",
                    summary="stable",
                    content={"value": 1},
                    record_id="cand-stable",
                )
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])

            with self.assertRaises(StorageConflictError):
                create_candidate(
                    repo,
                    kind="decision",
                    summary="stable",
                    content={"value": 2},
                    record_id="cand-stable",
                )

            candidate_file.write_text("{", encoding="utf-8")
            with self.assertRaises(StorageConflictError):
                create_candidate(
                    repo,
                    kind="decision",
                    summary="stable",
                    content={"value": 1},
                    record_id="cand-stable",
                )

    def test_review_missing_confirm_prevents_writes(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            create_candidate(
                repo,
                kind="incident",
                summary="incident",
                content={"value": 1},
                record_id="cand-review",
            )
            candidate_file = _candidate_path(repo, "cand-review")
            before = candidate_file.read_bytes()
            continuity_before = _continuity_path(repo).read_bytes()

            result = _run_cli(
                ["--repo", str(repo), "review", "--candidate", "cand-review"],
                repo,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr.strip(), "error: invalid arguments")
            self.assertEqual(candidate_file.read_bytes(), before)
            self.assertEqual(_continuity_path(repo).read_bytes(), continuity_before)
            self.assertEqual(_project_records(repo), [])

    def test_re_review_preserves_project_and_repairs_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            create_candidate(
                repo,
                kind="constraint",
                summary="constraints",
                content={"value": 1},
                record_id="cand-review",
            )
            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                return_value="2026-07-23T00:00:10Z",
            ):
                first = review_candidate(repo, "cand-review")
            self.assertTrue(first["created"])

            project_path = _project_records(repo)[0]
            project_bytes = project_path.read_bytes()
            receipt_path = _receipt_path(repo, first["id"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            project = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual(
                receipt,
                {
                    "schema_version": 1,
                    "repository_id": identity.get_git_identity(repo)["repository_id"],
                    "worktree_id": identity.get_git_identity(repo)["worktree_id"],
                    "record_id": first["id"],
                    "content_hash": project["integrity"]["content_hash"],
                },
            )
            self.assertNotIn("content", receipt)
            receipt_path.unlink()
            stale = f"{render.CONTINUITY_GENERATED_HEADER}stale generated content\n"
            _continuity_path(repo).write_text(stale, encoding="utf-8")

            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                return_value="2026-07-23T00:00:11Z",
            ):
                second = review_candidate(repo, "cand-review")
            self.assertFalse(second["created"])
            self.assertTrue(receipt_path.exists())
            self.assertEqual(project_path.read_bytes(), project_bytes)
            self.assertNotEqual(_continuity_path(repo).read_text(encoding="utf-8"), stale)
            project = json.loads(project_path.read_text(encoding="utf-8"))
            schema.validate_record(project)
            self.assertEqual(project["id"], first["id"])
            self.assertEqual(project["provenance"]["source"], "explicit-review")
            self.assertEqual(project["review"]["confirmed_by"], "explicit_user")
            self.assertEqual(project["created_at"], "2026-07-23T00:00:10Z")
            self.assertEqual(project["review"]["confirmed_at"], "2026-07-23T00:00:10Z")
            self.assertEqual(project["applies_to"]["branch"], "main")

    def test_review_receipt_is_worktree_local(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(
                repo,
                kind="decision",
                summary="local trust",
                content={"value": 1},
                record_id="cand-local",
            )
            result = review_candidate(repo, "cand-local")
            self.assertTrue(_receipt_path(repo, result["id"]).exists())

            _run_git(["add", ".gitignore", ".continuity"], cwd=repo)
            _run_git(["commit", "-m", "track reviewed memory"], cwd=repo)
            linked = Path(workdir) / "linked"
            _run_git(["worktree", "add", "-b", "linked", str(linked)], cwd=repo)
            try:
                self.assertFalse(_receipt_path(linked, result["id"]).exists())
            finally:
                _run_git(["worktree", "remove", "--force", str(linked)], cwd=repo)

    def test_review_requires_candidate_checkout_identity(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            create_candidate(
                repo,
                kind="decision",
                summary="stale head",
                content={"value": 1},
                record_id="cand-stale-head",
            )
            _run_git(["commit", "--allow-empty", "-m", "advance head"], cwd=repo)
            with self.assertRaises(StorageError):
                review_candidate(repo, "cand-stale-head")
            self.assertEqual(_project_records(repo), [])
            self.assertFalse(_receipt_path(repo, "placeholder").parent.exists())

            create_candidate(
                repo,
                kind="decision",
                summary="branch change",
                content={"value": 2},
                record_id="cand-branch",
            )
            _run_git(["checkout", "-b", "other"], cwd=repo)
            with self.assertRaises(StorageError):
                review_candidate(repo, "cand-branch")
            self.assertEqual(_project_records(repo), [])
            self.assertFalse(_receipt_path(repo, "placeholder").parent.exists())

            _run_git(["checkout", "main"], cwd=repo)
            reviewed = review_candidate(repo, "cand-branch")
            self.assertTrue(reviewed["created"])
            self.assertTrue(_receipt_path(repo, reviewed["id"]).exists())

            _run_git(["checkout", "--detach", "HEAD"], cwd=repo)
            create_candidate(
                repo,
                kind="incident",
                summary="detached head",
                content={"value": 3},
                record_id="cand-detached",
            )
            _run_git(["commit", "--allow-empty", "-m", "advance detached head"], cwd=repo)
            with self.assertRaises(StorageError):
                review_candidate(repo, "cand-detached")
            self.assertEqual(len(_project_records(repo)), 1)
            self.assertFalse(_receipt_path(repo, "placeholder").exists())

    def test_review_publishes_receipt_before_new_project_record(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_checkpoint(repo, "checkpoint", {"value": 1}, record_id="cp-main")
            create_candidate(
                repo,
                kind="decision",
                summary="publish order",
                content={"value": 1},
                record_id="cand-publish-order",
            )
            original_write = storage._atomic_write_text

            def fail_receipt(path: Path, text: str) -> None:
                if path.parent.name == "receipts":
                    raise OSError("simulated receipt failure")
                original_write(path, text)

            with mock.patch("agentmemory.storage._atomic_write_text", side_effect=fail_receipt):
                with self.assertRaises(StorageError):
                    review_candidate(repo, "cand-publish-order")
            self.assertEqual(_project_records(repo), [])

            shared_records = repo / ".continuity" / "shared" / "records"

            def fail_project(path: Path, text: str) -> None:
                if path.parent == shared_records:
                    raise OSError("simulated project failure")
                original_write(path, text)

            with mock.patch("agentmemory.storage._atomic_write_text", side_effect=fail_project):
                with self.assertRaises(StorageError):
                    review_candidate(repo, "cand-publish-order")
            self.assertEqual(_project_records(repo), [])
            self.assertEqual(
                len(list((repo / ".continuity" / "local").rglob("receipts/*.json"))),
                1,
            )
            self.assertEqual(load_resume_state(repo)["project_records"], [])

    def test_render_empty_order_branch_and_detached_filter(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            result = render_continuity(repo)
            continuity_path = _continuity_path(repo)
            continuity_path.unlink()
            self.assertFalse(continuity_path.exists())
            result = render_continuity(repo)
            continuity_text = _continuity_path(repo).read_text(encoding="utf-8")
            self.assertEqual(result["count"], 0)
            self.assertTrue(continuity_text.startswith(render.CONTINUITY_GENERATED_HEADER))
            self.assertIn(f"{render.CONTINUITY_BRANCH_PREFIX}main\n", continuity_text)
            self.assertIn(render.CONTINUITY_EMPTY_STATE_TEXT, continuity_text)

            create_candidate(
                repo,
                kind="decision",
                summary="secret marker",
                content={"value": 0},
                record_id="cand-secret",
            )
            corrupted_candidate = _candidate_path(repo, "cand-secret")
            corrupted_candidate.write_text(json.dumps({"secret": "sk-very-secret"}), encoding="utf-8")

            render_continuity(repo)
            continuity_text = _continuity_path(repo).read_text(encoding="utf-8")
            self.assertNotIn("sk-very-secret", continuity_text)

            create_candidate(
                repo,
                kind="decision",
                summary="a",
                content={"value": 1},
                record_id="cand-main-a",
            )
            create_candidate(
                repo,
                kind="decision",
                summary="b",
                content={"value": 2},
                record_id="cand-main-b",
            )
            review_candidate(repo, "cand-main-a")
            review_candidate(repo, "cand-main-b")
            render_continuity(repo)
            ids = _extract_continuity_record_ids(_continuity_path(repo).read_text(encoding="utf-8"))
            self.assertEqual(ids, sorted(ids))

            head = _run_git(["rev-parse", "HEAD"], repo).stdout.strip()
            detached = Path(workdir) / "linked"
            _run_git(["worktree", "add", "--detach", str(detached), head], cwd=repo)
            _run_git(["checkout", "--detach", head], cwd=repo)
            create_candidate(
                repo,
                kind="incident",
                summary="detached",
                content={"value": 3},
                record_id="cand-det",
            )
            review_candidate(repo, "cand-det")
            render_continuity(repo)
            detached_ids = _extract_continuity_record_ids(_continuity_path(repo).read_text(encoding="utf-8"))
            self.assertEqual(detached_ids, [_project_id_for_candidate(repo, "cand-det")])

            detached_project_id = _project_id_for_candidate(repo, "cand-det")
            detached_project = next(
                path for path in _project_records(repo) if path.name == f"{detached_project_id}.json"
            )
            detached_payload = json.loads(detached_project.read_text(encoding="utf-8"))
            detached_payload["applies_to"]["head"] = "0" * 40
            detached_payload = schema.annotate_with_integrity(detached_payload, version=1)
            detached_project.write_text(
                json.dumps(detached_payload, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
            render_continuity(repo)
            detached_ids = _extract_continuity_record_ids(_continuity_path(repo).read_text(encoding="utf-8"))
            self.assertEqual(detached_ids, [])

            _run_git(["checkout", "main"], cwd=repo)
            render_continuity(repo)
            main_ids = _extract_continuity_record_ids(_continuity_path(repo).read_text(encoding="utf-8"))
            self.assertEqual(main_ids, sorted([_project_id_for_candidate(repo, "cand-main-a"), _project_id_for_candidate(repo, "cand-main-b")]))

    def test_render_fails_closed_on_bad_shared_entries(self) -> None:
        scenarios = [
            "non-json",
            "extension",
            "symlink",
            "special",
            "wrong-type",
            "unconfirmed",
            "cross-repo",
            "filename-mismatch",
        ]

        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as workdir:
                    repo = Path(workdir) / "repo"
                    repo.mkdir()
                    _make_git_repo(repo)
                    initialize_repository(repo)
                    create_candidate(
                        repo,
                        kind="decision",
                        summary="summary",
                        content={"value": 1},
                        record_id="cand-shared",
                    )
                    review_candidate(repo, "cand-shared")

                    shared = repo / ".continuity" / "shared" / "records"
                    continuity = _continuity_path(repo)
                    before = f"{render.CONTINUITY_GENERATED_HEADER}stale generated content\n"
                    continuity.write_text(before, encoding="utf-8")

                    if scenario == "non-json":
                        (shared / "broken.json").write_text("{", encoding="utf-8")
                    elif scenario == "extension":
                        (shared / "notes.txt").write_text("{}", encoding="utf-8")
                    elif scenario == "symlink":
                        outside = repo / "outside-target.json"
                        outside.write_text("{}", encoding="utf-8")
                        link = shared / "outside.json"
                        try:
                            os.symlink(str(outside), str(link))
                        except OSError as exc:
                            self.skipTest(f"symlink unavailable ({exc})")
                    elif scenario == "special":
                        if not hasattr(os, "mkfifo"):
                            self.skipTest("mkfifo unavailable")
                        special = shared / "special"
                        try:
                            os.mkfifo(str(special))
                        except OSError as exc:
                            self.skipTest(f"special unavailable ({exc})")
                    elif scenario == "wrong-type":
                        create_candidate(
                            repo,
                            kind="decision",
                            summary="wrong type",
                            content={"value": 2},
                            record_id="cand-wrong-type",
                        )
                        payload = json.loads(_candidate_path(repo, "cand-wrong-type").read_text(encoding="utf-8"))
                        payload["applies_to"]["branch"] = "DETACHED"
                        payload = schema.annotate_with_integrity(payload, version=1)
                        schema.validate_record(payload)
                        (shared / f"{payload['id']}.json").write_text(
                            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                            encoding="utf-8",
                        )
                    elif scenario == "unconfirmed":
                        project = _project_records(repo)[0]
                        payload: Dict[str, Any] = json.loads(project.read_text(encoding="utf-8"))
                        payload["review"]["confirmed"] = False
                        payload["review"]["confirmed_by"] = None
                        payload["review"]["confirmed_at"] = None
                        payload = schema.annotate_with_integrity(payload, version=1)
                        project.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
                    elif scenario == "cross-repo":
                        project = _project_records(repo)[0]
                        payload = json.loads(project.read_text(encoding="utf-8"))
                        payload["applies_to"]["repository_id"] = "f" * 64
                        payload["applies_to"]["branch"] = "DETACHED"
                        payload = schema.annotate_with_integrity(payload, version=1)
                        schema.validate_record(payload)
                        project.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
                    elif scenario == "filename-mismatch":
                        original = _project_records(repo)[0]
                        payload = json.loads(original.read_text(encoding="utf-8"))
                        original.unlink()
                        (shared / "renamed.json").write_text(
                            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                            encoding="utf-8",
                        )

                    result = _run_cli(["--repo", str(repo), "render"], repo)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(continuity.read_text(encoding="utf-8"), before)

    def test_arbitrary_continuity_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            arbitrary = "# User-owned continuity\n\nKeep this text.\n"
            continuity = _continuity_path(repo)
            continuity.write_text(arbitrary, encoding="utf-8")

            result = _run_cli(["--repo", str(repo), "render"], repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(continuity.read_text(encoding="utf-8"), arbitrary)

    def test_review_candidate_invalid_files_do_not_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            root = Path(workdir) / "root"
            root.mkdir()
            _make_git_repo(root)
            initialize_repository(root)

            create_candidate(
                root,
                kind="decision",
                summary="base",
                content={"value": 1},
                record_id="cand-bad",
            )
            candidate = _candidate_path(root, "cand-bad")
            before = candidate.read_bytes()

            candidate.write_text("{", encoding="utf-8")
            corrupt = candidate.read_bytes()
            with self.assertRaises(StorageError):
                review_candidate(root, "cand-bad")
            self.assertEqual(candidate.read_bytes(), corrupt)

            candidate.write_text(before.decode("utf-8"), encoding="utf-8")
            linked = Path(workdir) / "linked"
            _run_git(["worktree", "add", str(linked), "HEAD"], cwd=root)
            initialize_repository(linked)
            candidate_linked = _candidate_path(linked, "cand-bad")
            if not candidate_linked.exists():
                create_candidate(
                    linked,
                    kind="decision",
                    summary="linked",
                    content={"value": 1},
                    record_id="cand-bad",
                )
            candidate.write_bytes(candidate_linked.read_bytes())
            with self.assertRaises(StorageError):
                review_candidate(root, "cand-bad")

            outside = root / "outside-candidate.json"
            outside.write_text(candidate_linked.read_text(encoding="utf-8"), encoding="utf-8")
            candidate.unlink()
            try:
                os.symlink(str(outside), str(candidate))
            except OSError as exc:
                self.skipTest(f"symlink unavailable ({exc})")
            with self.assertRaises(StorageError):
                review_candidate(root, "cand-bad")

            self.assertEqual(_project_records(root), [])

    def test_concurrent_same_candidate_review(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            create_candidate(
                repo,
                kind="decision",
                summary="parallel",
                content={"value": 1},
                record_id="cand-parallel",
            )

            def _review(_: int) -> str:
                result = _run_cli(
                    [
                        "--repo",
                        str(repo),
                        "review",
                        "--candidate",
                        "cand-parallel",
                        "--confirm",
                    ],
                    repo,
                )
                self.assertEqual(result.returncode, 0)
                payload = json.loads(result.stdout)
                return payload["id"]

            with ThreadPoolExecutor(max_workers=5) as executor:
                project_ids = list(executor.map(_review, range(5)))
            self.assertEqual(len(set(project_ids)), 1)
            self.assertEqual(len(_project_records(repo)), 1)

    def test_generated_continuity_compatible_with_init_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            create_candidate(
                repo,
                kind="constraint",
                summary="compat",
                content={"value": 1},
                record_id="cand-compat",
            )
            review_candidate(repo, "cand-compat")
            self.assertTrue(_continuity_path(repo).read_text(encoding="utf-8").startswith(render.CONTINUITY_GENERATED_HEADER))
            self.assertTrue(get_status(repo)["initialized"])
            self.assertTrue(initialize_repository(repo)["initialized"])

    def test_cli_error_output_is_opaque(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            parse_error = _run_cli(
                ["--repo", str(repo), "candidate", "propose", "--kind", "decision", "--summary", "x", "--content-json", "{"],
                repo,
            )
            self.assertEqual(parse_error.returncode, 2)
            self.assertEqual(parse_error.stdout, "")
            self.assertEqual(parse_error.stderr.strip(), "error: invalid content-json")

            sentinel = "sk-12345678901234567890token"
            secret_error = _run_cli(
                [
                    "--repo",
                    str(repo),
                    "candidate",
                    "propose",
                    "--kind",
                    "decision",
                    "--summary",
                    "sensitive",
                    "--content-json",
                    json.dumps({"secret": sentinel}),
                ],
                repo,
            )
            self.assertEqual(secret_error.returncode, 1)
            self.assertEqual(secret_error.stdout, "")
            self.assertNotIn("secret", secret_error.stderr.lower())
            self.assertNotIn(sentinel, secret_error.stderr)
            self.assertNotIn(str(repo), secret_error.stderr)


if __name__ == "__main__":
    unittest.main()
