# Context

## Current Brief

This turn's only goal: add a project-scoped, read-only OpenViking knowledge retrieval boundary on top of the accepted M6 AgentMemory trust model.

### Deliverables

- Derive or require one stable OpenViking project URI for the current Git repository; never search a shared projects root implicitly.
- Require every knowledge query to carry that exact project URI and return bounded source provenance sufficient to identify the originating URI and local source when OpenViking exposes it.
- Keep retrieved knowledge untrusted and read-only. It must never create, confirm, promote, or inject an AgentMemory checkpoint/project record without the existing explicit candidate and `review --confirm` path.
- Keep global `notes` and `debug` collections outside the project retrieval command; no cross-domain fallback.
- Add focused tests and accurate plugin/CLI documentation without weakening M6 receipt, identity, secret, or byte-budget checks.

### Non-goals

- No browser-extension changes or browser-memory integration.
- No OpenViking daemon, vector database, indexing implementation, automatic repository scan, global/workspace memory, MCP/app/UI, cloud sync, or mutation of `E:\OpenVikingKB`.
- No automatic query at `SessionStart`, no transcript/tool-output access, and no automatic memory promotion.
- No installation, remote push, deployment, or modification of monitored project files outside this repository.

### Settled Contracts

- The exact project root is `viking://resources/projects/repo-<repository_id>`, derived from the existing Git common-directory identity. Human-readable or shared-root URI overrides are not accepted.
- Add one explicit read-only `retrieve` CLI command. It uses an absolute native OpenViking executable path plus an explicit absolute `ovcli.conf`, invokes subprocesses without a shell, performs `health`, then searches only the derived root with `level=2` and `context_type=resource`.
- Returned candidates are bounded, marked untrusted, and restricted to strict descendants of the derived root. Any memory/skill/cross-domain result fails the entire operation.
- Provenance reports the exact OpenViking URI and server `modTime`; local source path, current modification time, and current SHA-256 may be reported only after a safe repo-relative mapping and regular-file validation, explicitly labeled as current local evidence rather than an OpenViking index hash.
- Retrieval does not call `read`, import AgentMemory storage/render/hooks, require AgentMemory initialization, or create any repository state.

### File and Phase Scope

- Investigation: current CLI, identity/storage/render/hook boundaries, package metadata, tests, and the installed OpenViking CLI contract.
- Implementation is limited to a new `agentmemory/openviking.py`, the `retrieve` CLI surface, the shared Git identity decoder needed for non-ASCII repositories, focused retrieval tests, the public skill, and accurate README/security/privacy/package descriptions. Do not modify hooks, record schemas, storage layout, receipts, or rendering.
- Work is isolated on `codex/m7-project-scoped-openviking`, based on M6 commit `8c1d0a95b004a78bb82f3871aea78e84bf2c0fef`.

### Acceptance

- Existing M6 test suites remain green.
- New tests prove exact project-URI enforcement, rejection of shared/global/domain-crossing URIs, bounded provenance, read-only failure behavior, and no AgentMemory state writes during retrieval.
- Missing/unhealthy/malformed OpenViking fails closed without blocking ordinary AgentMemory status/checkpoint/resume behavior.
- Git identity preserves non-ASCII repository paths so the deterministic URI works in this checkout.
- `compileall`, Python 3.9 AST parsing, JSON parsing, skill/plugin validation, and `git diff --check` pass.

### Stop Conditions

- Stop and return to root if implementation requires an OpenViking server/config mutation, a new automatic hook event, a schema compatibility break, credential access, external publication, or weakening the M6 confirmation boundary.
- Stop if the project URI cannot be bound to the current Git repository without an unresolved product decision.

## Pending List

- No code blocker remains. External indexing is intentionally operator-owned; the current deterministic project URI is healthy but has no indexed resources, so live retrieval correctly returns an empty result.

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
