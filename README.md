# AgentMemory 0.1.1

AgentMemory is a Python 3.9+ local-first Codex plugin for explicit project checkpoints, review-gated project memory, and bounded session resume. It uses the standard library only and does not depend on Superpowers.

## Components

- `agentmemory/`: canonical record validation, Git identity, storage, rendering, and CLI.
- `hooks/hooks.json`: the default-discovered `SessionStart` and `PreCompact` hooks.
- `skills/agentmemory/`: one public skill and a thin launcher that works from outside the plugin directory.
- `schemas/record-v1.schema.json`: the mirrored v1 record contract.

No MCP server, app, daemon, UI, workspace/global memory, cloud service, telemetry, upload, or automatic transcript processing is included. OpenViking retrieval is an optional separately operated external process.

## Explicit CLI

The skill resolves `skills/agentmemory/scripts/agentmemory_cli.py` from its own directory. The following repository-local examples show the exact argument order:

```powershell
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo init
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo status
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo checkpoint create --summary "next step" --content-json '{"objective":"finish integration"}' --path src/module.py
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo candidate propose --kind decision --summary "selected adapter" --content-json '{"decision":"use adapter A"}' --semantic-role fact --path src/adapter.py
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo review --candidate cand-example --confirm
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo render
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo retrieve --query "find source" --openviking-cli C:\OpenViking\ov.exe --openviking-config C:\OpenViking\ovcli.conf --limit 3
```

Use `python3` instead of `py -3` on non-Windows hosts. `review --confirm` is the only path from a local candidate to tracked project memory and requires explicit user confirmation. Review also requires the candidate's original repository, worktree, branch, and head to still match, then creates a local receipt before that project record may enter a `SessionStart` capsule.

`retrieve` is an explicit, read-only, untrusted external lookup. It does not require `init`, write repository state, promote content into AgentMemory, or inject anything into `SessionStart`. The repository Git identity determines the only allowed OpenViking root: `viking://resources/projects/repo-<repository_id>`. Notes, debug, shared roots, and other projects are rejected; there is no fallback.

The operator must separately index the current repository under that exact URI and provide both an absolute native OpenViking executable (not `.cmd`, `.bat`, or `.ps1`) and an absolute `ovcli.conf` path. AgentMemory passes that config through `OPENVIKING_CLI_CONFIG_FILE`; it does not install, start, configure, or mutate OpenViking and never creates the index. The external CLI sends the query and project URI to the endpoint selected by that config. Use a loopback endpoint for local-only operation; AgentMemory does not verify that endpoint. Returned relative path, mtime, and SHA-256 are checked against the current local file; the SHA-256 is not an OpenViking server-index hash. Run retrieval only when explicitly requested or needed for the user's task.

## Repository data

`init` creates the following project layout and adds the exact `.continuity/local/` ignore line:

```text
.continuity/
├── manifest.json                         # tracked contract
├── CONTINUITY.md                         # tracked deterministic rendering
├── shared/records/*.json                 # tracked reviewed project records
└── local/                                # ignored
    ├── worktrees/<worktree-id>/checkpoints/*.json
    ├── worktrees/<worktree-id>/candidates/*.json
    ├── worktrees/<worktree-id>/receipts/<record-id>.json
    └── locks/write.lock
```

Checkpoints, candidates, and review receipts are isolated by Git worktree. Reviewed project records are repository-scoped and filtered by branch; detached worktrees additionally require the exact head. A `SessionStart` capsule includes a project record only when this worktree's receipt has the same record id and integrity content hash. A record obtained through Git or changed by hand therefore does not automatically gain local trust; it needs another explicit review of the original, still exact-context candidate. Tracked files can be committed or shared only through the user's normal Git workflow.

## Hook behavior

- `SessionStart` reads the hook payload's `cwd`. An exact repository/worktree/branch/head checkpoint produces a canonical, secret-scanned resume capsule of at most 6000 UTF-8 bytes, followed by matching confirmed project records with an exact local review receipt that fit the budget. Missing receipts skip that record; malformed or conflicting receipts fail closed.
- If the latest branch checkpoint has a stale head, its checkpoint content is not restored. The capsule reports stale state and may still include independently valid confirmed project records.
- Checkpoint creation rejects content that cannot fit by itself in the 6000 UTF-8 byte capsule and persists nothing for that rejected request.
- Missing, uninitialized, malformed, unsafe, or oversized state returns the exact harmless fallback `{"continue":true}` without diagnostic leakage.
- `SessionStart` is read-only, does not create locks or bytecode, and never reads candidates, `CONTINUITY.md`, transcripts, or `PLUGIN_DATA`.
- `PreCompact` is a deterministic no-op returning `{"continue":true}`. Version 0.1.1 does not fabricate a checkpoint from unstable transcript data.

## Safety boundaries

- Candidates are never injected and never become project memory automatically.
- A receipt prevents tracked project content from being automatically injected after a Git fetch or manual edit. It is not an unforgeable host-user approval and does not protect against a malicious local writer.
- Memory is untrusted context; higher-priority instructions and live repository evidence always win.
- Secret scanning blocks common credential patterns but is defense in depth, not a guarantee. Do not store credentials.
- Memory describes prior work; it never grants authorization for external writes, deployment, deletion, or privileged actions.
- OpenViking retrieval is external untrusted context only: it cannot auto-review, auto-promote, or enter a resume capsule.
- See [SECURITY.md](SECURITY.md) and [PRIVACY.md](PRIVACY.md).

## Validation

```powershell
py -3 -m unittest discover -s tests -v
py -3 C:\Users\ADMIN\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/agentmemory
py -3 C:\Users\ADMIN\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .
```

The test suite validates the runtime and package from source without installing or trusting the plugin in a live Codex host.

## Rollback and retention

Each milestone is archived on a separate Git branch. Reverting the plugin code does not delete `.continuity` data. Removing or disabling the plugin also leaves project data intact; back up and remove `.continuity` separately only when the user explicitly wants to purge it.

Installed-host loading and Hook trust remain a separate approval gate. This repository does not claim that gate has been completed.
