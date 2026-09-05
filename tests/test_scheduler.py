import json
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

from agentmemory.scheduler import (
    SchedulerValidationError,
    build_distillation_prompt,
    build_provider_argv,
    candidate_batch_schema,
    candidate_id_for,
    deduplicate_proposals,
    parse_cron,
    parse_provider_output,
    parse_strict_json,
    validate_candidate_batch,
    validate_scheduler_config,
)
from agentmemory.storage import (
    StorageError,
    create_candidate,
    disable_scheduler_config,
    enable_scheduler_config,
    initialize_repository,
    load_scheduler_config,
    write_scheduler_config,
)
from agentmemory.identity import get_git_identity
from agentmemory.schedule_runtime import ScheduleRuntimeError, configure_schedule, run_schedule, schedule_plan, schedule_status
from agentmemory.cli import run as cli_run


IDENTITY = {"repository_id": "a" * 64, "worktree_id": "b" * 64, "branch": "main", "head": "c" * 40}


def _config(provider="codex", **changes):
    value = {
        "schema_version": 1,
        "repository_id": IDENTITY["repository_id"],
        "worktree_id": IDENTITY["worktree_id"],
        "enabled": False,
        "provider": provider,
        "model": "gpt-5.6-terra",
        "cron": "0 3 * * *",
        "timezone": "local",
        "reasoning_effort": "medium" if provider == "codex" else None,
    }
    value.update(changes)
    return value


def _proposal(kind="decision", **changes):
    value = {
        "kind": kind,
        "summary": "verified fact",
        "semantic_role": "fact",
        "content": {"evidence": "test"},
        "paths": ["agentmemory/scheduler.py"],
        "experience": None,
    }
    if kind in ("strategy", "warning"):
        value["experience"] = {"applicability": {"task_types": ["bugfix"]}}
    value.update(changes)
    return value


def _wire_proposal(proposal=None, **changes):
    proposal = _proposal() if proposal is None else proposal
    value = {
        "kind": proposal["kind"],
        "summary": proposal["summary"],
        "semantic_role": proposal["semantic_role"],
        "content_json": json.dumps(proposal["content"]),
        "paths": proposal["paths"],
        "experience_json": json.dumps(proposal["experience"]),
    }
    value.update(changes)
    return value


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _repo(path):
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "Tests")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")


