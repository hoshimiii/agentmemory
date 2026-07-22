# Privacy

## Data processed

AgentMemory stores only content supplied through explicit CLI operations:

- ignored per-worktree checkpoints and candidates under `.continuity/local/`;
- explicitly reviewed project records under `.continuity/shared/records/`;
- a deterministic tracked `.continuity/CONTINUITY.md` rendering.

It does not collect full chats, transcripts, tool output, process telemetry, `PLUGIN_DATA`, or unrelated repository files. `SessionStart` reads validated checkpoint and confirmed project-record files only.

## Data movement

The plugin contains no network or telemetry code and performs no upload, synchronization, cross-repository reuse, or workspace/global promotion. Tracked project records and `CONTINUITY.md` can leave the machine only if the user includes them in a separate Git or file-sharing action.

## Retention and deletion

- Ignored checkpoints and candidates remain until the user removes the relevant `.continuity/local/` data.
- Reviewed project records and `CONTINUITY.md` may remain in the working tree and Git history. Deleting a working-tree file does not erase existing commits or remote copies.
- Disabling, uninstalling, or rolling back AgentMemory leaves all project data intact by default.
- Purging data is a separate destructive operation: back it up, inspect the exact repository path, and obtain explicit user approval before removal.

## Sensitive data

AgentMemory is not a secret vault. Best-effort scanning reduces common credential mistakes but cannot classify all private information. Do not place credentials or unnecessary personal data in checkpoints, candidates, or reviewed records.
