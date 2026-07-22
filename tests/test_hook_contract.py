import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
DISPATCHER = ROOT / "hooks" / "agentmemory_hook.py"

EXPECTED_FALLBACK_OUTPUT = '{"continue":true}'
EXPECTED_PRECOMPACT_OUTPUT = '{"continue":true}'
ERROR_OUTPUT = "agentmemory hook input rejected."
SENSITIVE_FIELDS = {
    "cwd": "C:\\Users\\agent\\agentmemory-secret-cwd",
    "transcript_path": "C:\\Users\\agent\\transcripts\\agentmemory_secret_session.jsonl",
    "source": "source://agentmemory/sensitive-token-7f4",
    "session_id": "session-secret-2026-07-23",
}


def payload_with_sensitives(path: Path | str) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload.update(SENSITIVE_FIELDS)
    return json.dumps(payload)


def snapshot_file_states(directory: Path) -> dict[str, str]:
    root = Path(directory)
    states: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        if path.is_file():
            states[rel] = f"file:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        else:
            states[rel] = "dir"
    return states


def run_dispatcher(
    action: str,
    payload: str,
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(DISPATCHER), action]
    execution_env = os.environ.copy()
    if env:
        execution_env.update(env)
    return subprocess.run(
        command,
        input=payload,
        text=True,
        capture_output=True,
        env=execution_env,
        cwd=str(cwd) if cwd is not None else None,
    )


