# Context

## Current Brief

This turn's only goal: implement and verify the smallest project-scoped M10 observability loop needed to trace memory writes, retrieval, injection, and explicitly annotated outcomes without weakening AgentMemory's review boundary.

### Deliverables

- Add an identity-bound, worktree-local `observability.enabled` switch that defaults off and is independent of the scheduler switch.
- Append bounded, privacy-minimized JSONL events for existing write, retrieval, and SessionStart injection boundaries; tracing is best effort and must never change the primary operation's result.
- Add explicit CLI operations to enable, disable, inspect, export, summarize, annotate an observed outcome, and confirm trace deletion.
- Correlate stages with locally generated opaque IDs and existing candidate/record IDs when available; never store prompts, memory content, provider output, environment values, raw session IDs, or hidden reasoning.
- Trace the existing deterministic relation-aware `experience match` budget, which grows from 8 KiB to a 24 KiB hard cap as trusted warning/strategy relations activate; do not mislabel retrieval-only output as SessionStart injection.
- Produce a deterministic daily JSON report that exposes event counts, write results, retrieval/injection coverage, explicit outcomes, and data-chain gaps for human review; it must not review, promote, delete, or infer usefulness.
- Preserve the documented four-arm counterfactual protocol as a later experiment runner; M10 collects the evidence needed for it but does not automate model experiments.

### Non-goals

- No automatic review, promotion, receipt creation, lifecycle mutation, shared-memory write, or memory deletion.
- No raw conversation, transcript, prompt, provider stdout/stderr, memory body, filesystem path, environment value, credential, hidden reasoning, or cross-project aggregation in trace data.
- No database, daemon, service, UI, remote telemetry, public Hub, automatic evaluator, experiment runner, causal inference, or scheduler installation.
- No change to v1/v2 record schemas, trust receipts, OpenViking query behavior, candidate limits, or provider adapters.
- No merge, push, release, external scheduler mutation, or destructive cleanup in this phase.

### Settled Contracts

- Observability configuration is exact-key validated and stored at `.continuity/local/worktrees/<worktree-id>/observability.json`; missing means disabled.
- Events are canonical one-line JSON objects at `observability/events.jsonl`, protected by a separate short-lived lock. Each line is at most 8 KiB; active storage is bounded to 10 MiB and 30 days by deterministic compaction.
- Automatic event writes fail open for observability only: malformed trace state, lock timeout, disk failure, or disabled tracing must not fail checkpoint, candidate, retrieval, schedule, review, or Hook behavior.
- Event types are `write_attempt`, `write_result`, `retrieval`, `injection`, and `outcome`; `used_by_agent`, `affected_decision`, and `task_success` remain nullable and are populated only by explicit confirmed outcome annotation.
- Retrieval records IDs/rank/score/filter metadata only when the underlying operation objectively exposes them. Missing OpenViking scores remain null; retrieval is never relabeled as injection.
- SessionStart is the only confirmed automatic injection boundary and retains its existing 6000-byte safety cap. Relation-aware growth belongs to explicit `experience match`, where selectors and activated relations objectively exist; M10 records its chosen budget but does not claim the result was injected.
- Reports describe evidence and explicit gaps. They never claim memory caused an outcome, and candidate generation remains separate from human review/promotion.

### File and Phase Scope

- Current task state remains only in this `CONTEXT.md`; lasting behavior belongs in the existing requirements/security/privacy/readme/Skill documentation.
- Approved code surfaces are a minimal new `agentmemory/observability.py`, existing `storage.py`, `cli.py`, `schedule_runtime.py`, `openviking.py`, `capsule.py`/`hook.py` only where the real boundary requires it, and focused tests.
- Record schemas, receipt validation, candidate/review semantics, provider prompts/adapters, hook event registration, plugin manifest shape, and shared storage are do-not-touch.
- Work is isolated on `codex/m10-memory-observability`, based on local `main` commit `97ac3ce`; pre-existing user changes in the original worktree remain untouched.

### Acceptance Commands

- `py -3 -m unittest tests.test_observability -v`
- Focused scheduler, OpenViking, storage/CLI, and Hook tests affected by instrumentation.
- `py -3 -m unittest discover -s tests -v`
- `python -m unittest discover -s tests -v`
- `py -3 -m compileall -q agentmemory hooks skills`
- Python 3.9 AST parsing, JSON parsing, Skill validation, Plugin validation, and `git diff --check`.
- Disabled observability creates no trace files; enabled tracing survives malformed/local write failures without altering primary command or Hook output.
- Report/export output parses as strict JSON and contains no raw content or host paths; explicit deletion and outcome annotation require confirmation.
- SessionStart remains bounded at 6000 bytes; `experience match` remains 8192 bytes at zero activated relations, grows by 2048 bytes per relation, and never exceeds 24576 bytes.

