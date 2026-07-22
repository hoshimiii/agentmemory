# Context

## State
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
- Next action: run the final verification matrix, archive M4 on its branch, then begin M5 packaging, public skill, documentation, and end-to-end acceptance.
