# Final Livestock Rename Rollout

## Purpose
Move from cow-specific naming to livestock naming with a migration-safe rollout, while keeping the current system operational.

## Guiding Rules
- Do not rename the physical database table until compatibility layers are in place and validated.
- Keep `cows` as the storage model until the final cutover.
- Prefer new livestock-facing APIs, services, and repository aliases over in-place breaking renames.
- Preserve all existing endpoints during transition.

## Phase 1: Alias-First Compatibility
- Internal variables in business logic use livestock-facing names.
- Existing cow-backed repositories remain the storage source.
- Alias modules exist for livestock-facing and staff-facing naming.
- Existing routes continue to work alongside alias routes.

## Phase 2: Internal API Cleanup
- Rename parameters and local variables from cow-specific names to livestock-specific names where call sites are already compatible.
- Keep route contracts stable for external clients.
- Update tests to exercise both naming paths.

## Phase 3: Data Access Bridge
- Add a repository layer or model adapter that treats `cows` as the canonical persistence table.
- If desired, add a read-only `livestock` view or ORM mapping for reporting.
- Ensure foreign keys and relationships are resolved through the compatibility layer.

## Phase 4: Physical Rename Cutover
- Schedule a maintenance window.
- Create a migration like:
	- `op.rename_table('cows', 'livestock')`
	- recreate indexes and foreign keys for `dam_id`, `milk_logs`, `medical_records`, `lactation_cycles`, and `breeding_logs`
	- update any hard-coded table names in migrations or raw SQL
- Ship code that still understands both names during the rollout window.
- Validate the application against the renamed schema before removing compatibility aliases.

## Draft Alembic Cutover Shape
1. Confirm there are no new writes landing on old cow-only paths.
2. Run a migration that renames the table and reapplies dependent constraints.
3. Keep repository aliases pointing to the new `livestock` naming layer.
4. Leave compatibility properties and routes in place for one release cycle.
5. Remove legacy aliases only after production verification.

## Rollout Checklist
1. All tests pass with alias routes enabled.
2. New livestock/staff aliases are adopted in new code.
3. Monitoring confirms no remaining dependency on cow-only naming.
4. Perform the rename migration.
5. Remove legacy cow aliases after a stabilization period.

## Recommendation
If there is no business requirement for a literal table rename, keep `cows` as the storage model and use the compatibility layer indefinitely. That is the lowest-risk option and aligns best with SRP and backward compatibility.