### Stop Conditions

- Stop if event correlation requires persisting raw session IDs, prompts, memory bodies, host paths, credentials, or hidden reasoning.
- Stop if instrumentation can fail the primary memory/Hook operation or requires changing record schemas/receipt trust.
- Stop if a useful daily report requires an automatic evaluator, causal inference, model call, database, service, or cross-project store.
- Stop before merge, push, release, scheduler creation, destructive cleanup, or automatic memory promotion.

## Pending List

- Current Work: M10 is implemented, accepted, and archived on remote branch `codex/m10-memory-observability`; merge, installation, release, scheduler creation, and experiment-runner automation remain separate decisions.
- M9 is merged locally into `main`, installed as personal plugin version `0.1.1+codex.20260905034459`, and passed a real Codex provider smoke in `C:\am9-smoke-0905`: exit 0, three local unreviewed candidates, one bounded rejection, zero tracked-file changes, scheduler disabled afterward.
- M9 live diagnostics also exposed the Windows long-path ceiling in the first disposable temp repository; the successful acceptance repo used a shorter path. Long-path support is intentionally deferred because it is not an M10 dependency.
- OpenViking was healthy earlier but returned no relevant project memory; live repository evidence remains authoritative.
- Exact Next Action: after explicit approval, merge the archived M10 branch into `main` and install the resulting personal plugin; otherwise keep remote `main` on the accepted M9 state.

## M10 Acceptance Evidence

- Branch: `codex/m10-memory-observability`, based on local `main` commit `97ac3ce`; accepted implementation commits end at `a024adf`.
- The opt-in, worktree-local observability loop records privacy-minimized write, retrieval, confirmed SessionStart injection, and explicitly confirmed outcome events. Automatic tracing fails open; export, report, outcome annotation, and deletion fail closed.
- Dynamic context remains selector-driven: explicit `experience match` starts at 8192 bytes, adds 2048 bytes per activated relation, and caps at 24576 bytes. SessionStart remains fixed at 6000 bytes because it has no objective relation-activation signal.
- `py -3 -m unittest tests.test_observability -q`: 19 passed in 69.629 seconds.
- `py -3 -m unittest tests.test_scheduler tests.test_hook_runtime -q`: 35 passed in 100.223 seconds.
- `py -3 -m unittest discover -s tests -q`: 151 passed with 2 expected Windows `mkfifo` capability skips in 334.276 seconds.
- `python -m unittest discover -s tests -q`: 151 passed with 2 expected Windows `mkfifo` capability skips in 354.710 seconds.
- Python 3.9 AST parsing passed for 15 files; JSON parsing passed for 7 files; compileall, Skill validation, Plugin validation, and `git diff --check` passed. `AICR-pass` is not installed and was not applicable.
- Fresh independent `gpt-5.6-terra xhigh` review initially found trace-identity, path-race, exact-bound, and orphan-outcome gaps. Commit `a024adf` fixed them; re-review reported no remaining P0-P2 findings.
- Residual security limit: portable Windows APIs cannot formally eliminate the final same-privilege reparse race between validation and replacement. The implementation follows the repository's existing path-validation model, uses a stable lock outside the trace directory, revalidates around lock/write/replace, and has symlink-swap regression coverage.
- M10 was pushed only to its milestone branch. It was not merged, installed, released, or connected to an external scheduler; remote `main` and the installed personal plugin remain on the accepted M9 state.

## M9 Acceptance Evidence

- Branch: `codex/m9-scheduled-memory-candidates`, based on P0 commit `e81deed`.
- `py -3 -m unittest discover -s tests -v`: 129 passed, 2 expected Windows `mkfifo` capability skips, 370.580 seconds.
- `python -m unittest discover -s tests -v`: 129 passed, 2 expected Windows `mkfifo` capability skips, 392.318 seconds.
- Fresh independent `gpt-5.6-terra xhigh` review found one disable/run TOCTOU issue; after the root fix and focused regression, re-review reported no remaining P0/P1 findings.
- A copied package passed Plugin and Skill validation, then Codex CLI 0.147.0 installed and enabled version 0.1.1 in an isolated temporary `CODEX_HOME`. A temporary Git repository passed status, init, disabled schedule configuration, plan, and `run --dry-run` using `codex`, `gpt-5.6-terra`, `xhigh`, `0 3 * * *`, and `Asia/Tokyo`.
- The temporary Codex home refused only PATH-alias creation because it was under the OS temp directory; plugin discovery, installation, enablement, and dry-run were successful.
- No live provider request, cost-bearing call, external scheduler, real Codex home, shared memory, review, promotion, merge, push, or deployment was used.

