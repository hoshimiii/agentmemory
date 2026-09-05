import io
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agentmemory import observability
from agentmemory.observability import ObservabilityError
from agentmemory.storage import StorageError, initialize_repository
from agentmemory.cli import run as cli_run
from tests.test_scheduler import _repo


def _retrieval_payload():
    return {"source": "experience", "query_digest": "a" * 64, "result_ids": ["mem-1"], "ranks": [0], "scores": [None], "lifecycle": "active", "filter": "project", "activated_relation_count": 1, "byte_budget": 8192, "byte_count": 1, "omitted_count": 0}


def _sized_event(line_bytes):
    base = {"schema_version": 1, "event_id": "evt-size", "correlation_id": "cor-size", "event_type": "retrieval",
            "observed_at": "2026-01-01T00:00:00Z", "repository_id": "repo", "worktree_id": "worktree",
            "branch": "main", "head": "head", "candidate_id": None, "record_id": None, "memory_id": None}
    for count in range(128):
        for length in range(1, 129):
            ids = ["m"] * count + ["m" * length]
            event = {**base, "payload": {**_retrieval_payload(), "result_ids": ids, "ranks": list(range(len(ids))), "scores": [None] * len(ids)}}
            if len(observability.canonical_json_dumps(event).encode("utf-8")) + 1 == line_bytes:
                return event
    raise AssertionError("unable to construct exact event size")


