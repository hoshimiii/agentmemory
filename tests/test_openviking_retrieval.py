from __future__ import annotations

import hashlib
import io
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentmemory.openviking import OpenVikingError, retrieve_project_knowledge
from agentmemory.cli import run
from agentmemory.identity import get_git_identity


REPOSITORY_ID = "a" * 64
PROJECT_URI = "viking://resources/projects/repo-" + REPOSITORY_ID


def _envelope(result: Dict[str, Any]) -> str:
    return json.dumps({"ok": True, "result": result}, separators=(",", ":"))


def _completed(result: Dict[str, Any], prefix: str = "") -> subprocess.CompletedProcess[str]:
    output = (prefix + "\n" if prefix else "") + _envelope(result)
    return subprocess.CompletedProcess(["ov.exe"], 0, output, "")


class TestOpenVikingRetrieval(unittest.TestCase):
    def _identity(self, repo: Path) -> Dict[str, str]:
        return {"repository_id": REPOSITORY_ID, "toplevel": str(repo)}

    def _config(self, root: Path) -> str:
        path = root / "ovcli.conf"
        path.write_text('{"url":"http://127.0.0.1:19330"}', encoding="utf-8")
        return str(path)

    def _responses(self, uri: str) -> List[subprocess.CompletedProcess[str]]:
        return [
            _completed({"healthy": True}),
            _completed(
                {
                    "memories": [],
                    "skills": [],
                    "resources": [
                        {
                            "uri": uri,
                            "context_type": "resource",
                            "level": 2,
                            "abstract": "verified note",
                            "overview": "short overview",
                        }
                    ],
                    "total": 1,
                },
                'cmd: ov find --uri=project -n 3 "query"',
            ),
            _completed({"modTime": "2026-07-28T00:00:00Z", "isDir": False}),
        ]

    def test_git_identity_preserves_non_ascii_repository_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir) / "中文仓库"
            repo.mkdir()
            initialized = subprocess.run(
                ["git", "init", "--initial-branch=main"],
                cwd=str(repo),
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            identity = get_git_identity(repo)
            self.assertEqual(Path(identity["toplevel"]), repo.resolve())

    def test_happy_path_is_scoped_read_only_and_returns_current_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir) / "repo"
            repo.mkdir()
            source = repo / "docs" / "note.md"
            source.parent.mkdir()
            source.write_text("local source", encoding="utf-8")
            uri = PROJECT_URI + "/docs/note.md"
            calls: List[List[str]] = []
            config = self._config(Path(tempdir))

            def run(command: List[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                self.assertFalse(kwargs["shell"])
                self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
                self.assertEqual(kwargs["encoding"], "utf-8")
                self.assertEqual(kwargs["cwd"], str(Path(config).parent))
                self.assertEqual(kwargs["env"]["OPENVIKING_CLI_CONFIG_FILE"], config)
                return self._responses(uri)[len(calls) - 1]

            with mock.patch("agentmemory.openviking.get_git_identity", return_value=self._identity(repo)), mock.patch(
                "agentmemory.openviking.subprocess.run", side_effect=run
            ):
                result = retrieve_project_knowledge(
                    repo,
                    "find source",
                    "C:/OpenViking/ov.exe",
                    config,
                )

            self.assertTrue(result["read_only"])
            self.assertTrue(result["untrusted"])
            self.assertEqual(result["repository_id"], REPOSITORY_ID)
            self.assertEqual(result["project_uri"], PROJECT_URI)
            item = result["results"][0]
            self.assertEqual(item["uri"], uri)
            self.assertEqual(item["server_mod_time"], "2026-07-28T00:00:00Z")
            self.assertEqual(item["current_local_evidence"]["path"], "docs/note.md")
            self.assertEqual(item["current_local_evidence"]["hash_kind"], "current_local_file_sha256")
            self.assertEqual(item["current_local_evidence"]["sha256"], hashlib.sha256(b"local source").hexdigest())
            self.assertEqual(calls[0][1:], ["health", "-o", "json"])
            self.assertEqual(
                calls[1][1:],
                [
                    "find",
                    "find source",
                    "--uri",
                    PROJECT_URI,
                    "--limit",
                    "3",
                    "--level",
                    "2",
                    "--context-type",
                    "resource",
                    "-o",
                    "json",
                    "--compact",
                    "true",
                ],
            )
            self.assertEqual(calls[2][1:], ["stat", uri, "-o", "json"])
            self.assertNotIn("read", [part for call in calls for part in call])
            self.assertFalse((repo / ".continuity").exists())

    def test_rejects_cross_domain_memory_skill_and_unsafe_source_results(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir) / "repo"
            repo.mkdir()
            (repo / "note.md").write_text("safe", encoding="utf-8")
            config = self._config(Path(tempdir))
            cases = [
                {"memories": [{"uri": "viking://memories/x"}], "skills": [], "resources": []},
                {"memories": [], "skills": [{"uri": "viking://skills/x"}], "resources": []},
                {
                    "memories": [],
                    "skills": [],
                    "resources": [
                        {
                            "uri": "viking://resources/notes/note.md",
                            "context_type": "resource",
                            "level": 2,
                        }
                    ],
                },
                {
                    "memories": [],
                    "skills": [],
                    "resources": [
                        {
                            "uri": PROJECT_URI + "/%252e%252e/outside.txt",
                            "context_type": "resource",
                            "level": 2,
                        }
                    ],
                },
            ]
            for found in cases:
                with self.subTest(found=found):
                    with mock.patch("agentmemory.openviking.get_git_identity", return_value=self._identity(repo)), mock.patch(
                        "agentmemory.openviking.subprocess.run",
                        side_effect=[_completed({"healthy": True}), _completed(found)],
                    ):
                        with self.assertRaisesRegex(OpenVikingError, "^openviking retrieval failed$"):
                            retrieve_project_knowledge(repo, "safe", "C:/OpenViking/ov.exe", config)

    def test_rejects_bad_process_json_bounds_and_secret_content(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir) / "repo"
            repo.mkdir()
            (repo / "note.md").write_text("safe", encoding="utf-8")
            config = self._config(Path(tempdir))
            failures: List[Any] = [
                subprocess.TimeoutExpired(["ov.exe"], 1),
                subprocess.CompletedProcess(["ov.exe"], 1, "", "details"),
                subprocess.CompletedProcess(["ov.exe"], 0, '{"ok":true,"ok":true,"result":{}}', ""),
                subprocess.CompletedProcess(["ov.exe"], 0, '{"ok":true,"result":NaN}', ""),
                subprocess.CompletedProcess(["ov.exe"], 0, "x" * (256 * 1024 + 1), ""),
            ]
            for failure in failures:
                with self.subTest(failure=type(failure).__name__):
                    with mock.patch("agentmemory.openviking.get_git_identity", return_value=self._identity(repo)), mock.patch(
                        "agentmemory.openviking.subprocess.run", side_effect=failure
                    ):
                        with self.assertRaisesRegex(OpenVikingError, "^openviking retrieval failed$"):
                            retrieve_project_knowledge(repo, "safe", "C:/OpenViking/ov.exe", config)

            secret_uri = PROJECT_URI + "/note.md"
            secret_found = {
                "memories": [],
                "skills": [],
                "resources": [
                    {
                        "uri": secret_uri,
                        "context_type": "resource",
                        "level": 2,
                        "abstract": "Bearer abcdefghijklmnopqrstuvwxyz123456",
                    }
                ],
            }
            with mock.patch("agentmemory.openviking.get_git_identity", return_value=self._identity(repo)), mock.patch(
                "agentmemory.openviking.subprocess.run",
                side_effect=[
                    _completed({"healthy": True}),
                    _completed(secret_found),
                    _completed({"modTime": "2026-07-28T00:00:00Z", "isDir": False}),
                ],
            ):
                with self.assertRaisesRegex(OpenVikingError, "^openviking retrieval failed$"):
                    retrieve_project_knowledge(repo, "safe", "C:/OpenViking/ov.exe", config)

    def test_rejects_invalid_limits_missing_files_symlinks_and_wrapper_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir) / "repo"
            repo.mkdir()
            identity = self._identity(repo)
            config = self._config(Path(tempdir))
            for limit in (0, 6, True):
                with self.subTest(limit=limit), self.assertRaises(OpenVikingError):
                    retrieve_project_knowledge(
                        repo,
                        "safe",
                        "C:/OpenViking/ov.exe",
                        config,
                        limit=limit,
                    )
            for wrapper in ("ov.cmd", "ov.bat", "ov.ps1"):
                with self.subTest(wrapper=wrapper), self.assertRaises(OpenVikingError):
                    retrieve_project_knowledge(
                        repo,
                        "safe",
                        str(Path(tempdir) / wrapper),
                        config,
                    )

            uri = PROJECT_URI + "/missing.md"
            with mock.patch("agentmemory.openviking.get_git_identity", return_value=identity), mock.patch(
                "agentmemory.openviking.subprocess.run", side_effect=self._responses(uri)
            ):
                with self.assertRaises(OpenVikingError):
                    retrieve_project_knowledge(repo, "safe", "C:/OpenViking/ov.exe", config)

            target = Path(tempdir) / "target.md"
            target.write_text("outside", encoding="utf-8")
            try:
                os.symlink(str(target), str(repo / "linked.md"))
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable ({exc})")
            linked_uri = PROJECT_URI + "/linked.md"
            with mock.patch("agentmemory.openviking.get_git_identity", return_value=identity), mock.patch(
                "agentmemory.openviking.subprocess.run", side_effect=self._responses(linked_uri)
            ):
                with self.assertRaises(OpenVikingError):
                    retrieve_project_knowledge(repo, "safe", "C:/OpenViking/ov.exe", config)

            race = repo / "race.md"
            race.write_text("inside", encoding="utf-8")
            race_uri = PROJECT_URI + "/race.md"
            real_lstat = type(race).lstat
            linked_stat = (repo / "linked.md").lstat()
            race_lstat_calls = 0

            def report_post_open_swap(path: Path) -> os.stat_result:
                nonlocal race_lstat_calls
                if path == race:
                    race_lstat_calls += 1
                    if race_lstat_calls == 3:
                        return linked_stat
                return real_lstat(path)

            with mock.patch("agentmemory.openviking.get_git_identity", return_value=identity), mock.patch(
                "agentmemory.openviking.subprocess.run", side_effect=self._responses(race_uri)
            ), mock.patch.object(type(race), "lstat", autospec=True, side_effect=report_post_open_swap):
                with self.assertRaises(OpenVikingError):
                    retrieve_project_knowledge(repo, "safe", "C:/OpenViking/ov.exe", config)

            nested = repo / "nested"
            nested.mkdir()
            nested_source = nested / "note.md"
            nested_source.write_text("inside", encoding="utf-8")
            nested_uri = PROJECT_URI + "/nested/note.md"
            real_lstat = type(nested).lstat
            nested_lstat_calls = 0

            def report_parent_swap(path: Path) -> os.stat_result:
                nonlocal nested_lstat_calls
                if path == nested:
                    nested_lstat_calls += 1
                    if nested_lstat_calls == 2:
                        return linked_stat
                return real_lstat(path)

            with mock.patch("agentmemory.openviking.get_git_identity", return_value=identity), mock.patch(
                "agentmemory.openviking.subprocess.run", side_effect=self._responses(nested_uri)
            ), mock.patch.object(type(nested), "lstat", autospec=True, side_effect=report_parent_swap):
                with self.assertRaises(OpenVikingError):
                    retrieve_project_knowledge(repo, "safe", "C:/OpenViking/ov.exe", config)

    def test_limits_results_and_has_no_stateful_or_forbidden_imports(self) -> None:
        self.assertTrue(inspect.getsource(retrieve_project_knowledge))
        source = ROOT / "agentmemory" / "openviking.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn(".storage", text)
        self.assertNotIn(".render", text)
        self.assertNotIn(".hooks", text)
        self.assertNotIn('"read"', text)

    def test_cli_forwards_retrieve_arguments_and_returns_compact_json(self) -> None:
        expected = {"read_only": True, "untrusted": True, "results": []}
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("agentmemory.cli.retrieve_project_knowledge", return_value=expected) as retrieve, redirect_stdout(
            stdout
        ), redirect_stderr(stderr):
            status = run(
                [
                    "--repo",
                    "C:/repo",
                    "retrieve",
                    "--query",
                    "find source",
                    "--openviking-cli",
                    "C:/OpenViking/ov.exe",
                    "--openviking-config",
                    "C:/OpenViking/ovcli.conf",
                    "--limit",
                    "5",
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(stdout.getvalue(), json.dumps(expected, separators=(",", ":")))
        self.assertEqual(stderr.getvalue(), "")
        retrieve.assert_called_once_with(
            "C:/repo",
            "find source",
            "C:/OpenViking/ov.exe",
            "C:/OpenViking/ovcli.conf",
            limit=5,
        )

    def test_cli_retrieve_fails_closed_for_adapter_error_and_invalid_limit(self) -> None:
        sentinel = "do-not-leak"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch(
            "agentmemory.cli.retrieve_project_knowledge", side_effect=OpenVikingError(sentinel)
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            status = run(
                [
                    "--repo",
                    "C:/repo",
                    "retrieve",
                    "--query",
                    "query",
                    "--openviking-cli",
                    "C:/OpenViking/ov.exe",
                    "--openviking-config",
                    "C:/OpenViking/ovcli.conf",
                ]
            )
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "error: operation failed\n")
        self.assertNotIn(sentinel, stderr.getvalue())

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("agentmemory.cli.retrieve_project_knowledge") as retrieve, redirect_stdout(
            stdout
        ), redirect_stderr(stderr):
            status = run(
                [
                    "--repo",
                    "C:/repo",
                    "retrieve",
                    "--query",
                    "query",
                    "--openviking-cli",
                    "C:/OpenViking/ov.exe",
                    "--openviking-config",
                    "C:/OpenViking/ovcli.conf",
                    "--limit",
                    "0",
                ]
            )
        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "error: invalid arguments\n")
        retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
