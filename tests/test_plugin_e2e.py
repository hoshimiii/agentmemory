from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from agentmemory.identity import get_git_identity


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".codex-plugin"
PLUGIN_JSON = PLUGIN_DIR / "plugin.json"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
SKILL_MD = ROOT / "skills" / "agentmemory" / "SKILL.md"
OPENAI_YAML = ROOT / "skills" / "agentmemory" / "agents" / "openai.yaml"
LAUNCHER = ROOT / "skills" / "agentmemory" / "scripts" / "agentmemory_cli.py"
README = ROOT / "README.md"
SECURITY = ROOT / "SECURITY.md"
PRIVACY = ROOT / "PRIVACY.md"
HOOK = ROOT / "hooks" / "agentmemory_hook.py"
HOOKS_DIR = ROOT / "hooks"
SKILL_DIR = ROOT / "skills" / "agentmemory"
RUNTIME_DIR = ROOT / "agentmemory"

EXPECTED_CONTINUE_OUTPUT = '{"continue":true}'

MAIN_CHECKPOINT = "cp-main"
MAIN_CANDIDATE = "cand-main"
MAIN_CHECKPOINT_NEXT = "cp-main-next"
FEATURE_CHECKPOINT = "cp-feature"
FEATURE_BRANCH = "feature"
LINKED_BRANCH = "linked"
LINKED_CHECKPOINT = "cp-linked"
SECRET_CANDIDATE = "cand-secret"
SECRET_SENTINEL = "sk-secret-token-abcdefghijklmnopq"


def _run_git(
    args: list[str],
    cwd: Path,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=process_env,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())
    return result


def _run_launcher(
    args: list[str],
    repo_root: Path,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(LAUNCHER), "--repo", str(repo_root), *args]
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_launcher_json(
    args: list[str],
    repo_root: Path,
    cwd: Path,
) -> Dict[str, Any]:
    result = _run_launcher(args, repo_root, cwd)
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def _run_hook(
    action: str,
    cwd: Path,
    payload: Dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    payload_json = json.dumps(payload, separators=(",", ":"))
    command = [sys.executable, str(HOOK), action]
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        input=payload_json,
        capture_output=True,
        check=False,
    )


def _run_discovered_hook(
    event_name: str,
    cwd: Path,
    payload: Dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    hooks_config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hook = hooks_config["hooks"][event_name][0]["hooks"][0]
    process_env = os.environ.copy()
    process_env["PLUGIN_ROOT"] = str(ROOT)

    if os.name == "nt":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            raise AssertionError("PowerShell is required for Windows Hook E2E")
        command = [shell, "-NoProfile", "-NonInteractive", "-Command", hook["commandWindows"]]
    else:
        shell = shutil.which("sh")
        if shell is None:
            raise AssertionError("sh is required for Hook E2E")
        command = [shell, "-c", hook["command"]]

    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        input=json.dumps(payload, separators=(",", ":")),
        capture_output=True,
        env=process_env,
        check=False,
    )


def _parse_session_start(result: subprocess.CompletedProcess[str]) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())

    outer = json.loads(result.stdout)
    context = None
    additional = outer.get("hookSpecificOutput")
    if additional is not None:
        context = json.loads(additional["additionalContext"])
    return outer, context


def _snapshot_tree(root: Path) -> Dict[str, str]:
    states: Dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = stat.S_IFMT(info.st_mode)
        if stat.S_ISDIR(mode):
            states[rel] = f"dir:{info.st_mtime_ns}"
        elif stat.S_ISLNK(mode):
            states[rel] = f"symlink:{info.st_mtime_ns}:{path.as_posix()}"
        elif stat.S_ISREG(mode):
            states[rel] = (
                f"file:{info.st_mtime_ns}:{info.st_size}:"
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}"
            )
        else:
            states[rel] = f"other:{mode}:{info.st_mtime_ns}"
    return states


def _git_status(repo_root: Path) -> str:
    return _run_git(["status", "--short"], repo_root).stdout


