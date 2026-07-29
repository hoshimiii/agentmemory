# Context

## Current Brief

This turn's only goal: specify, implement, and verify the P0 private experience-governance layer while preserving the accepted AgentMemory trust boundary.

### Deliverables

- Produce one self-contained P0 requirements document covering rationale, data contracts, lifecycle, applicability, evidence, dynamic context activation, CLI/storage/render behavior, compatibility, security boundaries, and rollback.
- Add compact project-scoped `strategy` and `warning` experience records through the existing candidate -> explicit review -> local receipt trust path.
- Add explicit lifecycle and lineage sufficient to represent `active`, `superseded`, and `deprecated` reviewed experience without automatic promotion or deletion.
- Add bounded applicability and verification evidence fields that are integrity-protected and fail closed; self-reported scores are not promotion evidence.
- Add an explicit matcher/renderer for task signals that returns only applicable, locally trusted active experience and grows context according to activated relations instead of one fixed 6000-byte budget.
- Preserve existing checkpoint, decision, incident, constraint, OpenViking retrieval, branch/worktree isolation, receipt, secret-scan, and hook behavior unless the approved requirements explicitly replace the fixed resume budget.
- Provide a multi-level checklist and tests mapping each requirement to observable evidence.

### Non-goals

- No EvoMap Hub, GDI, credits, public asset import, network sharing, autonomous mutation, live promotion, evaluator self-editing, or background daemon.
- No Capsule solidification, EvolutionEvent scoring, offline replay engine, shadow routing, automatic signal extraction, transcript/reasoning-trace ingestion, or cross-project experience transfer in P0.
- No OpenViking writes or use of OpenViking results as promotion evidence.
- No browser-extension integration, workspace/global memory, MCP/app/UI, installation, remote push, release, or deployment.

### Settled Contracts

- Existing candidate review, exact repository/worktree/branch/head checks, content integrity, secret scanning, local receipts, atomic writes, and fail-closed loading remain the sole trust and promotion boundary.
- `strategy` and `warning` are advisory untrusted context below higher-priority instructions and current repository evidence; they never execute tools or mutate a repository by themselves.
- A strategy and its warnings remain separate objects. Lineage links are identifiers only and cannot bypass review, receipt, repository identity, applicability, or lifecycle checks.
- The generator cannot modify evaluator criteria or convert its own claimed success into verified evidence. P0 stores objective command/result metadata only after explicit proposal and review.
- Dynamic context is relation-driven but not unbounded: explicit task-time matching starts at 8192 bytes, grows by 2048 bytes per activated Strategy-Warning relation, and stops at 24576 bytes. Each compact record is at most 2048 bytes and is included whole.
- Existing `SessionStart` continuity semantics and its fixed 6000-byte checkpoint capsule remain unchanged. P0 adds explicit task-time experience matching and does not infer tasks in SessionStart.
- P0 uses strict schema-version dispatch and stores reviewed v2 experiences under `.continuity/shared/experiences/`; the v1 schema, v1 shared records, manifest, `CONTINUITY.md`, hooks, and OpenViking adapter remain unchanged.

### File and Phase Scope

- Investigation may inspect schema/storage/render/CLI/hooks, all tests, public docs/skill, and accepted M6/M7 contracts; investigation agents are read-only.
- Requirements are recorded in one P0 requirements document; current task state remains only in this `CONTEXT.md` Current Brief and Pending List.
- Approved implementation surfaces are `agentmemory/schema.py`, `agentmemory/storage.py`, `agentmemory/render.py`, `agentmemory/cli.py`, new `schemas/experience-v2.schema.json`, focused tests, and public documentation/skill. `schemas/record-v1.schema.json` may be regression-checked but not changed.
- Hooks, OpenViking code, manifest contents, and v1 resume rendering are do-not-touch.
- Work is isolated on `codex/m8-p0-experience-governance`, based on local `main` commit `06ddbcc`.

### Acceptance

- Requirements and multi-level checklist map every P0 behavior, security boundary, compatibility rule, and deferred feature to acceptance evidence.
- Existing tests remain green; new tests cover both valid flows and malformed, stale, cross-project, missing-receipt, lifecycle, relation-cycle, context-growth, ceiling, and deterministic-order cases.
- Candidate and review remain the only promotion route; unreviewed, unreceipted, superseded, deprecated, inapplicable, malformed, and cross-project experience never becomes active task context.
- Dynamic output is deterministic for the same identity, signals, active graph, and safety limit; more activated valid relations may grow output, while cycles and fan-out remain bounded.
- `py -3 -m unittest discover -s tests -v`, `python -m unittest discover -s tests -v`, compile checks, Python 3.9 parsing when available, JSON/schema validation, skill/plugin validation, and `git diff --check` pass.

### Stop Conditions

- Stop if a slice requires weakening explicit review, receipt, identity, secret, path, integrity, or fail-closed behavior.
- Stop if a schema migration would make existing v1 files unreadable, silently reinterpret existing records, or require destructive rewriting without a separately approved migration contract.
- Stop if implementation requires transcript access, a new automatic hook event, network activity, external publication, installation, deployment, or modification outside this repository.
- Stop and return architecture decisions to root if relation activation, lifecycle transitions, evidence authority, or dynamic safety limits cannot be implemented within the approved contract.

## Pending List

- Current Work: Done.
- The approved and implemented contract is `docs/P0_EXPERIENCE_GOVERNANCE_REQUIREMENTS.zh-CN.md`; lifecycle changes require a new immutable candidate and explicit review.
- No architecture, implementation, review, or verification blocker remains.
- Deferred by contract: Hub, automatic promotion or mutation, Capsule/Event, replay/shadow, transcript-derived signals, OpenViking writes, installation, merge, push, release, and deployment.
- Exact Next Action: None.

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
