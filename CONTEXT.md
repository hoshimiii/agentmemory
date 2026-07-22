# Context

## Objective
Deliver the M0 hook-only implementation for AgentMemory with strict SessionStart and PreCompact contract behavior.

## State
- `plugin.json` is set to a minimal, validator-compliant manifest.
- Hook dispatch is implemented in a single Python file.
- Hook wiring and fixtures are present.
- Unit tests cover success paths and failure modes, including matcher/command/timeout contract checks.

## Decisions
- No plugin `hooks`, `skills`, `apps`, or `mcpServers` fields are present in `plugin.json`.
- Dispatcher is intentionally minimal and refuses unknown actions and event mismatches.
- `PLUGIN_DATA` is never read or written.

## Verification
- `validate_plugin.py`
- `tests/test_hook_contract.py` with unittest discovery
- Fixture-based stdin checks for startup, compact, and precompact
- Error-case tests for invalid JSON, non-object input, unknown action, and mismatch

## Next Action
Run the local installed-host trust/loading check with explicit authorization for this environment, then run the verification commands.
