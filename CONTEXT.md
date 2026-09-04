# Context

## Current Brief

This turn's only goal: finish and verify the opt-in scheduled AI candidate-distillation slot, document the next observability requirements without implementing telemetry, and prove the plugin can be isolated in a sandbox Codex home.

### Deliverables

- Add a worktree-local scheduler configuration with an explicit `enabled` switch, provider, model, cron expression, timezone label, and bounded provider options.
- Add fixed adapters for Codex CLI, Claude Code, and Gemini CLI; adapters use argument arrays without shell interpolation and run the selected AI in a read-only analysis mode.
- Add `schedule configure`, `enable`, `disable`, `status`, `plan`, and `run` commands. `plan` is read-only; `run` refuses disabled or malformed configuration.
- Have `schedule run` request a strict, bounded candidate batch, validate it through the existing candidate path, create at most five local candidates, and return a human-review report. It must never call review or write shared memory.
- Produce one final-state requirements document and focused tests covering configuration, cron validation, adapter rendering, provider-output parsing, candidate-only writes, failure handling, and compatibility.
- Add a bounded M10 requirements section for end-to-end write/retrieval/injection/outcome traceability and counterfactual usefulness experiments; do not implement it in M9.
- Install the current plugin package only into an isolated temporary Codex home and validate discovery/configuration without a paid provider run.

### Non-goals

- No automatic review, receipt creation, durable-memory promotion, lifecycle mutation, deletion, or shared-memory write.
- No transcript, `transcript_path`, `PLUGIN_DATA`, hidden reasoning, platform memory, OpenViking, cross-project aggregation, or browser-extension input.
- No scheduler installation, Codex automation creation, Windows Task Scheduler/cron mutation, real-host plugin installation, merge, push, release, or deployment in this phase.
- No observability trace writer, report database, telemetry service, automatic usefulness inference, or M10 runtime code.
- No provider plugin discovery, arbitrary shell templates, stored credentials, daemon, UI, remote Hub, replay evaluator, or shadow promotion.

### Settled Contracts

- Enabling the schedule is standing authorization to create reviewable local candidates only. `review --confirm` remains the sole promotion route and still needs immediate explicit human confirmation.
- Configuration lives under `.continuity/local/worktrees/<worktree-id>/scheduler.json`, remains ignored, embeds the expected repository/worktree identity, contains no credentials, and uses atomic locked writes.
- Canonical scheduling input is a validated POSIX-style five-field numeric cron expression. Seconds, macros, Quartz tokens, names, and provider-native recurrence syntax are outside M9; an outer scheduler consumes the returned plan.
- Providers are a closed registry: `codex`, `claude`, and `gemini`. The configured model is passed as one argument. Codex may also receive a validated reasoning effort.
- The AI process gets a strict JSON proposal contract and provider-enforced read-only repository access. AgentMemory, not the AI process, performs candidate writes after strict adapter-specific parsing and a post-run identity check.
- One run accepts at most five proposals and bounded output, deduplicates identical proposals, and rejects a checkout change before any write. Candidate IDs are deterministic for repository identity, current head, and normalized proposal so retries on unchanged evidence are idempotent.
- Invalid provider output creates no candidate. A valid batch may report individual proposal rejection, but promotion remains impossible without a later human review.
- Existing v1/v2 schemas, hooks, SessionStart, dynamic experience matching, OpenViking adapter, and reviewed-memory trust boundary remain unchanged.

### File and Phase Scope

- Current state remains only in this `CONTEXT.md` Current Brief and Pending List; lasting user-facing behavior is documented in `docs/SCHEDULED_MEMORY_CANDIDATES_REQUIREMENTS.zh-CN.md`.
- Approved implementation surfaces are a new pure-contract `agentmemory/scheduler.py`, a new execution boundary `agentmemory/schedule_runtime.py`, `agentmemory/storage.py`, `agentmemory/cli.py`, focused tests, `README.md`, `SECURITY.md`, `PRIVACY.md`, and the public AgentMemory Skill.
- Hooks, record schemas, OpenViking code, resume rendering, plugin manifest version, and reviewed-record behavior are do-not-touch.
- Work is isolated on `codex/m9-scheduled-memory-candidates`, based on P0 commit `e81deed`; pre-existing `.gitignore`, `.continuity/`, and context-audit changes are user state to preserve.

### Acceptance Commands

- `py -3 -m unittest tests.test_scheduler -v`
- `py -3 -m unittest discover -s tests -v`
- `python -m unittest discover -s tests -v`
- `py -3 -m compileall -q agentmemory hooks skills`
- Python 3.9 AST parsing, JSON parsing, Skill validation, Plugin validation, and `git diff --check`.
- Dry-run plans for Codex, Claude, and Gemini must contain no shell command string, secret, review command, receipt path, or shared-memory write.

### Stop Conditions

- Stop if a provider requires write-capable AI permissions, shell interpolation, credential persistence, or bypassing provider safety controls.
- Stop if candidate generation cannot remain bounded, parseable, secret-scanned, worktree-scoped, and separate from human review/promotion.
- Stop if implementation requires changing Hook events, reviewed schemas, `CONTINUITY.md`, OpenViking, or the existing receipt trust path.
- Stop before installing a scheduler, invoking a paid/provider run for acceptance, or making any external write without separate authorization.

## Pending List

- Current Work: M9 implementation, final regression, independent re-review, and isolated Codex-home installation are complete.
- OpenViking was queried with the explicit project URI but its local service was unavailable; this is not a feature precondition and no repair/start was attempted.
- External scheduler installation and live paid-provider execution remain deferred acceptance gates.
- M10 observability and usefulness-test requirements are documented but intentionally not implemented in M9.
- Exact Next Action: obtain explicit authorization before real-host installation, external scheduler creation, or a live paid-provider smoke run; otherwise start M10 observability as a separate branch.

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
