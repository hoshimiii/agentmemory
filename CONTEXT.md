# Context

## State
- M0 hook-only baseline is at commit `8875076`.
- `codex/m1-core-contract` passed independent Terra acceptance.
- The dual-layer storage/validation direction remains: strict runtime canonical checks remain authoritative while JSON Schema mirrors enforceable constraints.
- M1 work covers:
  - canonical JSON, UTF-8 byte checks, and integrity hash enforcement in runtime.
  - strict `schema_version` and `integrity.version` integer typing (bool rejected).
  - bounded, deterministic `applies_to.head` and `applies_to.branch` validation.
  - shared runtime bounds for `branch`, `paths`, `provenance` fields, and timestamps.
  - schema extension marker for required runtime-only validation items and schema/runtime drift checks.
- OpenViking is unavailable in this environment, so no OpenViking-specific integrations are in scope.
- Remaining deferrals: no additional contract changes beyond v1 runtime/schema enforcement or platform-host trust checks.
- Next action is to archive M1 in Git, branch M2, and implement the local store/init/CLI foundation.
