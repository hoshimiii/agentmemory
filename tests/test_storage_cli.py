from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
from unittest import mock

from agentmemory import schema
from agentmemory.identity import get_git_identity
from agentmemory.storage import (
    StorageConflictError,
    StorageError,
    CONTINUITY_PLACEHOLDER,
    MANIFEST_TEMPLATE,
    create_checkpoint,
    get_status,
    initialize_repository,
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
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(process.stderr.strip() or process.stdout.strip())
    return process


def _run_cli(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "agentmemory", *argv]
    command_env = os.environ.copy()
    existing = command_env.get("PYTHONPATH")
    if existing:
        command_env["PYTHONPATH"] = f"{SRC_ROOT}{os.pathsep}{existing}"
    else:
        command_env["PYTHONPATH"] = SRC_ROOT
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=command_env,
        check=False,
    )


def _make_git_repo(path: Path) -> Path:
    _run_git(["init", "--initial-branch=main"], cwd=path)
    _run_git(["config", "user.name", "agentmemory"], cwd=path)
    _run_git(["config", "user.email", "agentmemory@example"], cwd=path)
    _run_git(["commit", "--allow-empty", "-m", "init"], cwd=path)
    return path


def _checkpoint_path(repo: Path, record_id: str) -> Path:
    identity = get_git_identity(repo)
    return (
        repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "checkpoints" / f"{record_id}.json"
    )


