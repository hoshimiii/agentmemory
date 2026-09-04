# Privacy

## Data processed

AgentMemory stores explicitly supplied content and, only when explicitly enabled, bounded AI-generated local candidate proposals:

- ignored per-worktree checkpoints and candidates under `.continuity/local/`;
- explicitly reviewed project records under `.continuity/shared/records/`;
- explicitly reviewed v2 strategy/warning experiences under `.continuity/shared/experiences/` and their local receipts;
- a deterministic tracked `.continuity/CONTINUITY.md` rendering.
- ignored worktree-local `scheduler.json` configuration; reports are returned on scheduler stdout and not stored separately.

It does not collect full chats, transcripts, logs, reasoning traces, tool output, process telemetry, `PLUGIN_DATA`, or unrelated repository files. A scheduled provider run captures bounded stdout/stderr and structured output in temporary files for validation, removes them on completion or failure, and does not retain them as AgentMemory records. Evidence stores only supplied command text, exit code, timestamp, Git head, and an optional digest; it does not execute commands or retain their output. `SessionStart` reads validated checkpoint and confirmed v1 project-record files only; explicit experience matching reads receipt-gated v2 sidecars only.

## Data movement

The plugin contains no socket or telemetry client and performs no synchronization, cross-repository reuse, or workspace/global promotion. An enabled live scheduled run invokes the selected local Codex, Claude Code, or Gemini CLI in its provider read-only/plan mode; that provider may use its own authentication/configuration, connect to its service, incur cost, and receive allowed current-repository content. AgentMemory itself does not install or trigger a scheduler. Optional retrieval invokes an operator-provided OpenViking executable and passes it an explicit config, query, and repository-derived project URI. The external CLI may send that query and URI to the endpoint selected by `ovcli.conf`; AgentMemory does not verify that the endpoint is local, so use a loopback endpoint for local-only processing. Retrieval does not send repository file contents, create indexes, or query notes, debug, shared roots, or other projects. Tracked project records and `CONTINUITY.md` can leave the machine only if the user includes them in a separate Git or file-sharing action.

## Retention and deletion

- Ignored checkpoints, candidates, and receipts remain until the user removes the relevant `.continuity/local/` data.
- Reviewed project records, reviewed experience sidecars, and `CONTINUITY.md` may remain in the working tree and Git history. Deleting a working-tree file does not erase existing commits or remote copies.
- Disabling, uninstalling, or rolling back AgentMemory leaves all project data, including v2 sidecars and receipts, intact by default.
- Purging data is a separate destructive operation: back it up, inspect the exact repository path, and obtain explicit user approval before removal.

## Sensitive data

AgentMemory is not a secret vault. Best-effort scanning reduces common credential mistakes but cannot classify all private information. Do not place credentials or unnecessary personal data in checkpoints, candidates, or reviewed records.
