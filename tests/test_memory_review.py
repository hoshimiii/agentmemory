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
from agentmemory import identity, render
from agentmemory.storage import (
    StorageConflictError,
    StorageError,
    CONTINUITY_PLACEHOLDER,
    create_candidate,
    get_status,
    initialize_repository,
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


class TestAgentMemoryReview(unittest.TestCase):
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
            stale = f"{render.CONTINUITY_GENERATED_HEADER}stale generated content\n"
            _continuity_path(repo).write_text(stale, encoding="utf-8")

            with mock.patch(
                "agentmemory.storage._timestamp_utc",
                return_value="2026-07-23T00:00:11Z",
            ):
                second = review_candidate(repo, "cand-review")
            self.assertFalse(second["created"])
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