class TestStorageCLI(unittest.TestCase):
    def test_init_creates_expected_scaffold_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            gitignore = repo / ".gitignore"
            gitignore.write_bytes(b"keep=1\r\n.continuity/local/\r\nnotes.md\r\n.continuity/local/\r\n")

            initialize_repository(repo)
            manifest = repo / ".continuity" / "manifest.json"
            continuity_md = repo / ".continuity" / "CONTINUITY.md"
            shared_records = repo / ".continuity" / "shared" / "records"
            local_lock = repo / ".continuity" / "local" / "locks" / "write.lock"

            self.assertTrue(manifest.exists())
            self.assertTrue(continuity_md.exists())
            self.assertTrue(shared_records.exists())
            self.assertTrue(local_lock.exists())
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), MANIFEST_TEMPLATE)
            self.assertEqual(continuity_md.read_text(encoding="utf-8"), CONTINUITY_PLACEHOLDER)
            self.assertEqual(
                gitignore.read_bytes(),
                b"keep=1\r\n.continuity/local/\r\nnotes.md\r\n",
            )
            self.assertEqual(gitignore.read_text(encoding="utf-8").count(".continuity/local/"), 1)

            before_manifest = manifest.read_bytes()
            before_gitignore = gitignore.read_bytes()
            initialize_repository(repo)
            self.assertEqual(manifest.read_bytes(), before_manifest)
            self.assertEqual(gitignore.read_bytes(), before_gitignore)

    def test_init_non_git_and_bare_fail_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            not_repo = Path(workdir) / "not_repo"
            not_repo.mkdir()
            with self.assertRaises(StorageError):
                initialize_repository(not_repo)
            self.assertFalse((not_repo / ".continuity").exists())

            bare = Path(workdir) / "bare.git"
            _run_git(["init", "--bare", "--initial-branch=main", str(bare)], cwd=Path(workdir))
            with self.assertRaises(StorageError):
                initialize_repository(bare)
            self.assertFalse((bare / ".continuity").exists())

    def test_incompatible_manifest_and_continuity_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            manifest = repo / ".continuity" / "manifest.json"
            continuity_md = repo / ".continuity" / "CONTINUITY.md"
            manifest.write_text(json.dumps({"bad": "manifest"}, sort_keys=True), encoding="utf-8")
            continuity_md.write_text("user marker", encoding="utf-8")

            with self.assertRaises(StorageError):
                initialize_repository(repo)
            self.assertEqual(manifest.read_text(encoding="utf-8").strip(), '{"bad": "manifest"}')
            self.assertEqual(continuity_md.read_text(encoding="utf-8"), "user marker")

    def test_symlinked_manifest_and_gitignore_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)

            outside_marker = Path(workdir) / "outside-marker"
            outside_marker.mkdir()
            outside_manifest = outside_marker / "manifest.json"
            outside_gitignore = outside_marker / ".gitignore"
            outside_manifest.write_bytes(b"outside manifest marker")
            outside_gitignore.write_bytes(b"outside gitignore marker")

            try:
                os.symlink(str(outside_gitignore), str(repo / ".gitignore"))
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable ({exc})")

            with self.assertRaises(StorageError):
                initialize_repository(repo)
            self.assertEqual(outside_gitignore.read_bytes(), b"outside gitignore marker")
            (repo / ".gitignore").unlink()

            initialize_repository(repo)
            try:
                repo_manifest = repo / ".continuity" / "manifest.json"
                repo_manifest.unlink()
                os.symlink(str(outside_manifest), str(repo / ".continuity" / "manifest.json"))
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable ({exc})")

            with self.assertRaises(StorageError):
                initialize_repository(repo)
            self.assertEqual(outside_manifest.read_bytes(), b"outside manifest marker")
            with self.assertRaises(StorageError):
                get_status(repo)

    def test_status_rejects_symlinked_checkpoint_and_target_files(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            create_checkpoint(
                repo,
                summary="status symlink",
                content={"value": 1},
                record_id="cp-status",
            )
            repo_root = repo / ".continuity" / "local" / "worktrees" / get_git_identity(repo)["worktree_id"] / "checkpoints"
            checkpoint = repo_root / "cp-status.json"
            checkpoint.unlink()
            symlink_target = Path(workdir) / "outside-record"
            symlink_target.write_text("{}", encoding="utf-8")
            try:
                os.symlink(str(symlink_target), str(checkpoint))
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable ({exc})")
            with self.assertRaises(StorageError):
                _ = get_status(repo)
            self.assertEqual(symlink_target.read_text(encoding="utf-8"), "{}")

    def test_special_file_rejection_in_init(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)

            special = repo / ".continuity"
            if hasattr(os, "mkfifo"):
                try:
                    os.mkfifo(str(special))
                except OSError as exc:
                    self.skipTest(f"special file creation unavailable ({exc})")
            else:
                self.skipTest("mkfifo unavailable")

            with self.assertRaises(StorageError):
                initialize_repository(repo)
            self.assertTrue(special.exists())
            special.unlink()

    def test_checkpoint_roundtrip_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                side_effect=["2020-01-01T00:00:01Z", "2020-01-01T00:00:05Z"],
            ):
                create_checkpoint(
                    repo,
                    summary="checkpoint summary",
                    content={"facts": {"value": 1}},
                    paths=["notes/main.md"],
                    record_id="cp-old",
                )
                create_checkpoint(
                    repo,
                    summary="checkpoint summary",
                    content={"facts": {"value": 2}},
                    paths=["notes/main.md"],
                    record_id="cp-new",
                )

            new_path = _checkpoint_path(repo, "cp-new")
            old_path = _checkpoint_path(repo, "cp-old")
            os.utime(new_path, (0, 0))
            os.utime(old_path, (1_000_000, 1_000_000))

            status = get_status(repo)
            self.assertTrue(status["initialized"])
            self.assertEqual(status["checkpoint_count"], 2)
            self.assertEqual(status["latest_checkpoint_id"], "cp-new")

            old_record = json.loads(old_path.read_text(encoding="utf-8"))
            schema.validate_record(old_record)
            new_record = json.loads(new_path.read_text(encoding="utf-8"))
            schema.validate_record(new_record)
            self.assertEqual(old_record["id"], "cp-old")
            self.assertEqual(new_record["id"], "cp-new")

    def test_status_rejects_malformed_checkpoint_record(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            create_checkpoint(repo, summary="checkpoint summary", content={"facts": {"value": 1}}, record_id="cp-bad")
            _checkpoint_path(repo, "cp-bad").write_text("{", encoding="utf-8")
            with self.assertRaises(StorageError):
                get_status(repo)

    def test_status_rejects_checkpoint_filename_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            create_checkpoint(repo, summary="checkpoint summary", content={"value": 1}, record_id="cp-record")
            checkpoint = _checkpoint_path(repo, "cp-record")
            checkpoint.rename(checkpoint.with_name("cp-renamed.json"))

            with self.assertRaises(StorageError):
                get_status(repo)

    def test_invalid_and_secret_json_rejected_before_checkpoint_writes(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            with mock.patch("agentmemory.storage._atomic_write_text") as atomic_write:
                with self.assertRaises(StorageError):
                    create_checkpoint(
                        repo,
                        summary="secrets",
                        content={"api_key": "sk-1234567890abcdefghijklmnop"},
                        record_id="cp-secret",
                    )
                atomic_write.assert_not_called()

            bad = _run_cli(
                [
                    "--repo",
                    str(repo),
                    "checkpoint",
                    "create",
                    "--summary",
                    "bad",
                    "--content-json",
                    '{"value":NaN}',
                ],
                repo,
            )
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(bad.stdout, "")
            self.assertNotIn("NaN", bad.stderr)

    def test_same_id_idempotence_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                side_effect=["2020-01-01T00:00:01Z", "2020-01-01T00:00:11Z"],
            ):
                first = create_checkpoint(repo, summary="same-id", content={"a": 1}, record_id="cp-id")
                second = create_checkpoint(repo, summary="same-id", content={"a": 1}, record_id="cp-id")
            self.assertEqual(first["id"], "cp-id")
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])

            with self.assertRaises(StorageConflictError):
                create_checkpoint(repo, summary="same-id", content={"a": 2}, record_id="cp-id")

            _checkpoint_path(repo, "cp-id").write_text("{", encoding="utf-8")
            with self.assertRaises(StorageConflictError):
                create_checkpoint(repo, summary="same-id", content={"a": 1}, record_id="cp-id")

    def test_create_with_whitespace_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            with self.assertRaises(StorageError):
                create_checkpoint(repo, summary="bad id", content={"a": 1}, record_id="  cp-id  ")

    def test_create_before_initialize_does_not_touch_repo(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)

            with self.assertRaises(StorageError):
                create_checkpoint(repo, summary="before-init", content={"value": 1}, record_id="cp-before")

            self.assertFalse((repo / ".continuity").exists())

    def test_init_os_replace_failure_preserves_state_and_no_tmp_files(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            manifest = repo / ".continuity" / "manifest.json"
            continuity = repo / ".continuity" / "CONTINUITY.md"
            gitignore = repo / ".gitignore"
            gitignore.write_bytes(b"keep=1\r\nnotes.md\r\n")
            before_manifest = manifest.read_bytes()
            before_continuity = continuity.read_bytes()
            before_gitignore = gitignore.read_bytes()

            with mock.patch("agentmemory.storage.os.replace", side_effect=OSError("injected")):
                with self.assertRaises(StorageError):
                    initialize_repository(repo)

            self.assertEqual(manifest.read_bytes(), before_manifest)
            self.assertEqual(continuity.read_bytes(), before_continuity)
            self.assertEqual(gitignore.read_bytes(), before_gitignore)
            self.assertEqual(list(repo.glob("**/*.tmp")), [])

    def test_concurrent_processes_or_workers_produce_valid_records(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)

            ids = [f"cp-{index:02d}" for index in range(6)]

            def _worker(record_id: str) -> subprocess.CompletedProcess[str]:
                return _run_cli(
                    [
                        "--repo",
                        str(repo),
                        "checkpoint",
                        "create",
                        "--summary",
                        "parallel",
                        "--content-json",
                        json.dumps({"worker": record_id}),
                        "--id",
                        record_id,
                    ],
                    repo,
                )

            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(_worker, ids))

            for result in results:
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertIn(payload["id"], ids)

            identity = get_git_identity(repo)
            checkpoint_dir = (
                repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "checkpoints"
            )
            for record_id in ids:
                path = checkpoint_dir / f"{record_id}.json"
                with self.subTest(record_id=record_id):
                    record = json.loads(path.read_text(encoding="utf-8"))
                    schema.validate_record(record)
                    self.assertEqual(path.stem, record["id"])

            self.assertEqual(len(list(checkpoint_dir.glob("*.json"))), 6)

            def _worker_shared(_index: int) -> subprocess.CompletedProcess[str]:
                return _run_cli(
                    [
                        "--repo",
                        str(repo),
                        "checkpoint",
                        "create",
                        "--summary",
                        "same-id",
                        "--content-json",
                        json.dumps({"worker": "shared"}),
                        "--id",
                        "cp-shared",
                    ],
                    repo,
                )

            with ThreadPoolExecutor(max_workers=4) as shared_executor:
                same_id_payloads = list(shared_executor.map(_worker_shared, range(3)))
            for result in same_id_payloads:
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["id"], "cp-shared")

            shared = _checkpoint_path(repo, "cp-shared")
            self.assertTrue(shared.exists())
            schema.validate_record(json.loads(shared.read_text(encoding="utf-8")))

    def test_worktree_isolation_and_shared_repository_identity(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            root = Path(workdir) / "root"
            root.mkdir()
            _make_git_repo(root)
            linked = Path(workdir) / "linked"
            _run_git(["worktree", "add", str(linked)], cwd=root)

            initialize_repository(root)
            initialize_repository(linked)

            root_identity = get_git_identity(root)
            linked_identity = get_git_identity(linked)
            self.assertEqual(root_identity["repository_id"], linked_identity["repository_id"])
            self.assertNotEqual(root_identity["worktree_id"], linked_identity["worktree_id"])

            create_checkpoint(root, summary="root", content={"scope": "root"}, record_id="cp-root")
            create_checkpoint(linked, summary="linked", content={"scope": "linked"}, record_id="cp-linked")

            self.assertTrue(_checkpoint_path(root, "cp-root").exists())
            self.assertTrue(_checkpoint_path(linked, "cp-linked").exists())
            self.assertNotEqual(
                _checkpoint_path(root, "cp-root").parent.resolve(),
                _checkpoint_path(linked, "cp-linked").parent.resolve(),
            )

    def test_checkpoint_creation_does_not_dirty_git_status_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)
            initialize_repository(repo)
            _run_git(["add", ".continuity/manifest.json", ".continuity/CONTINUITY.md", ".gitignore"], cwd=repo)
            _run_git(["commit", "-m", "init scaffold"], cwd=repo)

            create = _run_cli(
                [
                    "--repo",
                    str(repo),
                    "checkpoint",
                    "create",
                    "--summary",
                    "git-status",
                    "--content-json",
                    json.dumps({"value": 1}),
                ],
                repo,
            )
            self.assertEqual(create.returncode, 0)
            status = _run_git(["status", "--short"], cwd=repo)
            self.assertEqual(status.stdout.strip(), "")

    def test_cli_status_output_and_error_safety(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            repo = Path(workdir) / "repo"
            repo.mkdir()
            _make_git_repo(repo)

            status_missing = _run_cli(["--repo", str(repo), "status"], repo)
            self.assertEqual(status_missing.returncode, 0)
            self.assertFalse(json.loads(status_missing.stdout)["initialized"])

            initialize_repository(repo)
            create_result = _run_cli(
                [
                    "--repo",
                    str(repo),
                    "checkpoint",
                    "create",
                    "--summary",
                    "status",
                    "--content-json",
                    json.dumps({"value": 1}),
                    "--id",
                    "cp-status",
                ],
                repo,
            )
            self.assertEqual(create_result.returncode, 0)

            status = json.loads(_run_cli(["--repo", str(repo), "status"], repo).stdout)
            self.assertTrue(status["initialized"])
            self.assertEqual(status["latest_checkpoint_id"], "cp-status")
            self.assertNotIn(str(repo), create_result.stdout)

            bad = _run_cli(
                [
                    "--repo",
                    str(repo),
                    "checkpoint",
                    "create",
                    "--summary",
                    "bad",
                    "--content-json",
                    "[1, 2, 3]",
                ],
                repo,
            )
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(bad.stdout, "")
            self.assertNotIn(str(repo), bad.stderr)
            self.assertNotIn("Traceback", bad.stderr)

            parse_bad = _run_cli(
                [
                    "--repo",
                    str(repo),
                    "checkpoint",
                    "create",
                    "--summary",
                    "x",
                    "--content-json",
                    "{}",
                    "--unknown-flag",
                ],
                repo,
            )
            self.assertEqual(parse_bad.returncode, 2)
            self.assertEqual(parse_bad.stdout, "")
            self.assertEqual(parse_bad.stderr.strip(), "error: invalid arguments")
            self.assertNotIn(str(repo), parse_bad.stderr)


if __name__ == "__main__":
    unittest.main()