def _init_repo(repo_root: Path) -> None:
    _run_git(["init", "--initial-branch=main"], repo_root)
    _run_git(["config", "user.name", "agentmemory"], repo_root)
    _run_git(["config", "user.email", "agentmemory@agentmemory.example"], repo_root)
    _run_git(["commit", "--allow-empty", "-m", "init"], repo_root)


def _candidate_file(repo_root: Path, candidate_id: str) -> Path:
    identity = get_git_identity(repo_root)
    return (
        repo_root
        / ".continuity"
        / "local"
        / "worktrees"
        / identity["worktree_id"]
        / "candidates"
        / f"{candidate_id}.json"
    )


def _parse_frontmatter(text: str) -> Dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}

    values: Dict[str, str] = {}
    for raw in lines[1:end]:
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class TestPluginPackageE2E(unittest.TestCase):
    def test_package_contract(self) -> None:
        manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("name"), "agentmemory")
        self.assertEqual(manifest.get("version"), "0.1.0")
        self.assertEqual(manifest.get("skills"), "./skills/")
        self.assertNotIn("hooks", manifest)
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)

        self.assertTrue(HOOKS_JSON.exists())
        skills = [path for path in (ROOT / "skills").iterdir() if path.is_dir()]
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "agentmemory")

        self.assertTrue(SKILL_MD.exists())
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(skill_text)
        self.assertEqual(set(frontmatter), {"name", "description"})
        self.assertNotIn("todo", skill_text.lower())
        skill_text_lower = skill_text.lower()
        self.assertIn("explicit", skill_text_lower)
        self.assertIn("confirmation", skill_text_lower)
        self.assertIn("untrusted", skill_text_lower)
        self.assertIn("transcript", skill_text_lower)

        self.assertTrue(LAUNCHER.exists())
        self.assertTrue(OPENAI_YAML.exists())
        self.assertIn("$agentmemory", OPENAI_YAML.read_text(encoding="utf-8"))

        for path in [README, SECURITY, PRIVACY]:
            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("m0", text)
            self.assertNotIn("probe", text)
            self.assertNotIn(".agentmemory storage", text)

    def test_cohesive_runtime_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            repo = temp_root / "repo"
            repo.mkdir()
            linked = temp_root / "linked"
            launcher_cwd = temp_root / "outside-caller"
            launcher_cwd.mkdir()

            _init_repo(repo)

            try:
                init_payload = _run_launcher_json(["init"], repo, launcher_cwd)
                self.assertTrue(init_payload["initialized"])

                _run_git(["add", ".gitignore", ".continuity/manifest.json", ".continuity/CONTINUITY.md"], repo)
                _run_git(["commit", "-m", "agentmemory scaffold"], repo)

                main_cp = _run_launcher_json(
                    [
                        "checkpoint",
                        "create",
                        "--id",
                        MAIN_CHECKPOINT,
                        "--summary",
                        "main checkpoint",
                        "--content-json",
                        json.dumps({"phase": "main"}, separators=(",", ":")),
                    ],
                    repo,
                    launcher_cwd,
                )
                self.assertEqual(main_cp["id"], MAIN_CHECKPOINT)

                main_candidate = _run_launcher_json(
                    [
                        "candidate",
                        "propose",
                        "--id",
                        MAIN_CANDIDATE,
                        "--kind",
                        "decision",
                        "--summary",
                        "primary decision",
                        "--content-json",
                        json.dumps({"decision": "choose"}, separators=(",", ":")),
                        "--semantic-role",
                        "fact",
                    ],
                    repo,
                    launcher_cwd,
                )
                self.assertEqual(main_candidate["id"], MAIN_CANDIDATE)

                start_outer, start_context = _parse_session_start(
                    _run_hook(
                        "session-start",
                        repo,
                        {"hook_event_name": "SessionStart", "cwd": str(repo)},
                    )
                )
                self.assertEqual(start_outer["continue"], True)
                self.assertIsNotNone(start_context)
                self.assertEqual(start_context["checkpoint"]["id"], MAIN_CHECKPOINT)
                self.assertEqual(start_context["project_records"], [])
                rendered_start = json.dumps(start_context, separators=(",", ":"))
                self.assertNotIn(MAIN_CANDIDATE, rendered_start)
                self.assertNotIn("primary decision", rendered_start)

                review = _run_launcher_json(
                    ["review", "--candidate", MAIN_CANDIDATE, "--confirm"],
                    repo,
                    launcher_cwd,
                )
                project_record_id = review["id"]
                self.assertEqual(review["candidate_id"], MAIN_CANDIDATE)

                _run_git(
                    [
                        "add",
                        ".continuity/CONTINUITY.md",
                        ".continuity/shared/records",
                    ],
                    repo,
                )
                _run_git(["commit", "-m", "render continuity"], repo)

                first_render = _run_launcher_json(["render"], repo, launcher_cwd)
                second_render = _run_launcher_json(["render"], repo, launcher_cwd)
                self.assertEqual(first_render["count"], 1)
                self.assertEqual(first_render, second_render)

                next_cp = _run_launcher_json(
                    [
                        "checkpoint",
                        "create",
                        "--id",
                        MAIN_CHECKPOINT_NEXT,
                        "--summary",
                        "main checkpoint latest",
                        "--content-json",
                        json.dumps({"phase": "next", "step": 2}, separators=(",", ":")),
                    ],
                    repo,
                    launcher_cwd,
                )
                self.assertEqual(next_cp["id"], MAIN_CHECKPOINT_NEXT)

                _, post_context = _parse_session_start(
                    _run_hook(
                        "session-start",
                        repo,
                        {"hook_event_name": "SessionStart", "cwd": str(repo)},
                    )
                )
                self.assertIsNotNone(post_context)
                self.assertEqual(post_context["checkpoint"]["id"], MAIN_CHECKPOINT_NEXT)
                project_records = post_context["project_records"]
                self.assertEqual(len(project_records), 1)
                self.assertEqual(project_records[0]["id"], project_record_id)
                self.assertEqual(project_records[0]["record_type"], "project_record")
                self.assertEqual(project_records[0]["summary"], "primary decision")
                self.assertEqual([record["record_type"] for record in project_records], ["project_record"])

                secret_proposal = _run_launcher(
                    [
                        "candidate",
                        "propose",
                        "--id",
                        SECRET_CANDIDATE,
                        "--kind",
                        "decision",
                        "--summary",
                        "secret content",
                        "--content-json",
                        json.dumps({"token": SECRET_SENTINEL}, separators=(",", ":")),
                    ],
                    repo,
                    launcher_cwd,
                )
                self.assertNotEqual(secret_proposal.returncode, 0)
                self.assertEqual(secret_proposal.stdout, "")
                combined = (secret_proposal.stdout + secret_proposal.stderr)
                self.assertNotIn(SECRET_SENTINEL, combined)
                self.assertNotIn(SECRET_CANDIDATE, combined)
                self.assertFalse(_candidate_file(repo, SECRET_CANDIDATE).exists())
                for file in (repo / ".continuity").rglob("*.json"):
                    if file.is_file():
                        self.assertNotIn(SECRET_SENTINEL, file.read_text(encoding="utf-8"))

                plugin_snapshot = {
                    "runtime": _snapshot_tree(RUNTIME_DIR),
                    "hooks": _snapshot_tree(HOOKS_DIR),
                    "skill": _snapshot_tree(SKILL_DIR),
                }
                status_before = _git_status(repo)
                continuity_local = repo / ".continuity" / "local"
                continuity_before = _snapshot_tree(continuity_local)

                first_hook = _run_discovered_hook(
                    "SessionStart",
                    repo,
                    {"hook_event_name": "SessionStart", "cwd": str(repo)},
                )
                second_hook = _run_discovered_hook(
                    "SessionStart",
                    repo,
                    {"hook_event_name": "SessionStart", "cwd": str(repo)},
                )
                first_precompact = _run_discovered_hook(
                    "PreCompact",
                    repo,
                    {"hook_event_name": "PreCompact"},
                )
                second_precompact = _run_discovered_hook(
                    "PreCompact",
                    repo,
                    {"hook_event_name": "PreCompact"},
                )
                self.assertEqual(first_hook.stdout, second_hook.stdout)
                self.assertEqual(first_precompact.stdout, second_precompact.stdout)
                self.assertNotEqual(first_hook.stdout, EXPECTED_CONTINUE_OUTPUT)
                self.assertEqual(first_precompact.stdout, EXPECTED_CONTINUE_OUTPUT)
                self.assertEqual(_snapshot_tree(RUNTIME_DIR), plugin_snapshot["runtime"])
                self.assertEqual(_snapshot_tree(HOOKS_DIR), plugin_snapshot["hooks"])
                self.assertEqual(_snapshot_tree(SKILL_DIR), plugin_snapshot["skill"])
                self.assertEqual(_git_status(repo), status_before)
                self.assertEqual(_snapshot_tree(continuity_local), continuity_before)

                _run_git(["checkout", "-b", FEATURE_BRANCH], repo)
                fallback_outer, _ = _parse_session_start(
                    _run_hook(
                        "session-start",
                        repo,
                        {"hook_event_name": "SessionStart", "cwd": str(repo)},
                    )
                )
                self.assertTrue(fallback_outer["continue"])
                self.assertNotIn("hookSpecificOutput", fallback_outer)

                _run_launcher_json(
                    [
                        "checkpoint",
                        "create",
                        "--id",
                        FEATURE_CHECKPOINT,
                        "--summary",
                        "feature checkpoint",
                        "--content-json",
                        json.dumps(
                            {"checkpoint_only": "must-not-restore"},
                            separators=(",", ":"),
                        ),
                    ],
                    repo,
                    launcher_cwd,
                )

                _, feature_context = _parse_session_start(
                    _run_hook(
                        "session-start",
                        repo,
                        {"hook_event_name": "SessionStart", "cwd": str(repo)},
                    )
                )
                self.assertIsNotNone(feature_context)
                self.assertEqual(feature_context["checkpoint"]["id"], FEATURE_CHECKPOINT)
                self.assertEqual(feature_context["project_records"], [])

                _run_git(["commit", "--allow-empty", "-m", "feature stale head"], repo)
                stale_result = _run_hook(
                    "session-start",
                    repo,
                    {"hook_event_name": "SessionStart", "cwd": str(repo)},
                )
                _, stale_feature_context = _parse_session_start(stale_result)
                self.assertIsNotNone(stale_feature_context)
                self.assertTrue(stale_feature_context["stale_head"])
                self.assertNotIn("checkpoint", stale_feature_context)
                self.assertNotIn("must-not-restore", stale_result.stdout)

                _run_git(
                    [
                        "worktree",
                        "add",
                        "-b",
                        LINKED_BRANCH,
                        str(linked),
                        "main",
                    ],
                    repo,
                )

                linked_status = _run_launcher_json(["status"], linked, launcher_cwd)
                self.assertTrue(linked_status["initialized"])
                self.assertEqual(linked_status["checkpoint_count"], 0)
                self.assertIsNone(linked_status["latest_checkpoint_id"])

                _run_launcher_json(
                    [
                        "checkpoint",
                        "create",
                        "--id",
                        LINKED_CHECKPOINT,
                        "--summary",
                        "linked checkpoint",
                        "--content-json",
                        json.dumps({"branch": "linked"}, separators=(",", ":")),
                    ],
                    linked,
                    launcher_cwd,
                )

                _, linked_context = _parse_session_start(
                    _run_hook(
                        "session-start",
                        linked,
                        {"hook_event_name": "SessionStart", "cwd": str(linked)},
                    )
                )
                self.assertIsNotNone(linked_context)
                self.assertEqual(linked_context["checkpoint"]["id"], LINKED_CHECKPOINT)

                feature_status = _run_launcher_json(["status"], repo, launcher_cwd)
                self.assertEqual(feature_status["latest_checkpoint_id"], FEATURE_CHECKPOINT)
            finally:
                if linked.exists():
                    _run_git(["worktree", "remove", "--force", str(linked)], repo)
