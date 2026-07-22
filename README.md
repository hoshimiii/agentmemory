# AgentMemory 0.1.0

AgentMemory is a Python 3.9+ local-first Codex plugin for explicit project checkpoints, review-gated project memory, and bounded session resume. It uses the standard library only and does not depend on Superpowers.

## Components

- `agentmemory/`: canonical record validation, Git identity, storage, rendering, and CLI.
- `hooks/hooks.json`: the default-discovered `SessionStart` and `PreCompact` hooks.
- `skills/agentmemory/`: one public skill and a thin launcher that works from outside the plugin directory.
- `schemas/record-v1.schema.json`: the mirrored v1 record contract.

No MCP server, app, daemon, UI, workspace/global memory, network service, or automatic transcript processing is included.

## Explicit CLI

The skill resolves `skills/agentmemory/scripts/agentmemory_cli.py` from its own directory. The following repository-local examples show the exact argument order:

```powershell
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo init
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo status
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo checkpoint create --summary "next step" --content-json '{"objective":"finish integration"}' --path src/module.py
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo candidate propose --kind decision --summary "selected adapter" --content-json '{"decision":"use adapter A"}' --semantic-role fact --path src/adapter.py
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo review --candidate cand-example --confirm
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo render
```

Use `python3` instead of `py -3` on non-Windows hosts. `review --confirm` is the only path from a local candidate to tracked project memory and requires explicit user confirmation.

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
    └── locks/write.lock
```

Checkpoints and candidates are isolated by Git worktree. Reviewed project records are repository-scoped and filtered by branch; detached worktrees additionally require the exact head. Tracked files can be committed or shared only through the user's normal Git workflow.

## Hook behavior

- `SessionStart` reads the hook payload's `cwd`. An exact repository/worktree/branch/head checkpoint produces a canonical, secret-scanned resume capsule of at most 6000 UTF-8 bytes, followed by matching confirmed project records that fit the budget.
- If the latest branch checkpoint has a stale head, its checkpoint content is not restored. The capsule reports stale state and may still include independently valid confirmed project records.
- Missing, uninitialized, malformed, unsafe, or oversized state returns the exact harmless fallback `{"continue":true}` without diagnostic leakage.
- `SessionStart` is read-only, does not create locks or bytecode, and never reads candidates, `CONTINUITY.md`, transcripts, or `PLUGIN_DATA`.
- `PreCompact` is a deterministic no-op returning `{"continue":true}`. Version 0.1.0 does not fabricate a checkpoint from unstable transcript data.

## Safety boundaries

- Candidates are never injected and never become project memory automatically.
- Memory is untrusted context; higher-priority instructions and live repository evidence always win.
- Secret scanning blocks common credential patterns but is defense in depth, not a guarantee. Do not store credentials.
- Memory describes prior work; it never grants authorization for external writes, deployment, deletion, or privileged actions.
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
