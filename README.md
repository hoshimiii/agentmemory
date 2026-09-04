# AgentMemory 0.1.1

AgentMemory is a Python 3.9+ local-first Codex plugin for explicit project checkpoints, review-gated project memory, bounded session resume, and explicit task-scoped experience lookup. It uses the standard library only and does not depend on Superpowers.

## Components

- `agentmemory/`: canonical record validation, Git identity, storage, rendering, and CLI.
- `hooks/hooks.json`: the default-discovered `SessionStart` and `PreCompact` hooks.
- `skills/agentmemory/`: one public skill and a thin launcher that works from outside the plugin directory.
- `schemas/record-v1.schema.json`: the mirrored v1 record contract.
- `schemas/experience-v2.schema.json`: the separate v2 strategy/warning experience contract.

No MCP server, app, daemon, UI, workspace/global memory, cloud service, telemetry, upload, or automatic transcript processing is included. OpenViking retrieval is an optional separately operated external process.

## Explicit CLI

The skill resolves `skills/agentmemory/scripts/agentmemory_cli.py` from its own directory. The following repository-local examples show the exact argument order:

```powershell
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo init
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo status
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo checkpoint create --summary "next step" --content-json '{"objective":"finish integration"}' --path src/module.py
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo candidate propose --kind decision --summary "selected adapter" --content-json '{"decision":"use adapter A"}' --semantic-role fact --path src/adapter.py
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo review --candidate cand-example --confirm
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo candidate propose --kind strategy --summary "repair a receipt mismatch" --content-json '{"body":"Check the record id and content hash before resuming."}' --experience-json '{"applicability":{"task_types":["bugfix"],"signals":["memory.receipt"],"error_patterns":[]},"evidence":{"checks":[{"command":"py -3 -m unittest discover -s tests -p test_memory_review.py -v","exit_code":0,"observed_at":"2026-07-29T12:00:00Z","git_head":"UNBORN","result_digest":null}]},"lineage":{"supersedes":[],"deprecates":[]},"relation":{"strategy_id":null}}'
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo experience match --task-type bugfix --signal memory.receipt --path agentmemory/storage.py --max-bytes 8192
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo render
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo retrieve --query "find source" --openviking-cli C:\OpenViking\ov.exe --openviking-config C:\OpenViking\ovcli.conf --limit 3
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule configure --provider codex --model gpt-5.6-terra --cron "0 3 * * *" --timezone local --reasoning-effort medium
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule configure --provider claude --model claude-sonnet-4 --cron "30 2 * * *" --timezone Asia/Tokyo
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule configure --provider gemini --model gemini-2.5-pro --cron "0 4 * * 1-5" --enable
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule enable
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule disable
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule status
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule plan
py -3 skills/agentmemory/scripts/agentmemory_cli.py --repo C:\path\to\repo schedule run --dry-run
```

Use `python3` instead of `py -3` on non-Windows hosts. `schedule configure` and `schedule enable` require explicit authorization and configure is disabled unless `--enable` is supplied. Once enabled, an outer scheduler may call `schedule run` only to create local candidates; it interprets cron/timezone and captures the JSON stdout report. AgentMemory never installs or mutates Codex Scheduled Tasks, Windows Task Scheduler, cron, or a provider scheduler, and does not trigger cron itself. `review --confirm` remains the only path to tracked project memory and always needs later immediate human confirmation.

Live provider runs may connect using the selected tool's auth/configuration and incur cost. Fixed Codex, Claude Code, and Gemini argv adapters use provider read-only/plan mode, which is not an OS sandbox. Outputs are bounded and strict, temporary files are cleaned up, and checkout identity is rechecked before candidate-only writes. The run never reads transcripts, `PLUGIN_DATA`, OpenViking, platform memory, or other projects; it never writes review receipts, shared records, experiences, or `CONTINUITY.md`.

