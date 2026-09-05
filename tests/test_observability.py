import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentmemory import observability
from agentmemory.observability import ObservabilityError
from agentmemory.storage import StorageError, initialize_repository
from tests.test_scheduler import _repo


def _retrieval_payload():
    return {"source": "experience", "query_digest": "a" * 64, "result_ids": ["mem-1"], "ranks": [0], "scores": [None], "lifecycle": "active", "filter": "project", "activated_relation_count": 1, "byte_budget": 8192, "byte_count": 1, "omitted_count": 0}


class ObservabilityTests(unittest.TestCase):
    def _initialized(self):
        directory = tempfile.TemporaryDirectory()
        repo = Path(directory.name) / "repo"
        _repo(repo)
        initialize_repository(repo)
        return directory, repo

    def test_missing_config_is_disabled_and_creates_no_trace_files(self):
        directory, repo = self._initialized()
        with directory:
            self.assertFalse(observability.emit(repo, event_type="write_attempt", payload={"operation": "checkpoint", "trigger": "cli", "source": "cli", "kind": "checkpoint", "scope": "local"}))
            self.assertEqual(list((repo / ".continuity" / "local").rglob("*observability*")), [])

    def test_config_is_identity_bound_and_malformed_state_fails_closed(self):
        directory, repo = self._initialized()
        with directory:
            config = observability.configure(repo, enabled=True)
            self.assertTrue(config["enabled"])
            path = repo / ".continuity" / "local" / "worktrees" / config["worktree_id"] / "observability.json"
            path.write_text(json.dumps({**config, "repository_id": "0" * 64}), encoding="utf-8")
            with self.assertRaises(ObservabilityError):
                observability.load_config(repo)
            path.write_text('{"enabled":true}', encoding="utf-8")
            with self.assertRaises(ObservabilityError):
                observability.load_config(repo)

    def test_config_reparse_is_rejected_when_supported(self):
        directory, repo = self._initialized()
        with directory:
            config = observability.configure(repo, enabled=True)
            path = repo / ".continuity" / "local" / "worktrees" / config["worktree_id"] / "observability.json"
            outside = repo / "outside.json"
            outside.write_text(json.dumps(config), encoding="utf-8")
            path.unlink()
            try:
                path.symlink_to(outside)
            except OSError as exc:
                self.skipTest("symlink unavailable ({})".format(exc))
            with self.assertRaises((ObservabilityError, StorageError)):
                observability.load_config(repo)

    def test_append_schema_privacy_and_best_effort_failure(self):
        directory, repo = self._initialized()
        with directory:
            observability.configure(repo, enabled=True)
            self.assertTrue(observability.emit(repo, event_type="retrieval", payload=_retrieval_payload(), memory_id="mem-1"))
            self.assertFalse(observability.emit(repo, event_type="write_attempt", payload={"operation": "raw prompt"}))
            self.assertFalse(observability.emit(repo, event_type="retrieval", payload={**_retrieval_payload(), "query_digest": "prompt text"}))
            self.assertFalse(observability.emit(repo, event_type="retrieval", payload={**_retrieval_payload(), "ranks": []}))
            exported = observability.export(repo)
            self.assertEqual(len(exported["events"]), 1)
            self.assertEqual(exported["events"][0]["memory_id"], "mem-1")

    def test_bounded_reads_and_opaque_ids_fail_closed(self):
        directory, repo = self._initialized()
        with directory:
            config = observability.configure(repo, enabled=True)
            path = repo / ".continuity" / "local" / "worktrees" / config["worktree_id"] / "observability.json"
            path.write_bytes(b"x" * (observability.MAX_EVENT_BYTES + 1))
            with self.assertRaises(ObservabilityError):
                observability.load_config(repo)
            observability.configure(repo, enabled=True)
            events = path.parent / "observability" / "events.jsonl"
            events.parent.mkdir(exist_ok=True)
            events.write_bytes(b"x" * (observability.MAX_LOG_BYTES + observability.MAX_EVENT_BYTES + 1))
            with self.assertRaises(ObservabilityError):
                observability.export(repo)
            event = {"schema_version": 1, "event_id": "bad id", "correlation_id": "cor-ok", "event_type": "retrieval", "observed_at": "2026-01-01T00:00:00Z", "repository_id": "a", "worktree_id": "b", "branch": "main", "head": "c", "candidate_id": None, "record_id": None, "memory_id": None, "payload": _retrieval_payload()}
            with self.assertRaises(ObservabilityError):
                observability.validate_event(event)
            event["event_id"] = "evt-ok"
            event["payload"] = {**_retrieval_payload(), "result_ids": [1]}
            with self.assertRaises(ObservabilityError):
                observability.validate_event(event)
            event["payload"] = _retrieval_payload()
            event["branch"] = "功能/分支"
            self.assertEqual(observability.validate_event(event)["branch"], "功能/分支")
            event["branch"] = "bad\x01branch"
            with self.assertRaises(ObservabilityError):
                observability.validate_event(event)

    def test_bounds_retention_and_deterministic_report(self):
        directory, repo = self._initialized()
        with directory:
            observability.configure(repo, enabled=True)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            old = now - timedelta(days=31)
            event = {"schema_version": 1, "event_id": "evt-old", "correlation_id": "cor-old", "event_type": "write_attempt", "observed_at": old.isoformat().replace("+00:00", "Z"), "repository_id": "a", "worktree_id": "b", "branch": "main", "head": "c", "candidate_id": None, "record_id": None, "memory_id": None, "payload": {"operation": "checkpoint", "trigger": "cli", "source": "cli", "kind": "checkpoint", "scope": "local"}}
            self.assertEqual(observability._compact([observability.validate_event(event)]), [])
            event["payload"] = {"operation": "checkpoint" * 2000, "trigger": "cli", "source": "cli", "kind": "checkpoint", "scope": "local"}
            with self.assertRaises(ObservabilityError):
                observability.validate_event(event)
            self.assertTrue(observability.emit(repo, event_type="retrieval", payload=_retrieval_payload(), correlation_id="cor-1"))
            self.assertTrue(observability.emit(repo, event_type="write_result", correlation_id="cor-write", payload={"operation": "checkpoint", "trigger": "cli", "source": "cli", "kind": "checkpoint", "scope": "local", "status": "created", "reason": None}))
            report = observability.report(repo, day=now.date().isoformat())
            self.assertEqual(report, observability.report(repo, day=now.date().isoformat()))
            self.assertEqual(report["write_result_statuses"]["created"], 1)
            self.assertEqual(observability.export(repo, since=now.date().isoformat(), until=now.date().isoformat())["events"], observability.export(repo)["events"])
            with self.assertRaises(ObservabilityError):
                observability.export(repo, since="2026-01-02", until="2026-01-01")

    def test_write_result_reason_matches_status(self):
        directory, repo = self._initialized()
        with directory:
            observability.configure(repo, enabled=True)
            base = {"operation": "checkpoint", "trigger": "cli", "source": "cli", "kind": "checkpoint", "scope": "local"}
            self.assertFalse(observability.emit(repo, event_type="write_result", payload={**base, "status": "created", "reason": "invalid"}))
            self.assertFalse(observability.emit(repo, event_type="write_result", payload={**base, "status": "failure", "reason": None}))
            self.assertTrue(observability.emit(repo, event_type="write_result", payload={**base, "status": "failure", "reason": "storage_failure"}))

    def test_explicit_outcome_and_confirmed_deletion(self):
        directory, repo = self._initialized()
        with directory:
            observability.configure(repo, enabled=True)
            self.assertTrue(observability.emit(repo, event_type="injection", correlation_id="cor-2", payload={"memory_ids": ["mem-1"], "order": [0], "bytes": 1, "budget": 2, "truncated": False, "conflict_reason": None}))
            self.assertTrue(observability.annotate_outcome(repo, correlation_id="cor-2", confirm=True, used_by_agent=True, affected_decision=None, task_success=True, user_corrections=0, retries=0, turns=1, tool_calls=1, token_cost=None))
            self.assertEqual(observability.export(repo)["events"][-1]["event_type"], "outcome")
            with self.assertRaises(ObservabilityError):
                observability.delete(repo, confirm=False, all_events=True)
            self.assertEqual(observability.delete(repo, confirm=True, all_events=True), 2)

    def test_disabled_outcome_annotation_fails_closed(self):
        directory, repo = self._initialized()
        with directory:
            with self.assertRaises(ObservabilityError):
                observability.annotate_outcome(repo, correlation_id="cor-3", confirm=True, used_by_agent=None, affected_decision=None, task_success=None, user_corrections=None, retries=None, turns=None, tool_calls=None, token_cost=None)


if __name__ == "__main__":
    unittest.main()