## P0 Acceptance Evidence

- Branch: `codex/m8-p0-experience-governance`, based on local `main` commit `06ddbcc`.
- Final independent `gpt-5.6-terra xhigh` review reported no P0-P3 findings after verifying projection bounds, receipt gating, lifecycle nonactivation, fan-out, schema parity, and v1/Hook isolation.
- `py -3 -m unittest discover -s tests -v`: 108 passed, 2 expected Windows `mkfifo` capability skips, 230.417 seconds.
- `python -m unittest discover -s tests -v`: 108 passed, 2 expected Windows `mkfifo` capability skips, 202.041 seconds.
- `compileall`, Python 3.9 AST parsing, JSON parsing for plugin/hooks/v1/v2 schemas, Skill validation, Plugin validation, and `git diff --check` passed.
- `AICR-pass` is not installed, so it was not applicable and did not block completion.
- Hooks, `.codex-plugin/plugin.json`, `schemas/record-v1.schema.json`, and `agentmemory/openviking.py` are unchanged from `06ddbcc`.
- OpenViking lookup was healthy with the explicit local config but returned no relevant P0 record; current repository evidence remained authoritative.
- Requested Spark implementation routing was attempted without `service_tier`, but the launched session was read-only; implementation used bounded Terra agents and a fresh independent Terra reviewer.
- Remaining risk: no live installation or deployed-host validation was performed because installation, merge, push, release, and deployment are explicit non-goals.

## M7 Acceptance Evidence

- Focused retrieval and CLI suite: 8 passed.
- Full regression suite: 89 passed, with 2 expected Windows FIFO skips.
- Python 3.9 AST parsing, `compileall`, JSON parsing, skill validation, plugin validation, and `git diff --check` passed.
- Live native OpenViking retrieval used the explicit config, returned the exact repository-derived URI with `results: []`, exited 0, and left Git status unchanged.
- Fresh Terra xhigh review found and then verified fixes for explicit CLI config discovery, endpoint disclosure, non-ASCII Git paths, absolute wrapper rejection, and leaf/parent reparse races; final review reported no P0-P3 findings.

## Accepted Baseline
- M0 hook-only baseline is at commit `8875076`.
- M1 core-contract passed independent Terra acceptance and is committed as `9f9290d`.
- M2 local checkpoint storage passed independent Terra acceptance and is committed as `2c7ec8e`.
- The dual-layer storage/validation direction remains: strict runtime canonical checks remain authoritative while JSON Schema mirrors enforceable constraints.
- M1 contract continues to hold: canonical JSON, UTF-8 checks, integrity enforcement, and schema-version/type bounds.
- M3 acceptance evidence: root and independent Terra reviews passed; both Python runners passed 64 tests with two Windows FIFO capability skips, plus compile, Python 3.9 AST, plugin validation, fail-closed, idempotence, branch, and leakage checks.
- M3 is archived as `fac58a3`; current focus is `codex/m4-continuity-hooks`.
- M4 goal: make the existing SessionStart hook inject one bounded deterministic resume capsule from the latest exact-context checkpoint plus confirmed current-branch project records; keep PreCompact safe and idempotent.
- M4 non-goals: PostCompact/PostToolUse/Stop/Subagent hooks, transcript parsing, implicit candidate capture, automatic promotion, new schema versions, skills, plugin metadata changes, OpenViking, MCP/daemon/UI, global/workspace memory, or install/trust changes.
- M4 constraints and acceptance:
  - Use only documented hook input fields; never read `transcript_path` or `PLUGIN_DATA`.
  - SessionStart is read-only. Non-Git, uninitialized, missing-checkpoint, malformed state, or runtime failure returns the exact harmless fallback `{"continue":true}` with no leakage.
  - The checkpoint must match repository, worktree, branch, and current head; stale-head checkpoints are reported only as a bounded non-restorable state and their content is not injected.
  - Candidates are never read or injected. Project records pass the M3 fail-closed checks and current branch/head rules.
  - Capsule output is deterministic, canonical, secret-scanned, and bounded below the host's model-visible output limit.
  - Current PreCompact payload has no stable explicit checkpoint content, so it remains a deterministic no-op rather than reading transcripts or fabricating state.
  - M0-M3 behavior and strict action/event rejection remain intact.
