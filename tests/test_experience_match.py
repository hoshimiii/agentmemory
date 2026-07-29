import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentmemory.storage import create_candidate, initialize_repository, review_candidate


ROOT = Path(__file__).resolve().parents[1]


def _git(args, cwd):
    result = subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)


def _repo(path):
    path.mkdir()
    _git(["init", "--initial-branch=main"], path)
    _git(["config", "user.name", "agentmemory"], path)
    _git(["config", "user.email", "agentmemory@example"], path)
    _git(["commit", "--allow-empty", "-m", "init"], path)
    initialize_repository(path)
    return path


def _experience(*, strategy_id=None, task_types=None, signals=None):
    return {"applicability": {"task_types": task_types or ["bugfix"], "signals": signals or [], "error_patterns": []},
            "evidence": {"checks": []}, "lineage": {"supersedes": [], "deprecates": []},
            "relation": {"strategy_id": strategy_id}}


def _add(repo, record_id, kind, experience, paths=None, body=None):
    create_candidate(repo, kind=kind, summary=record_id, content={"body": body or f"body {record_id}"},
                     experience=experience, paths=paths, record_id=record_id)
    return review_candidate(repo, record_id)["id"]


def _cli(repo, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.run([sys.executable, "-m", "agentmemory", "--repo", str(repo), *args], cwd=str(repo),
                          text=True, capture_output=True, env=env, check=False)


def _continuity_snapshot(repo):
    root = repo / ".continuity"
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class TestExperienceMatch(unittest.TestCase):
    def test_match_orders_strategies_linked_warnings_then_standalone(self):
        with tempfile.TemporaryDirectory() as workdir:
            repo = _repo(Path(workdir) / "repo")
            strategy = _add(repo, "strategy-a", "strategy", _experience())
            warning = _add(repo, "warning-a", "warning", _experience(strategy_id=strategy))
            standalone = _add(repo, "warning-b", "warning", _experience())
            result = _cli(repo, "experience", "match", "--task-type", "bugfix")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual([item["id"] for item in payload["selected"]], [strategy, warning, standalone])
            self.assertEqual(payload["activated_relation_count"], 1)
            self.assertEqual(payload["byte_budget"], 10240)
            self.assertEqual(payload["byte_count"], len(result.stdout.encode("utf-8")))
            self.assertNotIn("integrity", result.stdout)

    def test_dimensions_are_anded_and_path_is_exact(self):
        with tempfile.TemporaryDirectory() as workdir:
            repo = _repo(Path(workdir) / "repo")
            record = _add(repo, "strategy-path", "strategy", _experience(task_types=["bugfix"], signals=["receipt"]), ["agentmemory/render.py"])
            result = _cli(repo, "experience", "match", "--task-type", "bugfix", "--signal", "other")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["selected_count"], 0)
            result = _cli(repo, "experience", "match", "--task-type", "bugfix", "--signal", "receipt")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["selected_count"], 0)
            result = _cli(repo, "experience", "match", "--task-type", "bugfix", "--signal", "receipt", "--path", "agentmemory/render.py")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["selected"][0]["id"], record)

    def test_cli_rejects_missing_experience_json_and_invalid_match_inputs(self):
        with tempfile.TemporaryDirectory() as workdir:
            repo = _repo(Path(workdir) / "repo")
            missing = _cli(repo, "candidate", "propose", "--kind", "strategy", "--summary", "x", "--content-json", '{"body":"x"}')
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(missing.stderr.strip(), "error: invalid experience-json")
            invalid = _cli(repo, "experience", "match", "--task-type", "bad tag")
            self.assertEqual(invalid.returncode, 1)
            self.assertEqual(invalid.stderr.strip(), "error: operation failed")
            empty = _cli(repo, "experience", "match")
            self.assertEqual(empty.returncode, 1)
            self.assertEqual(empty.stderr.strip(), "error: operation failed")

    def test_dynamic_budgets_and_user_maximum(self):
        with tempfile.TemporaryDirectory() as workdir:
            repo = _repo(Path(workdir) / "repo")
            strategy = _add(repo, "strategy", "strategy", _experience())
            zero = _cli(repo, "experience", "match", "--task-type", "bugfix")
            self.assertEqual(json.loads(zero.stdout)["byte_budget"], 8192)
            _add(repo, "warning-0", "warning", _experience(strategy_id=strategy))
            one = _cli(repo, "experience", "match", "--task-type", "bugfix")
            self.assertEqual(json.loads(one.stdout)["byte_budget"], 10240)
            for index in range(1, 8):
                _add(repo, f"warning-{index}", "warning", _experience(strategy_id=strategy))
            eight = _cli(repo, "experience", "match", "--task-type", "bugfix")
            self.assertEqual(json.loads(eight.stdout)["activated_relation_count"], 8)
            self.assertEqual(json.loads(eight.stdout)["byte_budget"], 24576)
            limited = _cli(repo, "experience", "match", "--task-type", "bugfix", "--max-bytes", "8192")
            self.assertEqual(json.loads(limited.stdout)["byte_budget"], 8192)

    def test_superseded_strategy_leaves_related_warning_nonactivatable(self):
        with tempfile.TemporaryDirectory() as workdir:
            repo = _repo(Path(workdir) / "repo")
            strategy = _add(repo, "strategy", "strategy", _experience())
            warning = _add(repo, "warning", "warning", _experience(strategy_id=strategy))
            successor = _add(repo, "successor", "strategy", {**_experience(), "lineage": {"supersedes": [strategy], "deprecates": []}})
            result = _cli(repo, "experience", "match", "--task-type", "bugfix")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual([record["id"] for record in payload["selected"]], [successor])
            self.assertNotIn(warning, result.stdout)
            self.assertEqual(payload["activated_relation_count"], 0)

    def test_match_is_deterministic_utf8_accounted_and_read_only(self):
        with tempfile.TemporaryDirectory() as workdir:
            repo = _repo(Path(workdir) / "repo")
            for index in range(5):
                _add(repo, f"strategy-{index}", "strategy", _experience(), body="中文经验" * 20)
            status_before = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), text=True, capture_output=True, check=False).stdout
            continuity_before = _continuity_snapshot(repo)
            first = _cli(repo, "experience", "match", "--task-type", "bugfix")
            second = _cli(repo, "experience", "match", "--task-type", "bugfix")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            payload = json.loads(first.stdout)
            self.assertEqual(payload["selected_count"], 4)
            self.assertEqual(payload["omitted_count"], 1)
            self.assertEqual(payload["byte_count"], len(first.stdout.encode("utf-8")))
            self.assertIn("中文经验", first.stdout)
            self.assertEqual(_continuity_snapshot(repo), continuity_before)
            self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), text=True, capture_output=True, check=False).stdout, status_before)

            secret = "sk-12345678901234567890"
            rejected = _cli(repo, "experience", "match", "--task-type", secret)
            self.assertEqual(rejected.returncode, 1)
            self.assertNotIn(secret, rejected.stdout + rejected.stderr)


if __name__ == "__main__":
    unittest.main()