class SchedulerConfigTests(unittest.TestCase):
    def test_identity_bound_config_and_provider_rules(self):
        self.assertEqual(validate_scheduler_config(_config(), IDENTITY)["model"], "gpt-5.6-terra")
        self.assertEqual(validate_scheduler_config(_config("claude"), IDENTITY)["provider"], "claude")
        with self.assertRaises(SchedulerValidationError):
            validate_scheduler_config(_config(repository_id="0" * 64), IDENTITY)
        with self.assertRaises(SchedulerValidationError):
            validate_scheduler_config(_config(reasoning_effort=None), IDENTITY)
        with self.assertRaises(SchedulerValidationError):
            validate_scheduler_config(_config("gemini", reasoning_effort="low"), IDENTITY)
        with self.assertRaises(SchedulerValidationError):
            validate_scheduler_config(_config(model="--unsafe-option"), IDENTITY)
        with self.assertRaises(SchedulerValidationError):
            validate_scheduler_config({**_config(), "secret": "no"}, IDENTITY)

    def test_numeric_five_field_cron_only(self):
        self.assertEqual(parse_cron("*/5 0-23/2 1,15 1-12 0,7"), ("*/5", "0-23/2", "1,15", "1-12", "0,7"))
        self.assertEqual(parse_cron("59 23 31 12 7"), ("59", "23", "31", "12", "7"))
        for invalid in (
            "@daily", "0 0 0 * *", "0 0 * JAN *", "0 0 * * ?", "0 0 * * * *",
            "0\t0 * * *", "*/0 * * * *", "60 * * * *", "0 24 * * *", "0 0 0 * *",
            "0 0 * 13 *", "0 0 * * 8", "0  0 * * *", "0 0 * * *" + " " * 129,
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(SchedulerValidationError):
                    parse_cron(invalid)


class SchedulerProviderContractTests(unittest.TestCase):
    def test_argv_is_a_fixed_read_only_array(self):
        expected = {
            "codex": ("--sandbox", "read-only"),
            "claude": ("--permission-mode", "plan"),
            "gemini": ("--approval-mode", "plan"),
        }
        for provider, permission in expected.items():
            with self.subTest(provider=provider):
                argv = build_provider_argv(_config(provider))
                self.assertIsInstance(argv, list)
                self.assertEqual(tuple(argv[argv.index(permission[0]):argv.index(permission[0]) + 2]), permission)
                self.assertFalse(any(";" in part or "&&" in part for part in argv))

    def test_only_the_provider_contract_source_is_parsed(self):
        batch = {"summary": "ok", "proposals": [_wire_proposal()]}
        self.assertEqual(parse_provider_output("codex", json.dumps(batch))["summary"], "ok")
        self.assertEqual(
            parse_provider_output("claude", json.dumps({"result": "ignore", "structured_output": batch}))["summary"], "ok"
        )
        self.assertEqual(
            parse_provider_output("gemini", json.dumps({"response": json.dumps(batch)}))["summary"], "ok"
        )
        with self.assertRaises(SchedulerValidationError):
            parse_provider_output("claude", json.dumps({"result": json.dumps(batch)}))
        with self.assertRaises(SchedulerValidationError):
            parse_provider_output("gemini", json.dumps({"response": json.dumps(batch), "error": "no"}))

    def test_structured_output_wire_schema_and_decoding(self):
        schema = candidate_batch_schema()

        def objects(value):
            if isinstance(value, dict):
                yield value
                yield from (item for child in value.values() for item in objects(child))
            elif isinstance(value, list):
                yield from (item for child in value for item in objects(child))

        for value in objects(schema):
            self.assertFalse({"allOf", "if", "then", "else"} & set(value))
            if value.get("type") == "object":
                self.assertFalse(value.get("additionalProperties", True))
        proposal = _proposal("strategy")
        decoded = parse_provider_output("codex", json.dumps({"summary": "ok", "proposals": [_wire_proposal(proposal)]}))
        self.assertEqual(decoded["proposals"], [proposal])
        with self.assertRaises(SchedulerValidationError):
            parse_provider_output("codex", json.dumps({"summary": "ok", "proposals": [_wire_proposal(content_json="[]")]}))
        with self.assertRaises(SchedulerValidationError):
            parse_provider_output("codex", json.dumps({"summary": "ok", "proposals": [_wire_proposal(experience_json="{}")]}))


class SchedulerCandidateContractTests(unittest.TestCase):
    def test_strict_json_proposal_pairing_and_secret_rejection(self):
        with self.assertRaises(SchedulerValidationError):
            parse_strict_json('{"a":1,"a":2}')
        with self.assertRaises(SchedulerValidationError):
            parse_strict_json('{"a":NaN}')
        with self.assertRaises(SchedulerValidationError):
            validate_candidate_batch({"summary": "x", "proposals": [_proposal(experience={})]})
        with self.assertRaises(SchedulerValidationError):
            validate_candidate_batch({"summary": "x", "proposals": [_proposal(content={"token": "secret"})]})
        self.assertEqual(validate_candidate_batch({"summary": "nothing durable", "proposals": []})["proposals"], [])
        valid = validate_candidate_batch({"summary": "x", "proposals": [_proposal("strategy")]})
        self.assertEqual(valid["proposals"][0]["kind"], "strategy")

    def test_id_and_within_batch_deduplication_are_deterministic(self):
        first = _proposal(paths=["b.py", "a.py"])
        second = _proposal(paths=["a.py", "b.py"])
        self.assertEqual(candidate_id_for(IDENTITY, first), candidate_id_for(IDENTITY, second))
        other_branch = dict(IDENTITY, branch="feature")
        other_worktree = dict(IDENTITY, worktree_id="d" * 64)
        self.assertNotEqual(candidate_id_for(IDENTITY, first), candidate_id_for(other_branch, first))
        self.assertNotEqual(candidate_id_for(IDENTITY, first), candidate_id_for(other_worktree, first))
        accepted, duplicates = deduplicate_proposals(IDENTITY, [first, second])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(duplicates, [accepted[0]["id"]])

    def test_prompt_preserves_human_review_boundary(self):
        prompt = build_distillation_prompt().lower()
        for forbidden in ("edit", "network", "transcript", "plugin_data", "platform memory", "other projects", "review", "promote"):
            self.assertIn(forbidden, prompt)


class SchedulerStorageTests(unittest.TestCase):
    def _config_for(self, repo):
        identity = get_git_identity(repo)
        return _config(repository_id=identity["repository_id"], worktree_id=identity["worktree_id"])

    def test_missing_uninitialized_idempotent_enable_disable_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            config = self._config_for(repo)
            self.assertIsNone(load_scheduler_config(repo))
            with self.assertRaises(StorageError):
                write_scheduler_config(repo, config)
            initialize_repository(repo)
            first = write_scheduler_config(repo, config)
            second = write_scheduler_config(repo, config)
            self.assertEqual(first, second)
            self.assertFalse(load_scheduler_config(repo)["enabled"])
            self.assertTrue(enable_scheduler_config(repo)["enabled"])
            self.assertFalse(disable_scheduler_config(repo)["enabled"])
            self.assertEqual(disable_scheduler_config(repo)["enabled"], False)
            copied = dict(config)
            copied["worktree_id"] = "0" * 64
            with self.assertRaises(StorageError):
                write_scheduler_config(repo, copied)

    def test_expected_checkout_guard_creates_no_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            expected = get_git_identity(repo)
            _git(repo, "commit", "--allow-empty", "-m", "advance")
            with self.assertRaises(StorageError):
                create_candidate(
                    repo, "decision", "guarded", {"evidence": "x"},
                    record_id="cand-ai-guard", expected_identity=expected,
                )
            candidate_dir = repo / ".continuity" / "local" / "worktrees" / expected["worktree_id"] / "candidates"
            self.assertFalse(candidate_dir.exists())

    def test_scheduler_symlink_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            identity = get_git_identity(repo)
            config_path = repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "scheduler.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            outside = repo / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            try:
                config_path.symlink_to(outside)
            except OSError as exc:
                self.skipTest("symlink unavailable ({})".format(exc))
            with self.assertRaises(StorageError):
                load_scheduler_config(repo)
            self.assertTrue(create_candidate(
                repo, "decision", "scheduler path is isolated", {"evidence": "x"},
                record_id="cand-ai-scheduler-isolation",
            )["created"])


class SchedulerRuntimeTests(unittest.TestCase):
    def _cli(self, *argv):
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_run(argv)
        return code, json.loads(output.getvalue()) if output.getvalue() else None

    def test_cli_schedule_commands_and_plan_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            base = ("--repo", str(repo), "schedule")
            code, configured = self._cli(*base, "configure", "--provider", "codex", "--model", "gpt-5.6-terra", "--cron", "0 3 * * *")
            self.assertEqual(code, 0)
            self.assertFalse(configured["enabled"])
            code, status = self._cli(*base, "status")
            self.assertEqual(code, 0)
            self.assertFalse(status["enabled"])
            code, enabled = self._cli(*base, "enable")
            self.assertEqual(code, 0)
            self.assertTrue(enabled["enabled"])
            with mock.patch("agentmemory.schedule_runtime.shutil.which", return_value="C:/tools/codex.exe"):
                code, plan = self._cli(*base, "plan")
                self.assertEqual(code, 0)
                self.assertIsInstance(plan["argv"], list)
                code, dry = self._cli(*base, "run", "--dry-run")
                self.assertEqual(code, 0)
                self.assertEqual(dry, plan)
            code, disabled = self._cli(*base, "disable")
            self.assertEqual(code, 0)
            self.assertFalse(disabled["enabled"])

    def test_cross_provider_reasoning_effort_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            with self.assertRaises(ScheduleRuntimeError):
                configure_schedule(str(repo), provider="claude", model="claude-4", cron="0 3 * * *", reasoning_effort="high")

    def test_plan_and_mocked_run_only_create_local_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            configure_schedule(str(repo), provider="codex", model="gpt-5.6-terra", cron="0 3 * * *")
            with mock.patch("agentmemory.schedule_runtime.shutil.which", return_value="C:/tools/codex.exe"):
                plan = schedule_plan(str(repo))
                self.assertTrue(plan["runnable"])
                self.assertIsInstance(plan["argv"], list)
                rendered_plan = "\n".join(plan["argv"]).lower()
                for forbidden in ("analyze only", "review --candidate", "receipt", "shared/", "continuity.md", "secret-sentinel", ";", "&&"):
                    self.assertNotIn(forbidden, rendered_plan)
                self.assertFalse(schedule_status(str(repo))["enabled"])
                self.assertEqual(run_schedule(str(repo), dry_run=True), plan)
                from agentmemory import schedule_runtime
                with mock.patch.object(schedule_runtime, "_run_provider", return_value={"summary": "ok", "proposals": [_wire_proposal()]}):
                    with self.assertRaises(ScheduleRuntimeError):
                        run_schedule(str(repo))
                from agentmemory.storage import enable_scheduler_config
                enable_scheduler_config(repo)
                identity = get_git_identity(repo)
                worktree_local = repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"]

                def tree_snapshot(path):
                    if not path.exists():
                        return {}
                    return {
                        str(item.relative_to(path)).replace("\\", "/"): item.read_bytes()
                        for item in sorted(path.rglob("*")) if item.is_file()
                    }

                protected_before = {
                    "records": tree_snapshot(repo / ".continuity" / "shared" / "records"),
                    "experiences": tree_snapshot(repo / ".continuity" / "shared" / "experiences"),
                    "receipts": tree_snapshot(worktree_local / "receipts"),
                    "continuity": (repo / ".continuity" / "CONTINUITY.md").read_bytes(),
                    "git": _git(repo, "status", "--porcelain").stdout,
                }
                with mock.patch.object(schedule_runtime, "_run_provider", return_value={"summary": "ok", "proposals": [_wire_proposal()]}):
                    report = run_schedule(str(repo))
                protected_after = {
                    "records": tree_snapshot(repo / ".continuity" / "shared" / "records"),
                    "experiences": tree_snapshot(repo / ".continuity" / "shared" / "experiences"),
                    "receipts": tree_snapshot(worktree_local / "receipts"),
                    "continuity": (repo / ".continuity" / "CONTINUITY.md").read_bytes(),
                    "git": _git(repo, "status", "--porcelain").stdout,
                }
            self.assertEqual(report["status"], "completed")
            self.assertTrue(report["requires_human_review"])
            self.assertFalse(report["reviewed"])
            self.assertTrue(report["candidates"][0]["created"])
            self.assertEqual(protected_after, protected_before)
            self.assertEqual(list((repo / ".continuity" / "shared" / "records").iterdir()), [])
            identity = get_git_identity(repo)
            candidate_path = repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "candidates" / (report["candidates"][0]["id"] + ".json")
            self.assertEqual(json.loads(candidate_path.read_text(encoding="utf-8"))["provenance"]["source"], "scheduled-ai")

    def test_individual_rejection_duplicate_and_repeat_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            configure_schedule(str(repo), provider="codex", model="gpt-5.6-terra", cron="0 3 * * *", enabled=True)
            valid = _wire_proposal()
            malformed = _wire_proposal(content_json="{")
            invalid = _wire_proposal(_proposal(paths=["../escape"]))
            payload = {"summary": "ok", "proposals": [valid, malformed, invalid, valid, malformed]}
            from agentmemory import schedule_runtime
            with mock.patch("agentmemory.schedule_runtime.shutil.which", return_value="C:/tools/codex.exe"), \
                 mock.patch.object(schedule_runtime, "_run_provider", return_value=payload):
                first = run_schedule(str(repo))
                second = run_schedule(str(repo))
            self.assertEqual(first["rejected_count"], 3)
            self.assertEqual(first["rejections"], [{"proposal_index": 1, "category": "invalid_proposal"}, {"proposal_index": 2, "category": "invalid_proposal"}, {"proposal_index": 4, "category": "invalid_proposal"}])
            self.assertEqual(first["duplicate_count"], 1)
            self.assertTrue(second["candidates"][0]["idempotent"])

    def test_disable_between_plan_and_reload_prevents_provider_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            enabled = configure_schedule(
                str(repo), provider="codex", model="gpt-5.6-terra",
                cron="0 3 * * *", enabled=True,
            )
            disabled = dict(enabled, enabled=False)
            from agentmemory import schedule_runtime
            with mock.patch("agentmemory.schedule_runtime.shutil.which", return_value="C:/tools/codex.exe"), \
                 mock.patch.object(schedule_runtime, "load_scheduler_config", side_effect=[enabled, disabled]), \
                 mock.patch.object(schedule_runtime, "_run_provider") as provider:
                with self.assertRaises(ScheduleRuntimeError):
                    run_schedule(str(repo))
            provider.assert_not_called()

    def test_missing_executable_blocks_normal_run_but_not_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            configure_schedule(str(repo), provider="gemini", model="gemini-2.5", cron="0 3 * * *", enabled=True)
            with mock.patch("agentmemory.schedule_runtime.shutil.which", return_value=None):
                self.assertFalse(run_schedule(str(repo), dry_run=True)["runnable"])
                with self.assertRaises(ScheduleRuntimeError):
                    run_schedule(str(repo))

    def test_windows_provider_requires_native_executable(self):
        from agentmemory import schedule_runtime
        with mock.patch.object(schedule_runtime.os, "name", "nt"), \
             mock.patch.object(schedule_runtime.shutil, "which", return_value="C:/tools/codex.exe") as which:
            self.assertEqual(schedule_runtime._executable("codex"), str(Path("C:/tools/codex.exe").absolute()))
            which.assert_called_once_with("codex.exe")
        with mock.patch.object(schedule_runtime.os, "name", "nt"), \
             mock.patch.object(schedule_runtime.shutil, "which", return_value="C:/npm/codex.CMD") as which:
            self.assertIsNone(schedule_runtime._executable("codex"))
            which.assert_called_once_with("codex.exe")

    def test_six_proposals_and_checkout_change_write_no_candidates(self):
        for change_head in (False, True):
            with self.subTest(change_head=change_head), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory) / "repo"
                _repo(repo)
                initialize_repository(repo)
                configure_schedule(str(repo), provider="codex", model="gpt-5.6-terra", cron="0 3 * * *", enabled=True)
                payload = {"summary": "x", "proposals": [_proposal(summary=str(index)) for index in range(6)]}
                if change_head:
                    payload = {"summary": "x", "proposals": [_proposal()]}
                from agentmemory import schedule_runtime
                def provider(*_):
                    if change_head:
                        _git(repo, "commit", "--allow-empty", "-m", "change")
                    return payload
                with mock.patch("agentmemory.schedule_runtime.shutil.which", return_value="C:/tools/codex.exe"), \
                     mock.patch.object(schedule_runtime, "_run_provider", side_effect=provider):
                    with self.assertRaises(ScheduleRuntimeError):
                        run_schedule(str(repo))
                identity = get_git_identity(repo)
                candidates = repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "candidates"
                self.assertFalse(candidates.exists() and list(candidates.glob("*.json")))

    def test_bounded_reader_rejects_oversize_and_invalid_utf8(self):
        from agentmemory import schedule_runtime
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out"
            path.write_bytes(b"x" * (64 * 1024 + 1))
            with self.assertRaises(ScheduleRuntimeError):
                schedule_runtime._read_bounded(path)
            path.write_bytes(b"\xff")
            with self.assertRaises(ScheduleRuntimeError):
                schedule_runtime._read_bounded(path)

    def test_provider_process_nonzero_timeout_and_temp_cleanup(self):
        from agentmemory import schedule_runtime

        class FailedProcess:
            returncode = 7

            def poll(self):
                return self.returncode

        class HangingProcess:
            def __init__(self):
                self.returncode = None
                self.killed = False

            def poll(self):
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        for process in (FailedProcess(), HangingProcess()):
            captured = {}

            def popen(argv, **kwargs):
                captured["argv"] = argv
                captured["kwargs"] = kwargs
                return process

            patches = [
                mock.patch.object(schedule_runtime, "_executable", return_value="C:/tools/codex.exe"),
                mock.patch.object(schedule_runtime.subprocess, "Popen", side_effect=popen),
            ]
            if isinstance(process, HangingProcess):
                patches.append(mock.patch.object(schedule_runtime, "_TIMEOUT_SECONDS", 0))
            with self.subTest(process=type(process).__name__), patches[0], patches[1]:
                if len(patches) == 3:
                    patches[2].start()
                try:
                    with self.assertRaises(ScheduleRuntimeError):
                        schedule_runtime._run_provider(_config(), ".")
                finally:
                    if len(patches) == 3:
                        patches[2].stop()
            self.assertIsInstance(captured["argv"], list)
            self.assertFalse(captured["kwargs"]["shell"])
            self.assertIs(captured["kwargs"]["stdin"], subprocess.DEVNULL)
            self.assertIs(captured["kwargs"]["stderr"], subprocess.DEVNULL)
            temp_paths = [
                Path(captured["kwargs"]["stdout"].name),
                Path(captured["argv"][captured["argv"].index("--output-schema") + 1]),
                Path(captured["argv"][captured["argv"].index("--output-last-message") + 1]),
            ]
            self.assertFalse(any(path.exists() for path in temp_paths))
        self.assertTrue(process.killed)

    def test_cli_invalid_schedule_and_mocked_enabled_run(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cli_run(("--repo", str(repo), "schedule", "configure", "--provider", "codex", "--model", "gpt", "--cron", "@daily")), 1)
            self.assertEqual(stderr.getvalue().strip(), "error: operation failed")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cli_run(("--repo", str(repo), "schedule", "configure", "--provider", "claude", "--model", "claude-4", "--cron", "0 3 * * *", "--reasoning-effort", "high")), 1)
            self.assertEqual(stderr.getvalue().strip(), "error: operation failed")
            output = io.StringIO()
            expected = {"status": "completed", "requires_human_review": True}
            with redirect_stdout(output), mock.patch("agentmemory.cli.run_schedule", return_value=expected) as mocked:
                self.assertEqual(cli_run(("--repo", str(repo), "schedule", "run")), 0)
            mocked.assert_called_once_with(str(repo), dry_run=False)
            self.assertEqual(json.loads(output.getvalue()), expected)
            self.assertTrue(create_candidate(
                repo, "decision", "unrelated storage remains usable", {"evidence": "x"},
                record_id="cand-ai-unrelated",
            )["created"])
            identity = get_git_identity(repo)
            manual_path = repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "candidates" / "cand-ai-unrelated.json"
            self.assertEqual(json.loads(manual_path.read_text(encoding="utf-8"))["provenance"]["source"], "cli")

    def test_scheduler_config_rejects_oversized_file_before_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            _repo(repo)
            initialize_repository(repo)
            identity = get_git_identity(repo)
            config_path = repo / ".continuity" / "local" / "worktrees" / identity["worktree_id"] / "scheduler.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_bytes(b"{" + b" " * (64 * 1024))
            with self.assertRaises(StorageError):
                load_scheduler_config(repo)


if __name__ == "__main__":
    unittest.main()
