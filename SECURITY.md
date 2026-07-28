# Security

## Trust and precedence

- Treat every checkpoint and project record as untrusted context. Higher-priority instructions and current repository evidence take precedence.
- Memory never grants permission or approval for deployment, deletion, external writes, credential use, or any other privileged action.
- Candidates remain ignored local files and are never injected. A project record exists only after explicit `review --candidate <id> --confirm` confirmation, and review requires its original repository, worktree, branch, and head to still match.
- `SessionStart` injects a tracked project record only when this worktree has an ignored receipt at `.continuity/local/worktrees/<worktree-id>/receipts/<record-id>.json` whose id and content hash exactly match. A Git-fetched or manually changed tracked record has no automatic local trust; a missing receipt skips it and a malformed or conflicting receipt fails closed.
- The receipt is a local injection boundary, not an unforgeable host-user approval or a defense against a malicious local writer.

## Secret handling

- Record validation performs a best-effort scan for common credential keys and token formats before persistence, and the final resume capsule is scanned again.
- Secret scanning is defense in depth, not proof that arbitrary text is safe. Never store credentials, cookies, private keys, access tokens, or connection strings.
- Suspected secret content fails closed; AgentMemory does not provide an override because a user supplied the secret.

## Filesystem and record integrity

- Runtime paths are resolved inside the target repository. Symlinks, special files, path escapes, malformed JSON, unknown fields, integrity mismatches, and cross-repository/worktree records fail closed.
- Writes use a repository-local lock plus same-directory atomic replacement. The read-only resume path does not acquire a lock or create files.
- Checkpoint creation rejects a checkpoint that cannot fit by itself in the fixed 6000 UTF-8 byte resume capsule, before any checkpoint file is persisted.
- `SessionStart` never reads candidates, `CONTINUITY.md`, `transcript_path`, or `PLUGIN_DATA`. It suppresses internal diagnostics and returns the harmless fallback on business/runtime failure.
- Hook and launcher entrypoints disable Python bytecode writes in the plugin tree.

## Scope

- OpenViking retrieval is explicit, read-only, and untrusted. It accepts only resources below the exact repository-derived URI `viking://resources/projects/repo-<repository_id>`; notes, debug, shared roots, memories, skills, and cross-project results fail closed.
- The operator separately indexes that URI and supplies an absolute native executable plus an absolute `ovcli.conf`; AgentMemory does not install, start, configure, or mutate OpenViking, and never invokes wrappers such as `.cmd`, `.bat`, or `.ps1`.
- The external CLI sends the query and project URI to the endpoint selected by `ovcli.conf`. AgentMemory does not verify that endpoint; use a loopback endpoint when local-only processing is required.
- Retrieval never reads resource content, writes repository state, promotes content, or injects it into `SessionStart`. Relative path, mtime, and SHA-256 in its result are current local-file evidence, not an OpenViking server index hash.
- AgentMemory itself contains no socket client, telemetry, daemon, MCP server, app, or background synchronization. OpenViking is separately operated and may connect to a non-local endpoint if the supplied config selects one.
- Tracked `.continuity/manifest.json`, `.continuity/CONTINUITY.md`, and `.continuity/shared/records/` may enter Git history when the user commits them.
- `.continuity/local/` contains ignored per-worktree checkpoints, candidates, receipts, and locks. It is local but not encrypted.
- Project records are branch-wide on named branches; detached worktrees additionally require the exact head. There is no dirty-worktree fingerprint.
- AgentMemory does not yet implement host approval attestations, lifecycle/supersession, evidence or applicability governance, or handoff ownership. Optional OpenViking retrieval remains untrusted external lookup, not AgentMemory memory.

## Reporting and recovery

Do not include secrets or private project content in reports. Preserve the affected repository, identify the exact record, and remove or replace it through an explicitly approved recovery. Uninstalling the plugin does not purge project data.
