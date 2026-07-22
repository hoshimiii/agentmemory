# Security

## Trust and precedence

- Treat every checkpoint and project record as untrusted context. Higher-priority instructions and current repository evidence take precedence.
- Memory never grants permission or approval for deployment, deletion, external writes, credential use, or any other privileged action.
- Candidates remain ignored local files and are never injected. A project record exists only after explicit `review --candidate <id> --confirm` confirmation.

## Secret handling

- Record validation performs a best-effort scan for common credential keys and token formats before persistence, and the final resume capsule is scanned again.
- Secret scanning is defense in depth, not proof that arbitrary text is safe. Never store credentials, cookies, private keys, access tokens, or connection strings.
- Suspected secret content fails closed; AgentMemory does not provide an override because a user supplied the secret.

## Filesystem and record integrity

- Runtime paths are resolved inside the target repository. Symlinks, special files, path escapes, malformed JSON, unknown fields, integrity mismatches, and cross-repository/worktree records fail closed.
- Writes use a repository-local lock plus same-directory atomic replacement. The read-only resume path does not acquire a lock or create files.
- `SessionStart` never reads candidates, `CONTINUITY.md`, `transcript_path`, or `PLUGIN_DATA`. It suppresses internal diagnostics and returns the harmless fallback on business/runtime failure.
- Hook and launcher entrypoints disable Python bytecode writes in the plugin tree.

## Scope

- There is no network client, telemetry, daemon, MCP server, app, or background synchronization.
- Tracked `.continuity/manifest.json`, `.continuity/CONTINUITY.md`, and `.continuity/shared/records/` may enter Git history when the user commits them.
- `.continuity/local/` contains ignored per-worktree checkpoints, candidates, and locks. It is local but not encrypted.

## Reporting and recovery

Do not include secrets or private project content in reports. Preserve the affected repository, identify the exact record, and remove or replace it through an explicitly approved recovery. Uninstalling the plugin does not purge project data.