class ObservabilityTests(unittest.TestCase):
    def _cli_raw(self, *argv):
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_run(argv)
        return code, output.getvalue()

    def _cli(self, *argv):
        code, output = self._cli_raw(*argv)
        return code, json.loads(output) if output else None

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
            oversized = b"x" * (observability.MAX_LOG_BYTES + 1)
            events.write_bytes(oversized)
            with self.assertRaises(ObservabilityError):
                observability.export(repo)
            with self.assertRaises(ObservabilityError):
                observability.delete(repo, confirm=True, all_events=True)
            self.assertEqual(events.read_bytes(), oversized)
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

    def test_physical_event_and_store_bounds_are_exact(self):
        directory, repo = self._initialized()
        with directory, mock.patch.object(observability, "MAX_EVENT_BYTES", 1024), mock.patch.object(observability, "MAX_LOG_BYTES", 2048):
            observability.configure(repo, enabled=True)
            _, _, paths = observability._layout(repo)
            exact = _sized_event(1024)
            self.assertEqual(len(observability.canonical_json_dumps(exact).encode("utf-8")) + 1, 1024)
            self.assertEqual(observability.validate_event(exact)["event_id"], "evt-size")
            too_large = _sized_event(1025)
            with self.assertRaises(ObservabilityError):
                observability.validate_event(too_large)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            paths["events"].write_bytes((observability.canonical_json_dumps(exact) + "\n").encode("utf-8"))
            self.assertEqual(observability._read_events(paths)[0]["event_id"], "evt-size")
            for index in range(12):
                self.assertTrue(observability.emit(repo, event_type="retrieval", correlation_id="cor-{}".format(index), memory_id="mem-{}".format(index), payload=_retrieval_payload()))
            self.assertLessEqual(paths["events"].stat().st_size, observability.MAX_LOG_BYTES)

    def test_observability_lock_and_atomic_write_revalidate_swaps(self):
        directory, repo = self._initialized()
        with directory:
            observability.configure(repo, enabled=True)
            _, _, paths = observability._layout(repo)
            self.assertEqual(paths["lock"].parent.name, "locks")
            self.assertNotEqual(paths["lock"].parent, paths["directory"])
            outside = Path(directory.name) / "outside"
            outside.mkdir()
            real_lock = observability.FileLock

            class SwapDirectoryLock:
                def __init__(self, *args, **kwargs):
                    self.lock = real_lock(*args, **kwargs)

                def __enter__(self):
                    paths["directory"].symlink_to(outside, target_is_directory=True)
                    return self.lock.__enter__()

                def __exit__(self, *args):
                    return self.lock.__exit__(*args)

            try:
                with mock.patch.object(observability, "FileLock", SwapDirectoryLock):
                    self.assertFalse(observability.emit(repo, event_type="retrieval", payload=_retrieval_payload()))
            except OSError as exc:
                self.skipTest("symlink unavailable ({})".format(exc))
            self.assertEqual(list(outside.iterdir()), [])
            self.assertTrue(paths["lock"].exists())
            paths["directory"].unlink()

            paths["directory"].mkdir()
            real_validate = observability._validate_within_root
            swapped = False

            def swap_before_replace(root, target, *, target_is_file):
                nonlocal swapped
                if target == paths["events"] and target_is_file and not swapped and list(paths["directory"].glob(".o.*.tmp")):
                    paths["events"].symlink_to(outside / "events.jsonl")
                    swapped = True
                return real_validate(root, target, target_is_file=target_is_file)

            with mock.patch.object(observability, "_validate_within_root", side_effect=swap_before_replace):
                self.assertFalse(observability.emit(repo, event_type="retrieval", payload=_retrieval_payload()))
            self.assertTrue(swapped)
            self.assertFalse((outside / "events.jsonl").exists())
            self.assertTrue(paths["events"].is_symlink())
            paths["events"].unlink()

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
            with self.assertRaises(ObservabilityError):
                observability.annotate_outcome(repo, correlation_id="cor-missing", confirm=True, used_by_agent=True, affected_decision=None, task_success=True, user_corrections=0, retries=0, turns=1, tool_calls=1, token_cost=None)
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

    def test_cli_controls_and_disabled_write(self):
        directory, repo = self._initialized()
        with directory:
            base = ("--repo", str(repo), "observability")
            self.assertEqual(self._cli(*base, "status"), (0, {"configured": False, "enabled": False}))
            self.assertEqual(self._cli(*base, "enable")[0], 0)
            self.assertTrue(self._cli(*base, "status")[1]["enabled"])
            self.assertEqual(self._cli(*base, "disable")[0], 0)
            before = self._cli("--repo", str(repo), "checkpoint", "create", "--summary", "x", "--content-json", "{}", "--id", "cp-observe")
            self.assertEqual(before[0], 0)
            self.assertEqual(observability.export(repo)["events"], [])

    def test_cli_checkpoint_correlation_and_outcome(self):
        directory, repo = self._initialized()
        with directory:
            self.assertEqual(self._cli("--repo", str(repo), "observability", "enable")[0], 0)
            self.assertEqual(self._cli("--repo", str(repo), "checkpoint", "create", "--summary", "x", "--content-json", "{}", "--id", "cp-observe")[0], 0)
            events = observability.export(repo)["events"]
            self.assertEqual([item["event_type"] for item in events], ["write_attempt", "write_result"])
            self.assertEqual(events[0]["correlation_id"], events[1]["correlation_id"])
            self.assertEqual(events[0]["record_id"], "cp-observe")
            self.assertEqual(events[1]["record_id"], "cp-observe")
            correlation = events[0]["correlation_id"]
            args = ("--repo", str(repo), "observability", "outcome", "annotate", "--correlation-id", correlation, "--used-by-agent", "unknown", "--affected-decision", "false", "--task-success", "true", "--confirm")
            self.assertEqual(self._cli(*args)[0], 0)

    def test_cli_known_id_survives_failed_write_trace(self):
        directory, repo = self._initialized()
        with directory:
            self.assertEqual(self._cli("--repo", str(repo), "observability", "enable")[0], 0)
            command = ("--repo", str(repo), "candidate", "propose", "--kind", "decision", "--summary", "candidate", "--content-json", "{}", "--id", "cand-failure")
            with redirect_stderr(io.StringIO()), mock.patch("agentmemory.cli.create_candidate", side_effect=StorageError("failed")):
                self.assertEqual(self._cli(*command)[0], 1)
            events = observability.export(repo)["events"]
            self.assertEqual([event["candidate_id"] for event in events], ["cand-failure", "cand-failure"])
            self.assertEqual(events[-1]["payload"]["status"], "failure")

    def test_cli_observability_export_report_and_confirmed_delete(self):
        directory, repo = self._initialized()
        with directory:
            base = ("--repo", str(repo), "observability")
            day = datetime.now(timezone.utc).date().isoformat()
            self.assertEqual(self._cli(*base, "enable")[0], 0)
            self.assertEqual(self._cli("--repo", str(repo), "checkpoint", "create", "--summary", "x", "--content-json", "{}", "--id", "cp-export")[0], 0)

            code, exported = self._cli(*base, "export", "--since", day, "--until", day)
            self.assertEqual(code, 0)
            self.assertTrue(exported["enabled"])
            self.assertEqual([event["event_type"] for event in exported["events"]], ["write_attempt", "write_result"])
            report = self._cli(*base, "report", "--date", day)[1]
            self.assertEqual(report["counts"]["write_attempt"], 1)
            self.assertEqual(report["write_result_statuses"]["created"], 1)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(self._cli(*base, "delete", "--all")[0], 2)
            self.assertEqual(self._cli(*base, "delete", "--all", "--confirm"), (0, {"deleted": 2}))
            self.assertEqual(self._cli(*base, "export"), (0, {"enabled": True, "events": []}))

    def test_cli_schedule_trace_pairs_and_rejection_outcomes(self):
        directory, repo = self._initialized()
        with directory:
            self.assertEqual(self._cli("--repo", str(repo), "observability", "enable")[0], 0)
            command = ("--repo", str(repo), "schedule", "run")
            with mock.patch("agentmemory.cli.run_schedule", return_value={"plan": True}) as run:
                self.assertEqual(self._cli(*command, "--dry-run"), (0, {"plan": True}))
            run.assert_called_once_with(str(repo), dry_run=True)
            self.assertEqual(observability.export(repo)["events"], [])

            mixed = {"candidates": [{"id": "cand-created", "kind": "decision", "created": True, "idempotent": False}, {"id": "cand-idempotent", "kind": "warning", "created": False, "idempotent": True}], "rejected_count": 1}
            with mock.patch("agentmemory.cli.run_schedule", return_value=mixed) as run:
                self.assertEqual(self._cli(*command), (0, mixed))
            run.assert_called_once_with(str(repo), dry_run=False)
            events = observability.export(repo)["events"]
            self.assertEqual([event["event_type"] for event in events], ["write_attempt", "write_result", "write_result", "write_result"])
            self.assertEqual({event["correlation_id"] for event in events}, {events[0]["correlation_id"]})
            self.assertEqual([(event["candidate_id"], event["payload"]["kind"], event["payload"]["status"]) for event in events[1:]], [("cand-created", "decision", "created"), ("cand-idempotent", "warning", "idempotent"), (None, None, "rejected")])
            self.assertEqual(events[-1]["payload"]["reason"], "invalid")

            observability.delete(repo, confirm=True, all_events=True)
            rejected = {"candidates": [], "rejected_count": 2}
            with mock.patch("agentmemory.cli.run_schedule", return_value=rejected):
                self.assertEqual(self._cli(*command), (0, rejected))
            rejected_events = observability.export(repo)["events"]
            self.assertEqual([event["event_type"] for event in rejected_events], ["write_attempt", "write_result"])
            self.assertEqual(rejected_events[0]["correlation_id"], rejected_events[1]["correlation_id"])
            result = rejected_events[1]
            self.assertEqual(result["event_type"], "write_result")
            self.assertEqual(result["payload"]["status"], "rejected")
            self.assertEqual(result["payload"]["reason"], "invalid")

            observability.delete(repo, confirm=True, all_events=True)
            with mock.patch("agentmemory.cli.run_schedule", return_value={"candidates": [], "rejected_count": 0}):
                self.assertEqual(self._cli(*command), (0, {"candidates": [], "rejected_count": 0}))
            empty_events = observability.export(repo)["events"]
            self.assertEqual([event["event_type"] for event in empty_events], ["write_attempt", "write_result"])
            self.assertEqual(empty_events[-1]["payload"]["status"], "success")

    def test_cli_candidate_and_review_write_result_ids_and_status(self):
        directory, repo = self._initialized()
        with directory:
            self.assertEqual(self._cli("--repo", str(repo), "observability", "enable")[0], 0)
            candidate = self._cli("--repo", str(repo), "candidate", "propose", "--kind", "decision", "--summary", "candidate", "--content-json", "{}", "--id", "cand-observe")[1]
            candidate_events = observability.export(repo)["events"]
            self.assertEqual(candidate_events[0]["correlation_id"], candidate_events[1]["correlation_id"])
            self.assertEqual(candidate_events[0]["candidate_id"], candidate["id"])
            self.assertEqual(candidate_events[1]["candidate_id"], candidate["id"])
            self.assertEqual(candidate_events[1]["payload"]["status"], "created")

            reviewed = self._cli("--repo", str(repo), "review", "--candidate", candidate["id"], "--confirm")[1]
            review_events = observability.export(repo)["events"][-2:]
            self.assertEqual(review_events[0]["correlation_id"], review_events[1]["correlation_id"])
            self.assertEqual(review_events[0]["candidate_id"], candidate["id"])
            self.assertEqual(review_events[1]["candidate_id"], candidate["id"])
            self.assertEqual(review_events[1]["record_id"], reviewed["id"])
            self.assertEqual(review_events[1]["payload"]["status"], "success")

    def test_cli_experience_trace_metrics_and_trace_error_is_inert(self):
        directory, repo = self._initialized()
        with directory:
            self.assertEqual(self._cli("--repo", str(repo), "observability", "enable")[0], 0)
            rendered = json.dumps({
                "selected": [{"id": "exp-alpha"}, {"id": "warn-beta"}],
                "activated_relation_count": 2,
                "byte_budget": 1536,
                "byte_count": 987,
                "omitted_count": 3,
            }, separators=(",", ":"))
            command = ("--repo", str(repo), "experience", "match", "--task-type", "bugfix", "--signal", "receipt", "--path", "agentmemory/storage.py", "--max-bytes", "1536")
            with mock.patch("agentmemory.cli.load_trusted_experiences", return_value=[]), \
                 mock.patch("agentmemory.cli.render_experience_match", return_value=rendered):
                self.assertEqual(self._cli_raw(*command), (0, rendered))
            event = observability.export(repo)["events"][-1]
            self.assertEqual(event["payload"]["source"], "experience")
            self.assertEqual(event["payload"]["result_ids"], ["exp-alpha", "warn-beta"])
            self.assertEqual(event["payload"]["activated_relation_count"], 2)
            self.assertEqual(event["payload"]["byte_budget"], 1536)
            self.assertEqual(event["payload"]["byte_count"], 987)
            self.assertEqual(event["payload"]["omitted_count"], 3)

            observability.delete(repo, confirm=True, all_events=True)
            with mock.patch("agentmemory.cli.load_trusted_experiences", return_value=[]), \
                 mock.patch("agentmemory.cli.render_experience_match", return_value=rendered), \
                 mock.patch("agentmemory.cli._digest", side_effect=RuntimeError("trace derivation failed")):
                self.assertEqual(self._cli_raw(*command), (0, rendered))
            self.assertEqual(observability.export(repo)["events"], [])

    def test_cli_openviking_trace_uses_hashed_ids_and_query_digest(self):
        directory, repo = self._initialized()
        with directory:
            self.assertEqual(self._cli("--repo", str(repo), "observability", "enable")[0], 0)
            query = "retrieve architecture context"
            uris = ["ov://project/doc-a", "ov://project/doc-b"]
            response = {"results": [{"uri": uri} for uri in uris]}
            command = ("--repo", str(repo), "retrieve", "--query", query, "--openviking-cli", "C:/tools/ov.exe", "--openviking-config", "C:/tools/ov.json", "--limit", "2")
            with mock.patch("agentmemory.cli.retrieve_project_knowledge", return_value=response) as retrieve:
                self.assertEqual(self._cli_raw(*command), (0, json.dumps(response, separators=(",", ":"), ensure_ascii=False)))
            retrieve.assert_called_once_with(str(repo), query, "C:/tools/ov.exe", "C:/tools/ov.json", limit=2)
            event = observability.export(repo)["events"][-1]
            expected_ids = ["ov-" + hashlib.sha256(uri.encode("utf-8")).hexdigest() for uri in uris]
            self.assertEqual(event["payload"]["source"], "openviking")
            self.assertEqual(event["payload"]["query_digest"], hashlib.sha256(query.encode("utf-8")).hexdigest())
            self.assertEqual(event["payload"]["result_ids"], expected_ids)
            serialized_events = json.dumps(observability.export(repo)["events"], separators=(",", ":"), ensure_ascii=False)
            self.assertNotIn(query, serialized_events)
            for uri in uris:
                self.assertNotIn(uri, serialized_events)


if __name__ == "__main__":
    unittest.main()
