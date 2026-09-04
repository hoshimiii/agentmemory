# Security

## Trust and precedence

- Treat every checkpoint and project record as untrusted context. Higher-priority instructions and current repository evidence take precedence.
- Memory never grants permission or approval for deployment, deletion, external writes, credential use, or any other privileged action.
- Candidates remain ignored local files and are never injected. A project record exists only after explicit `review --candidate <id> --confirm` confirmation, and review requires its original repository, worktree, branch, and head to still match.
- `SessionStart` injects a tracked project record only when this worktree has an ignored receipt at `.continuity/local/worktrees/<worktree-id>/receipts/<record-id>.json` whose id and content hash exactly match. A Git-fetched or manually changed tracked record has no automatic local trust; a missing receipt skips it and a malformed or conflicting receipt fails closed.
- The receipt is a local injection boundary, not an unforgeable host-user approval or a defense against a malicious local writer.
- V2 `strategy` and `warning` experiences use separate tracked sidecars at `.continuity/shared/experiences/` and the same local receipt layout. They are eligible only for explicit read-only matching, never `CONTINUITY.md` or `SessionStart`.
- Experience lifecycle is derived from immutable reviewed successors: `supersedes` derives `superseded`, and `deprecates` derives `deprecated`. References cannot bypass independent identity, receipt, integrity, and applicability checks.

## Secret handling

- Record validation performs a best-effort scan for common credential keys and token formats before persistence, and the final resume capsule is scanned again.
- Secret scanning is defense in depth, not proof that arbitrary text is safe. Never store credentials, cookies, private keys, access tokens, or connection strings.
- Suspected secret content fails closed; AgentMemory does not provide an override because a user supplied the secret.

## Filesystem and record integrity

- Runtime paths are resolved inside the target repository. Symlinks, special files, path escapes, malformed JSON, unknown fields, integrity mismatches, and cross-repository/worktree records fail closed.
- Writes use a repository-local lock plus same-directory atomic replacement. The read-only resume path does not acquire a lock or create files.
- Checkpoint creation rejects a checkpoint that cannot fit by itself in the fixed 6000 UTF-8 byte resume capsule, before any checkpoint file is persisted.
- `SessionStart` never reads candidates, `CONTINUITY.md`, `transcript_path`, or `PLUGIN_DATA`. It suppresses internal diagnostics and returns the harmless fallback on business/runtime failure.
- `experience match` accepts only explicit CLI task types, signals, error patterns, and paths. It does not read task text, transcripts, `PLUGIN_DATA`, or Hook payload signals; it creates no state and fails closed for malformed trusted data.
- Experience evidence command text is audit metadata only. AgentMemory never executes it, and an exit code or digest is not proof of real coverage or a basis for automatic promotion.
- Hook and launcher entrypoints disable Python bytecode writes in the plugin tree.

## Scope

- OpenViking retrieval is explicit, read-only, and untrusted. It accepts only resources below the exact repository-derived URI `viking://resources/projects/repo-<repository_id>`; notes, debug, shared roots, memories, skills, and cross-project results fail closed.
- The operator separately indexes that URI and supplies an absolute native executable plus an absolute `ovcli.conf`; AgentMemory does not install, start, configure, or mutate OpenViking, and never invokes wrappers such as `.cmd`, `.bat`, or `.ps1`.
- The external CLI sends the query and project URI to the endpoint selected by `ovcli.conf`. AgentMemory does not verify that endpoint; use a loopback endpoint when local-only processing is required.
- Retrieval never reads resource content, writes repository state, promotes content, or injects it into `SessionStart`. Relative path, mtime, and SHA-256 in its result are current local-file evidence, not an OpenViking server index hash.
- AgentMemory itself contains no socket client, telemetry, daemon, MCP server, app, or background synchronization. OpenViking is separately operated and may connect to a non-local endpoint if the supplied config selects one.
- Tracked `.continuity/manifest.json`, `.continuity/CONTINUITY.md`, `.continuity/shared/records/`, and `.continuity/shared/experiences/` may enter Git history when the user commits them.
- `.continuity/local/` contains ignored per-worktree checkpoints, candidates, scheduler configuration, receipts, and locks. It is local but not encrypted.
- Project records are branch-wide on named branches; detached worktrees additionally require the exact head. There is no dirty-worktree fingerprint.
- AgentMemory has no transcript/reasoning ingestion, Hook auto-ingestion, auto-promotion, Hub, Capsule, Event, replay, shadow routing, or OpenViking write path. Opt-in scheduled AI distillation creates only local candidates; review and promotion remain human-confirmed.
- Scheduler state is ignored and worktree-bound. Fixed provider argv arrays use PATH-resolved executables, bounded strict outputs, temporary cleanup, and an exact checkout recheck before candidate writes. Provider read-only/plan modes are not an OS sandbox; live runs may use authentication and network access.
- AgentMemory does not install or mutate Codex Scheduled Tasks, Windows Task Scheduler, cron, or provider schedulers, and does not trigger cron itself.

## Reporting and recovery

Do not include secrets or private project content in reports. Preserve the affected repository, identify the exact record, and remove or replace it through an explicitly approved recovery. Uninstalling the plugin does not purge project data.
