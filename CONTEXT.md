# Context

## State
- M0 hook-only baseline is at commit `8875076`.
- M1 core-contract passed independent Terra acceptance and is committed as `9f9290d`.
- M2 local checkpoint storage passed independent Terra acceptance and is committed as `2c7ec8e`.
- Current focus: `codex/m3-reviewed-memory-render`.
- M3 goal: add local candidate proposal, explicit user-confirmed project records, and deterministic project-memory rendering.
- M3 non-goals: hooks, resume capsules, skills, plugin changes, global/workspace promotion, OpenViking, MCP/daemon/UI, transcript parsing, automatic candidate capture, or automatic promotion.
- M3 constraints and acceptance:
  - Candidates remain under ignored per-worktree local storage and never render or inject.
  - `review --candidate <id> --confirm` is the only CLI project-write path; it preserves the candidate and is deterministic and idempotent.
  - Project records are strict M1 tracked shared records with candidate branch identity and explicit-user provenance.
  - `CONTINUITY.md` contains only valid confirmed records for the current repository and branch, in deterministic order.
  - Malformed, unknown, cross-repository, symlinked, or special shared entries fail closed without replacing the continuity file.
  - M2 guarantees remain unchanged.
- The dual-layer storage/validation direction remains: strict runtime canonical checks remain authoritative while JSON Schema mirrors enforceable constraints.
- M1 contract continues to hold: canonical JSON, UTF-8 checks, integrity enforcement, and schema-version/type bounds.
- M3 acceptance evidence: root and independent Terra reviews passed; both Python runners passed 64 tests with two Windows FIFO capability skips, plus compile, Python 3.9 AST, plugin validation, fail-closed, idempotence, branch, and leakage checks.
- Next action: archive M3 in Git, create `codex/m4-continuity-hooks`, and implement bounded SessionStart/PreCompact continuity behavior.
