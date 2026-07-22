# AgentMemory M0 Plugin

## Scope
- Implement M0-level plugin packaging and hook contracts only.
- Expose no skill execution, no MCP servers, no memory persistence, no transcript parsing, and no PLUGIN_DATA file operations.

## Files
- `.codex-plugin/plugin.json` with minimal valid manifest metadata.
- `hooks/hooks.json` with SessionStart and PreCompact matcher wiring.
- `hooks/agentmemory_hook.py` dispatcher enforcing strict action/event contracts.
- `tests/fixtures/*` and `tests/test_hook_contract.py` for contract validation.

## Commands
- Validate plugin manifest:
  - `uv run --with pyyaml python C:\Users\ADMIN\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .`
- Run tests:
  - `py -3 -m unittest discover -s tests -v`
- Manual hook smoke checks:
  - `Get-Content tests/fixtures/session-startup.json | py -3 hooks/agentmemory_hook.py session-start`
  - `Get-Content tests/fixtures/precompact-auto.json | py -3 hooks/agentmemory_hook.py pre-compact`

## Trust and loading status
- Installed-host trust and runtime loading verification are still pending.