- M4 acceptance evidence: root review and independent Terra acceptance passed; capsule security, exact fallback, read-only cold start, branch/head filtering, deterministic budget handling, and M0-M3 regression coverage were verified.
- M4 final evidence: both Python runners passed 75 tests with two Windows FIFO capability skips; compile, Python 3.9 AST, JSON parsing, plugin validation, diff checks, and independent Terra acceptance passed.
- M4 is archived as `8c74d6e`; current focus is `codex/m5-plugin-package-e2e`.
- M5 goal: finish the distributable 0.1.0 plugin package with one public AgentMemory skill, accurate product/security/privacy documentation, and cohesive local CLI/hook/worktree end-to-end coverage.
- M5 non-goals: runtime/schema/storage behavior changes, new hook events, transcript or `PLUGIN_DATA` use, MCP/daemon/app/UI, workspace/global memory, automatic repository scanning, automatic candidate review/promotion, marketplace writes, installation, hook trust, remote push, or deployment.
- M5 constraints and acceptance:
  - Keep exactly one public skill. It may guide explicit `init`, `status`, `checkpoint`, `candidate`, `review --confirm`, and `render` operations through a bundled thin CLI launcher; it never edits `.continuity` files directly or treats memory as authority.
  - Package discovery must use valid plugin fields and existing default Hook discovery; no unsupported manifest keys or new lifecycle surface.
  - Documentation must state tracked versus ignored data, secret-scan limits, untrusted-memory precedence, branch/worktree behavior, rollback/data-retention behavior, and the separate installed-host trust gate.
  - E2E must use temporary Git repositories and linked worktrees to prove explicit checkpoint/resume, candidate exclusion, confirmed project records, branch/head filtering, secret rejection, deterministic PreCompact no-op, rebuild behavior, and no Hook/plugin bytecode side effects.
  - M0-M4 tests and behavior remain unchanged; no host installation or trust mutation is part of M5.
- M5 acceptance evidence: exact `gpt-5.3-codex-spark xhigh` implemented the bounded packaging and cohesive E2E slices with no `service_tier`; root reviewed and corrected the integrated result; fresh independent Terra acceptance passed after the E2E exercised the commands discovered from `hooks/hooks.json` and snapshot-checked the complete local continuity tree for side effects.
- M5 final evidence: both Python runners passed 77 tests with two Windows FIFO capability skips; the scoped package E2E passed 2 tests under each runner; compile, Python 3.9 AST, JSON parsing, skill validation, plugin validation, and diff checks passed.
- M5 is accepted on `codex/m5-plugin-package-e2e`; installation, hook trust, remote push, and deployment remain separate unapproved gates.
- M6 goal on `codex/m6-trusted-resume-boundary`: close the verified trust and resumability gaps with the smallest v1-compatible changes, without turning AgentMemory into the proposed full continuity platform.
- M6 constraints: preserve the 0.1.0 API/schema/package surface; no dirty-worktree fingerprint, Host approval attestation, lifecycle/supersession, evidence/applicability governance, handoff ownership, JIT retrieval, vector search, MCP/daemon/app/UI, or workspace/global memory. Named-branch project records remain branch-wide; detached records remain exact-head scoped.
- M6 implemented boundary: `review --confirm` now requires the candidate's original repository, worktree, branch, and head. A successful review writes an ignored, per-worktree receipt at `.continuity/local/worktrees/<worktree-id>/receipts/<record-id>.json`; SessionStart injects a project record only when that receipt's record id and content hash exactly match. Missing receipts skip the record, while malformed or conflicting receipts fail closed. This limits automatic injection of Git-fetched or manually modified tracked content, but is not an unforgeable Host-user approval and does not defend against malicious local writes.
- M6 implemented resumability boundary: checkpoint creation rejects and does not persist content that cannot fit by itself in the fixed 6000 UTF-8 byte resume capsule.
- M6 final evidence: on the current final worktree, root verification passed 81 tests with 2 Windows FIFO capability skips across the 27-test and 54-test groups; compileall, Python 3.9 AST parsing for 11 files, JSON parsing for 6 files, skill validation, plugin validation, and diff checks passed. Fresh independent Terra re-review passed after the P2 fix with no new material findings.
