# Context

## State
- M0 hook-only baseline is at commit `8875076`.
- M1 core-contract passed independent Terra acceptance and is committed as `9f9290d`.
- Current focus: `codex/m2-local-store-cli` (M2 accepted by independent Terra review).
- M2 scope in this branch is limited to local checkpoint persistence and CLI scaffolding:
  - stdlib-only local checkpoint storage (`agentmemory/storage.py`, `agentmemory/locking.py`).
  - minimal CLI (`agentmemory/cli.py`, `agentmemory/__main__.py`).
  - scaffold persistence and status behavior in `tests/test_storage_cli.py`.
  - no hook changes, no skill/manifest updates, no MCP/daemon, no candidate/project persistence, no resume capsule logic.
  - no PLUGIN_DATA or transcript parsing in storage paths.
- The dual-layer storage/validation direction remains: strict runtime canonical checks remain authoritative while JSON Schema mirrors enforceable constraints.
- M1 contract continues to hold: canonical JSON, UTF-8 checks, integrity enforcement, and schema-version/type bounds.
- M2 acceptance evidence: 53 tests passed with one Windows FIFO capability skip; compile, Python 3.9 AST grammar, plugin validation, symlink/conflict, and CLI leakage checks passed.
- Next action: archive M2 in Git, create `codex/m3-reviewed-memory-render`, and implement candidate review plus deterministic project-memory rendering.
