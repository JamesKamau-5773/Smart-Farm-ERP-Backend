# Livestock Rename Migration Plan

## Goal
Move the codebase from cow-specific naming toward livestock-facing naming without breaking existing API consumers, storage, or tests.

## Current State
- Storage remains on `cows`.
- New compatibility aliases now exist for livestock-facing routes and services.
- Existing cow routes continue to work.
- New livestock route aliases also work.

## Phase 1: Compatibility Layer
- Keep `cows` as the physical database table.
- Use `LivestockRepository` and `LivestockService` aliases in transition code.
- Support both route families:
  - `/api/operations/cows/...`
  - `/api/operations/livestock/...`
  - `/api/clinical/cows/...`
  - `/api/clinical/livestock/...`
- Keep all current tests green.

## Phase 2: Domain Naming Cleanup
- Gradually rename variables, function parameters, and response payloads to use livestock terms.
- Keep method signatures backward-compatible where practical.
- Introduce new repository/service names in new code paths first.

## Phase 3: Data Model Bridge
- Add a database view or repository mapping layer if the application needs `livestock` as a logical name while storage stays on `cows`.
- Only introduce physical rename/migration if there is a clear cutover window.

## Phase 4: Optional Physical Rename
- Rename `cows` to `livestock` only after all callers have moved.
- Add migration scripts for:
  - table rename
  - foreign key updates
  - relationship refactors
  - test fixture updates
- Preserve backward compatibility during deployment with a staged rollout.

## Recommended Order
1. Keep compatibility aliases active.
2. Migrate internal naming in services and repositories.
3. Update tests and docs.
4. Decide whether a physical rename is worth the operational risk.

## Notes
- If a physical rename is not required for product reasons, keeping `cows` as storage is safer and simpler.
- The current codebase already reflects the compatibility-first approach.