There are three separate layers: v1 continuity tracks checkpoints and confirmed project facts for bounded `SessionStart`; v2 experience stores explicitly reviewed `strategy` and `warning` records for an explicit `experience match`; OpenViking is a separately operated, read-only lookup. Experience matching is deterministic, read-only, and untrusted: it accepts only explicit task types, signals, error patterns, and paths, never infers task text or reads transcripts, `PLUGIN_DATA`, or Hook payload task data. Evidence metadata records command text, exit code, time, Git head, and optional digest; it never executes commands and is not proof of coverage or promotion.

`retrieve` is an explicit, read-only, untrusted external lookup. It does not require `init`, write repository state, promote content into AgentMemory, or inject anything into `SessionStart`. The repository Git identity determines the only allowed OpenViking root: `viking://resources/projects/repo-<repository_id>`. Notes, debug, shared roots, and other projects are rejected; there is no fallback.

The operator must separately index the current repository under that exact URI and provide both an absolute native OpenViking executable (not `.cmd`, `.bat`, or `.ps1`) and an absolute `ovcli.conf` path. AgentMemory passes that config through `OPENVIKING_CLI_CONFIG_FILE`; it does not install, start, configure, or mutate OpenViking and never creates the index. The external CLI sends the query and project URI to the endpoint selected by that config. Use a loopback endpoint for local-only operation; AgentMemory does not verify that endpoint. Returned relative path, mtime, and SHA-256 are checked against the current local file; the SHA-256 is not an OpenViking server-index hash. Run retrieval only when explicitly requested or needed for the user's task.

## Repository data

`init` creates the following project layout and adds the exact `.continuity/local/` ignore line:

```text
.continuity/
├── manifest.json                         # tracked contract
├── CONTINUITY.md                         # tracked deterministic rendering
├── shared/records/*.json                 # tracked reviewed project records
├── shared/experiences/*.json             # tracked reviewed v2 strategy/warning records
└── local/                                # ignored
    ├── worktrees/<worktree-id>/checkpoints/*.json
    ├── worktrees/<worktree-id>/candidates/*.json
    ├── worktrees/<worktree-id>/receipts/<record-id>.json # v1/v2 local trust receipts
    ├── worktrees/<worktree-id>/scheduler.json           # ignored opt-in configuration
    └── locks/write.lock
```

Checkpoints, candidates, and review receipts are isolated by Git worktree. Reviewed project records are repository-scoped and filtered by branch; detached worktrees additionally require the exact head. A `SessionStart` capsule includes a v1 project record only when this worktree's receipt has the same record id and integrity content hash. V2 experiences never enter `CONTINUITY.md`, `load_resume_state()`, or `SessionStart`; they require an explicit match and their own matching receipt. A record obtained through Git or changed by hand therefore does not automatically gain local trust; it needs another explicit review of the original, still exact-context candidate. Tracked files can be committed or shared only through the user's normal Git workflow.

V2 records are immutable. A reviewed successor derives an older same-kind record as `superseded`; a reviewed deprecator derives a target as `deprecated`. No record is edited, reactivated, or deleted by this lifecycle. A match begins at 8192 bytes, adds 2048 bytes per activated strategy-warning relationship, and caps at 24576 bytes; `--max-bytes` can only lower that effective budget. The 6000-byte `SessionStart` capsule is unchanged.

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
- Experience match output is untrusted, explicit, and read-only; it cannot auto-review, auto-promote, execute evidence commands, or enter a resume capsule.
- This release has no transcript processing, Hook auto-ingestion, automatic promotion, Hub, Capsule, Event, replay, or shadow-routing feature. Opt-in AI distillation creates only local candidates.
- See [SECURITY.md](SECURITY.md) and [PRIVACY.md](PRIVACY.md).

## Validation

```powershell
py -3 -m unittest discover -s tests -v
py -3 C:\Users\ADMIN\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/agentmemory
py -3 C:\Users\ADMIN\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .
```

The test suite validates the runtime and package from source without installing or trusting the plugin in a live Codex host.

## Rollback and retention

Each milestone is archived on a separate Git branch. Reverting the plugin code does not delete `.continuity` data, including `shared/experiences/` and local receipts. Removing or disabling the plugin also leaves project data intact; back up and remove `.continuity` separately only when the user explicitly wants to purge it.

Installed-host loading and Hook trust remain a separate approval gate. This repository does not claim that gate has been completed.
