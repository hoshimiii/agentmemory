from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from agentmemory import identity, schema
from agentmemory.security import SecretScanError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "record-v1.schema.json"

REPO_ID = "a" * 64
WORKTREE_ID = "b" * 64
REPO_HEAD = "0" * 40


def _run_git(
    args: list[str],
    cwd: Path,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    execution_env = os.environ.copy()
    if env:
        execution_env.update(env)
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=execution_env,
        check=False,
        timeout=10,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.strip() or proc.stdout.strip())
    return proc


def _head_commit(path: Path) -> str:
    return _run_git(["rev-parse", "--verify", "HEAD"], cwd=path).stdout.strip()


def _timestamp() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()


def _timestamp_z() -> str:
    return _timestamp().replace("+00:00", "Z")


def _repo_head_or_fallback() -> str:
    try:
        value = _run_git(["rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
        if len(value) == 40 and schema.HEAD_SHA_RE.fullmatch(value):
            return value
    except Exception:
        pass
    return REPO_HEAD


def _base_record_kwargs(
    record_type: str,
    *,
    scope: str,
    kind: str,
    status: str,
    semantic_role: str,
) -> dict:
    return {
        "schema_version": 1,
        "id": f"rec-{record_type}",
        "record_type": record_type,
        "kind": kind,
        "status": status,
        "semantic_role": semantic_role,
        "summary": "Canonical summary for contract test.",
        "scope": scope,
        "applies_to": {
            "repository_id": REPO_ID,
            "worktree_id": WORKTREE_ID,
            "branch": "main",
            "head": _repo_head_or_fallback(),
            "paths": ["notes/plan.md", "src/main.py"],
        },
        "provenance": {
            "source": "test-run",
            "evidence_refs": ["evt-1"],
            "source_record_id": "src-1",
        },
        "content": {"facts": {"value": 1}},
        "review": {
            "confirmed": False,
            "confirmed_by": None,
            "confirmed_at": None,
        },
        "created_at": _timestamp(),
    }


def _seal_record(record: dict) -> dict:
    with_integrity = schema.annotate_with_integrity(record, version=1)
    return with_integrity


def _valid_checkpoint() -> dict:
    record = _base_record_kwargs(
        "checkpoint",
        scope="local",
        kind="checkpoint",
        status="active",
        semantic_role="fact",
    )
    return _seal_record(record)


def _valid_candidate() -> dict:
    record = _base_record_kwargs(
        "candidate",
        scope="local",
        kind="decision",
        status="candidate",
        semantic_role="inference",
    )
    return _seal_record(record)


def _valid_project_record(*, semantic_role: str = "fact") -> dict:
    record = _base_record_kwargs(
        "project_record",
        scope="project",
        kind="decision",
        status="active",
        semantic_role=semantic_role,
    )
    record["review"] = {
        "confirmed": True,
        "confirmed_by": "explicit_user",
        "confirmed_at": _timestamp(),
    }
    return _seal_record(record)


class TestAgentMemoryCoreContract(unittest.TestCase):
    def test_valid_checkpoint_candidate_and_project_records(self) -> None:
        for rec in (_valid_checkpoint(), _valid_candidate(), _valid_project_record()):
            schema.validate_record(rec)

    def test_unknown_top_level_and_nested_fields_rejected(self) -> None:
        record = _valid_candidate()
        record["unexpected"] = "bad"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(record)

        broken = _valid_checkpoint()
        broken["applies_to"]["unexpected"] = "bad"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(broken)

    def test_bad_enums_rejected(self) -> None:
        record = _valid_candidate()
        record["record_type"] = "foreign"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(record)

        record = _valid_candidate()
        record["kind"] = "foreign"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(record)

    def test_invariant_violations_rejected(self) -> None:
        bad = _valid_checkpoint()
        bad["review"]["confirmed_by"] = "explicit_user"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_checkpoint()
        bad["review"]["confirmed_at"] = _timestamp()
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_checkpoint()
        bad["kind"] = "decision"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["review"]["confirmed_by"] = "explicit_user"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["review"]["confirmed_at"] = _timestamp()
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["semantic_role"] = "instruction"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["status"] = "active"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_project_record()
        bad["semantic_role"] = "instruction"
        bad["kind"] = "decision"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

    def test_head_must_be_commit_sha_or_unborn(self) -> None:
        record = _valid_candidate()
        record["applies_to"]["head"] = _repo_head_or_fallback()
        record = schema.annotate_with_integrity(record)
        schema.validate_record(record)

        unborn = _valid_candidate()
        unborn["applies_to"]["head"] = "UNBORN"
        unborn = schema.annotate_with_integrity(unborn)
        schema.validate_record(unborn)

        for bad_head in ["HEAD", "master", "1234", "G" * 40, "ab" * 20, "a" * 39]:
            bad = _valid_candidate()
            bad["applies_to"]["head"] = bad_head
            with self.assertRaises(schema.RecordValidationError):
                schema.validate_record(bad)

    def test_branch_name_validation_and_bounds(self) -> None:
        valid_candidates = [
            "main",
            "feature/foo",
            "release/v2.1",
            "hotfix/_cleanup",
            "功能/修复",
            "@",
            "DETACHED",
        ]
        for branch in valid_candidates:
            record = _valid_candidate()
            record["applies_to"]["branch"] = branch
            record = schema.annotate_with_integrity(record)
            schema.validate_record(record)

        invalid_branches = [
            "",
            " main",
            "main ",
            "main/",
            "/main",
            ".main",
            "main.",
            "main//patch",
            "main/.",
            "feat/..",
            "feat@{1}",
            "feat~x",
            "feat^x",
            "feat:x",
            "feat?x",
            "feat*x",
            "feat[x",
            "feat\\x",
            "-option",
            "a/.hidden",
            "topic.lock",
            "feature/topic.lock/next",
        ]
        for branch in invalid_branches:
            bad = _valid_candidate()
            bad["applies_to"]["branch"] = branch
            bad = schema.annotate_with_integrity(bad)
            with self.assertRaises(schema.RecordValidationError):
                schema.validate_record(bad)

    def test_schema_version_and_integrity_version_reject_bool(self) -> None:
        bad_schema_version = _valid_candidate()
        bad_schema_version["schema_version"] = True
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad_schema_version)

        bad_integrity_version = _valid_candidate()
        bad_integrity_version["integrity"]["version"] = False
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad_integrity_version)

        with self.assertRaises(schema.RecordValidationError):
            schema.annotate_with_integrity(_valid_candidate(), version=True)

    def test_path_and_provenance_bounds(self) -> None:
        valid = _valid_candidate()
        valid["applies_to"]["paths"] = ["文档/决策.md", ".continuity/CONTINUITY.md"]
        valid = schema.annotate_with_integrity(valid)
        schema.validate_record(valid)

        long_path = "x" * (schema.MAX_PATH_LENGTH + 1)
        bad = _valid_candidate()
        bad["applies_to"]["paths"] = [long_path]
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["applies_to"]["paths"] = ["notes/main.md"] * (schema.MAX_PATHS_COUNT + 1)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        for bad_path in ["a//b", " notes/a.md", "notes/a.md ", "repo:path/file", "notes/"]:
            bad = _valid_candidate()
            bad["applies_to"]["paths"] = [bad_path]
            bad = schema.annotate_with_integrity(bad)
            with self.assertRaises(schema.RecordValidationError):
                schema.validate_record(bad)

        bad = _valid_candidate()
        bad["provenance"]["source"] = "x" * (schema.MAX_PROVENANCE_SOURCE_LENGTH + 1)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["provenance"]["evidence_refs"] = ["evt"] * (schema.MAX_EVIDENCE_REFS + 1)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["provenance"]["evidence_refs"][0] = "x" * (schema.MAX_EVIDENCE_REF_LENGTH + 1)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["provenance"]["source_record_id"] = "x" * (schema.MAX_SOURCE_RECORD_ID_LENGTH + 1)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["provenance"]["source_record_id"] = "   "
        bad = schema.annotate_with_integrity(bad)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

    def test_bad_paths_and_timestamps_and_hash_fail(self) -> None:
        bad = _valid_candidate()
        bad["applies_to"]["paths"] = ["/abs/path.md"]
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["applies_to"]["paths"] = ["notes/../secrets.md"]
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["created_at"] = "2026-07-23T12:00:00"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["integrity"]["content_hash"] = "md5:not-a-hash"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

    def test_unknown_schema_version_rejected(self) -> None:
        bad = _valid_candidate()
        bad["schema_version"] = 2
        bad = schema.annotate_with_integrity(bad)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

    def test_tampering_is_detected(self) -> None:
        record = _valid_candidate()
        record = schema.annotate_with_integrity(record)
        schema.validate_record(record)
        record["summary"] = "tampered"
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(record)

    def test_oversized_content_rejected(self) -> None:
        record = _valid_candidate()
        record["content"] = {"blob": "x" * (schema.MAX_CONTENT_BYTES + 1)}
        record = schema.annotate_with_integrity(record)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(record)

    def test_candidate_cannot_be_instruction_or_confirmed_or_project_like(self) -> None:
        bad = _valid_candidate()
        bad["semantic_role"] = "instruction"
        bad = schema.annotate_with_integrity(bad)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["status"] = "active"
        bad = schema.annotate_with_integrity(bad)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["scope"] = "project"
        bad = schema.annotate_with_integrity(bad)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

    def test_project_instruction_allowed_only_as_reviewed_constraint(self) -> None:
        valid = _valid_project_record(semantic_role="instruction")
        valid["kind"] = "constraint"
        valid = schema.annotate_with_integrity(valid)
        schema.validate_record(valid)

        bad = _valid_project_record(semantic_role="instruction")
        bad["kind"] = "decision"
        bad = schema.annotate_with_integrity(bad)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_project_record(semantic_role="fact")
        bad["review"] = {
            "confirmed": False,
            "confirmed_by": None,
            "confirmed_at": None,
        }
        bad = schema.annotate_with_integrity(bad)
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

    def test_project_record_requires_source_record_id(self) -> None:
        bad = _valid_project_record()
        bad["provenance"]["source_record_id"] = ""
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        good = _valid_project_record()
        good["provenance"]["source_record_id"] = "src-1"
        schema.validate_record(good)

    def test_validate_record_does_not_mutate_input(self) -> None:
        original = _valid_candidate()
        snapshot = copy.deepcopy(original)
        schema.validate_record(original)
        self.assertEqual(original, snapshot)

    def test_validate_record_rejects_noncanonical_json_shapes(self) -> None:
        bad = _valid_candidate()
        bad["content"] = {"bad": float("nan")}
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["content"] = {1: "key must be a string"}
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        bad["content"] = {"bad": {1, 2, 3}}
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

        bad = _valid_candidate()
        loop: dict[str, object] = {}
        loop["self"] = loop
        bad["content"] = loop
        with self.assertRaises(schema.RecordValidationError):
            schema.validate_record(bad)

    def test_validate_record_rejects_unserializable_and_utf8_payload(self) -> None:
        bad = _valid_candidate()
        bad["content"] = {"value": "\ud800"}
        with self.assertRaises(schema.RecordValidationError):
            schema.annotate_with_integrity(bad)

    def test_timestamp_z_roundtrip(self) -> None:
        record = _valid_project_record()
        created_at = _timestamp_z()
        confirmed_at = _timestamp_z()
        record["created_at"] = created_at
        record["review"]["confirmed_at"] = confirmed_at
        sealed = schema.annotate_with_integrity(record)
        validated = schema.validate_record(sealed)
        self.assertEqual(validated["created_at"], created_at)
        self.assertEqual(validated["review"]["confirmed_at"], confirmed_at)

        offset = _valid_candidate()
        offset["created_at"] = "2026-07-23T12:00:00-05:00"
        offset = schema.annotate_with_integrity(offset)
        schema.validate_record(offset)

    def test_identity_detects_worktree_subdir_and_non_bare_state(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            root = Path(workdir) / "repo"
            worktree = Path(workdir) / "linked"
            root.mkdir()
            _run_git(["init", "--initial-branch=main"], cwd=root)
            _run_git(["config", "user.name", "agentmemory"], cwd=root)
            _run_git(["config", "user.email", "agentmemory@agentmemory.example"], cwd=root)
            readme = root / "README.md"
            readme.write_text("content", encoding="utf-8")
            _run_git(["add", "README.md"], cwd=root)
            _run_git(["commit", "-m", "init", "--allow-empty"], cwd=root)
            _run_git(["worktree", "add", str(worktree)], cwd=root)

            subdir = root / "subdir"
            subdir.mkdir()

            main_identity = identity.get_git_identity(root)
            linked_identity = identity.get_git_identity(worktree)
            subdir_identity = identity.get_git_identity(subdir)
            expected_head = _head_commit(root)

            self.assertIn("toplevel", linked_identity)
            self.assertIn("common_dir", linked_identity)
            self.assertEqual(main_identity["repository_id"], linked_identity["repository_id"])
            self.assertEqual(main_identity["common_dir"], linked_identity["common_dir"])
            self.assertNotEqual(main_identity["worktree_id"], linked_identity["worktree_id"])
            self.assertEqual(main_identity["branch"], "main")
            self.assertEqual(subdir_identity["branch"], "main")
            self.assertEqual(main_identity["head"], expected_head)
            self.assertEqual(subdir_identity["head"], expected_head)

    def test_identity_reports_detached_and_unborn_states(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            detached = Path(workdir) / "detached"
            detached.mkdir()
            _run_git(["init", "--initial-branch=main"], cwd=detached)
            _run_git(["config", "user.name", "agentmemory"], cwd=detached)
            _run_git(["config", "user.email", "agentmemory@agentmemory.example"], cwd=detached)
            _run_git(["commit", "--allow-empty", "-m", "root"], cwd=detached)
            branch_head = _head_commit(detached)
            _run_git(["checkout", "--detach", branch_head], cwd=detached)

            detached_identity = identity.get_git_identity(detached)
            self.assertEqual(detached_identity["branch"], "DETACHED")
            self.assertEqual(detached_identity["head"], branch_head)

            unborn = Path(workdir) / "unborn"
            unborn.mkdir()
            _run_git(["init", "--initial-branch=main"], cwd=unborn)
            unborn_identity = identity.get_git_identity(unborn)
            self.assertEqual(unborn_identity["branch"], "main")
            self.assertEqual(unborn_identity["head"], "UNBORN")

    def test_identity_fails_for_non_git_and_bare(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            bad = Path(workdir) / "bad"
            bad.mkdir()
            with self.assertRaises(identity.GitIdentityError) as ctx:
                identity.get_git_identity(bad)
            self.assertEqual(str(ctx.exception), identity.GIT_IDENTITY_ERROR)

            bare = Path(workdir) / "bare.git"
            _run_git(["init", "--bare", "--initial-branch=main", str(bare)], cwd=Path(workdir))
            with self.assertRaises(identity.GitIdentityError) as ctx:
                identity.get_git_identity(bare)
            self.assertEqual(str(ctx.exception), identity.GIT_IDENTITY_ERROR)

    def test_secret_scan_rejects_sensitive_material(self) -> None:
        secrets = [
            "sk-12345678901234567890",
            "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            "Bearer abcdefghijklmnopqrstuvwxyz123456",
            "postgres://user:pass@localhost/db",
        ]
        for secret in secrets:
            record = _valid_candidate()
            record["content"] = {"api_key": secret}
            with self.assertRaises(SecretScanError):
                schema.validate_record(record)

    def test_schema_file_is_valid_and_structural(self) -> None:
        loaded = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertFalse(loaded["additionalProperties"])
        self.assertEqual(
            loaded["x-agentmemory-runtime-validation-required"],
            schema.RUNTIME_VALIDATION_REQUIRED,
        )

        required = set(loaded["required"])
        expected_required = set(
            [
                "schema_version",
                "id",
                "record_type",
                "kind",
                "status",
                "semantic_role",
                "summary",
                "scope",
                "applies_to",
                "provenance",
                "content",
                "review",
                "created_at",
                "integrity",
            ]
        )
        self.assertEqual(required, expected_required)
        self.assertEqual(loaded["properties"]["record_type"]["enum"], ["checkpoint", "candidate", "project_record"])
        self.assertEqual(loaded["properties"]["kind"]["enum"], ["checkpoint", "decision", "incident", "constraint"])
        self.assertEqual(loaded["properties"]["status"]["enum"], ["candidate", "active"])
        self.assertEqual(loaded["properties"]["scope"]["enum"], ["local", "project"])
        self.assertEqual(loaded["properties"]["applies_to"]["required"], ["repository_id", "worktree_id", "branch", "head", "paths"])

        self.assertEqual(loaded["properties"]["id"]["pattern"], schema.RECORD_ID_RE.pattern)
        self.assertEqual(loaded["properties"]["id"]["maxLength"], schema.MAX_RECORD_ID_LENGTH)
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["repository_id"]["pattern"],
            schema.RECORD_ID_SHA256_RE.pattern,
        )
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["worktree_id"]["pattern"],
            schema.RECORD_ID_SHA256_RE.pattern,
        )
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["head"]["oneOf"][1]["pattern"],
            schema.HEAD_SHA_ONLY_RE.pattern,
        )
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["head"]["oneOf"][1]["maxLength"],
            40,
        )
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["branch"]["oneOf"][1]["maxLength"],
            schema.MAX_BRANCH_LENGTH,
        )
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["branch"]["oneOf"][1]["pattern"],
            schema.SCHEMA_BRANCH_PATTERN,
        )
        self.assertIsNone(schema.SCHEMA_BRANCH_RE.fullmatch("DETACHED"))
        self.assertIsNotNone(schema.SCHEMA_BRANCH_RE.fullmatch("功能/修复"))
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["paths"]["maxItems"],
            schema.MAX_PATHS_COUNT,
        )
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["paths"]["items"]["maxLength"],
            schema.MAX_PATH_LENGTH,
        )
        self.assertEqual(
            loaded["properties"]["applies_to"]["properties"]["paths"]["items"]["pattern"],
            schema.SCHEMA_PATH_PATTERN,
        )
        self.assertIsNotNone(schema.SCHEMA_PATH_RE.fullmatch("文档/决策.md"))
        self.assertEqual(
            loaded["properties"]["provenance"]["properties"]["source"]["maxLength"],
            schema.MAX_PROVENANCE_SOURCE_LENGTH,
        )
        self.assertEqual(
            loaded["properties"]["provenance"]["properties"]["evidence_refs"]["maxItems"],
            schema.MAX_EVIDENCE_REFS,
        )
        self.assertEqual(
            loaded["properties"]["provenance"]["properties"]["evidence_refs"]["items"]["maxLength"],
            schema.MAX_EVIDENCE_REF_LENGTH,
        )
        self.assertEqual(
            loaded["properties"]["provenance"]["properties"]["source_record_id"]["maxLength"],
            schema.MAX_SOURCE_RECORD_ID_LENGTH,
        )
        self.assertEqual(
            loaded["properties"]["created_at"]["maxLength"],
            schema.MAX_TIMESTAMP_LENGTH,
        )
        self.assertEqual(loaded["properties"]["created_at"]["format"], "date-time")
        self.assertEqual(
            loaded["properties"]["review"]["properties"]["confirmed_at"]["maxLength"],
            schema.MAX_TIMESTAMP_LENGTH,
        )
        self.assertEqual(loaded["properties"]["review"]["properties"]["confirmed_at"]["format"], "date-time")

        all_of = loaded["allOf"]
        candidate_constraints = next(
            entry
            for entry in all_of
            if entry.get("if", {}).get("properties", {}).get("record_type", {}).get("const") == "candidate"
        )
        checkpoint_constraints = next(
            entry
            for entry in all_of
            if entry.get("if", {}).get("properties", {}).get("record_type", {}).get("const") == "checkpoint"
        )
        project_constraints = next(
            entry
            for entry in all_of
            if entry.get("if", {}).get("properties", {}).get("record_type", {}).get("const") == "project_record"
        )
        instruction_constraints = next(
            entry
            for entry in all_of
            if entry.get("if", {}).get("properties", {}).get("semantic_role", {})
            == {"const": "instruction"}
        )

        self.assertEqual(
            candidate_constraints["then"]["properties"]["review"]["properties"]["confirmed_by"]["type"],
            "null",
        )
        self.assertEqual(
            candidate_constraints["then"]["properties"]["review"]["properties"]["confirmed_at"]["type"],
            "null",
        )
        self.assertEqual(
            checkpoint_constraints["then"]["properties"]["review"]["properties"]["confirmed_by"]["type"],
            "null",
        )
        self.assertEqual(
            checkpoint_constraints["then"]["properties"]["review"]["properties"]["confirmed_at"]["type"],
            "null",
        )
        self.assertEqual(
            project_constraints["then"]["properties"]["review"]["properties"]["confirmed"]["const"],
            True,
        )
        self.assertEqual(
            project_constraints["then"]["properties"]["review"]["properties"]["confirmed_by"]["const"],
            "explicit_user",
        )
        self.assertEqual(
            project_constraints["then"]["properties"]["review"]["properties"]["confirmed_at"]["type"],
            "string",
        )
        self.assertEqual(
            project_constraints["then"]["properties"]["provenance"]["properties"]["source_record_id"]["minLength"],
            1,
        )
        self.assertEqual(
            instruction_constraints["then"]["properties"]["kind"]["const"],
            "constraint",
        )


if __name__ == "__main__":
    unittest.main()