class TestAgentMemoryHookContract(unittest.TestCase):
    def assert_no_sensitive_leak(
        self,
        stdout: str,
        stderr: str,
    ) -> None:
        for key, value in SENSITIVE_FIELDS.items():
            self.assertNotIn(key, stdout)
            self.assertNotIn(key, stderr)
            self.assertNotIn(value, stdout)
            self.assertNotIn(value, stderr)

    def test_session_startup_and_compact_matchers_are_supported(self) -> None:
        hooks_config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        session_cfg = hooks_config["hooks"]["SessionStart"][0]
        compact_cfg = hooks_config["hooks"]["PreCompact"][0]
        session_hook = session_cfg["hooks"][0]
        compact_hook = compact_cfg["hooks"][0]

        self.assertEqual(session_cfg["matcher"], "startup|resume|compact")
        self.assertEqual(compact_cfg["matcher"], "manual|auto")
        self.assertEqual(session_hook["type"], "command")
        self.assertEqual(compact_hook["type"], "command")
        self.assertEqual(
            session_hook["command"],
            'python3 "$PLUGIN_ROOT/hooks/agentmemory_hook.py" session-start',
        )
        self.assertEqual(
            session_hook["commandWindows"],
            'py -3 "$env:PLUGIN_ROOT\\hooks\\agentmemory_hook.py" session-start',
        )
        self.assertEqual(
            compact_hook["command"],
            'python3 "$PLUGIN_ROOT/hooks/agentmemory_hook.py" pre-compact',
        )
        self.assertEqual(
            compact_hook["commandWindows"],
            'py -3 "$env:PLUGIN_ROOT\\hooks\\agentmemory_hook.py" pre-compact',
        )
        self.assertEqual(session_hook["timeout"], 5)
        self.assertEqual(compact_hook["timeout"], 5)

    def test_session_startup_fixture_returns_expected_output(self) -> None:
        payload = payload_with_sensitives(FIXTURES_DIR / "session-startup.json")
        result = run_dispatcher("session-start", payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, EXPECTED_FALLBACK_OUTPUT)
        self.assertEqual(result.stderr, "")
        self.assert_no_sensitive_leak(result.stdout, result.stderr)

    def test_session_compact_fixture_returns_expected_output(self) -> None:
        payload = payload_with_sensitives(FIXTURES_DIR / "session-compact.json")
        result = run_dispatcher("session-start", payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, EXPECTED_FALLBACK_OUTPUT)
        self.assertEqual(result.stderr, "")
        self.assert_no_sensitive_leak(result.stdout, result.stderr)

    def test_precompact_fixture_returns_expected_output(self) -> None:
        payload = payload_with_sensitives(FIXTURES_DIR / "precompact-auto.json")
        result = run_dispatcher("pre-compact", payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, EXPECTED_PRECOMPACT_OUTPUT)
        self.assertEqual(result.stderr, "")
        self.assert_no_sensitive_leak(result.stdout, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertTrue(parsed["continue"])

    def test_non_standard_json_constants_are_rejected(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            payload = f'{{"hook_event_name":"SessionStart","value":{constant}}}'
            result = run_dispatcher("session-start", payload)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr.strip(), ERROR_OUTPUT)
            self.assertNotIn(constant, result.stderr)

    def test_invalid_json_is_rejected(self) -> None:
        result = run_dispatcher("session-start", "{invalid}")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), ERROR_OUTPUT)

    def test_non_object_payload_is_rejected(self) -> None:
        result = run_dispatcher("session-start", "[1, 2, 3]")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), ERROR_OUTPUT)

    def test_unknown_action_is_rejected(self) -> None:
        payload = (FIXTURES_DIR / "session-startup.json").read_text(encoding="utf-8")
        result = run_dispatcher("unsupported-action", payload)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), ERROR_OUTPUT)

    def test_event_mismatch_is_rejected(self) -> None:
        payload = (FIXTURES_DIR / "session-startup.json").read_text(encoding="utf-8")
        result = run_dispatcher("pre-compact", payload)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), ERROR_OUTPUT)

        precompact_payload = (
            (FIXTURES_DIR / "precompact-auto.json")
            .read_text(encoding="utf-8")
        )
        result = run_dispatcher("session-start", precompact_payload)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), ERROR_OUTPUT)

    def test_stdin_json_parseability_no_input_leakage(self) -> None:
        payload = payload_with_sensitives(FIXTURES_DIR / "session-startup.json")
        result = run_dispatcher("session-start", payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("unknown_field", result.stdout)
        self.assertNotIn("notes", result.stdout)
        self.assert_no_sensitive_leak(result.stdout, result.stderr)

        invalid = run_dispatcher("session-start", "{\"hook_event_name\":")
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stderr.strip(), ERROR_OUTPUT)
        self.assertEqual(invalid.stdout, "")
        self.assertEqual(invalid.stderr, ERROR_OUTPUT)
        self.assertNotIn("SessionStart", invalid.stderr)

    def test_temp_cwd_and_plugin_data_set_has_no_file_changes(self) -> None:
        payload = payload_with_sensitives(FIXTURES_DIR / "session-startup.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = Path(tmpdir) / "marker.txt"
            marker.write_text("keep", encoding="utf-8")

            before = snapshot_file_states(Path(tmpdir))

            result = run_dispatcher(
                "session-start",
                payload,
                env={"PLUGIN_DATA": tmpdir},
                cwd=tmpdir,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, EXPECTED_FALLBACK_OUTPUT)

            after = snapshot_file_states(Path(tmpdir))
            self.assertEqual(before, after)

            def probe_state_change(
                setup,
                mutate,
                message: str,
            ) -> None:
                with tempfile.TemporaryDirectory() as probe_tmpdir:
                    probe_root = Path(probe_tmpdir)
                    setup(probe_root)
                    before_probe = snapshot_file_states(probe_root)
                    mutate(probe_root)
                    after_probe = snapshot_file_states(probe_root)
                    self.assertNotEqual(before_probe, after_probe, message)

            probe_state_change(
                lambda _: None,
                lambda d: (d / "empty-dir").mkdir(),
                "empty directory creation must change snapshot",
            )
            probe_state_change(
                lambda _: None,
                lambda d: (d / "created.txt").write_text(
                    "created",
                    encoding="utf-8",
                ),
                "file creation must change snapshot",
            )
            probe_state_change(
                lambda d: (d / "delete-me.txt").write_text(
                    "keep",
                    encoding="utf-8",
                ),
                lambda d: (d / "delete-me.txt").unlink(),
                "file deletion must change snapshot",
            )
            probe_state_change(
                lambda d: (d / "kind.txt").write_text("file", encoding="utf-8"),
                lambda d: ((d / "kind.txt").unlink(), (d / "kind.txt").mkdir()),
                "file-to-directory type change must change snapshot",
            )
            probe_state_change(
                lambda d: (d / "marker.txt").write_text("before", encoding="utf-8"),
                lambda d: (d / "marker.txt").write_text("after", encoding="utf-8"),
                "in-place file modification must change snapshot",
            )

    def test_cold_start_does_not_create_plugin_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            plugin_root = temp_root / "plugin"
            (plugin_root / "hooks").mkdir(parents=True)
            shutil.copytree(
                ROOT / "agentmemory",
                plugin_root / "agentmemory",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            shutil.copy2(DISPATCHER, plugin_root / "hooks" / DISPATCHER.name)

            payload = json.dumps(
                {
                    "hook_event_name": "SessionStart",
                    "cwd": str(temp_root),
                }
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(plugin_root / "hooks" / DISPATCHER.name),
                    "session-start",
                ],
                input=payload,
                text=True,
                capture_output=True,
                cwd=str(temp_root),
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, EXPECTED_FALLBACK_OUTPUT)
            self.assertEqual(result.stderr, "")
            self.assertEqual(list(plugin_root.rglob("__pycache__")), [])
            self.assertEqual(list(plugin_root.rglob("*.pyc")), [])


if __name__ == "__main__":
    unittest.main()
