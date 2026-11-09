ZZLab new-element package template

1. Replace every TODO. package-template sets the current base catalog SHA.
2. Add authoritative JSON records under records/. Their exact runtime shape is defined by library/schemas/.
3. For kits explicitly declare layout.opticalType. Unknown optical behavior = unsupported; unresolved geometry = placementAllowed false. Never invent dimensions to pass validation.
4. Place assets inside this package, declare root/path/source/SHA in package.json. Targets preserve existing application URLs. Replacements need exact previous SHA.
5. Provide four named review declarations and hashed files under evidence/. These are reviewer declarations, not tool certification.
6. stage PACKAGE is read-only. stage PACKAGE --output NEW_DIR creates an isolated candidate. Review its catalog, diagrams, BOM and evidence.
7. adopt STAGE is read-only; adopt STAGE --apply updates LOCAL source/assets with backup and rollback. It does not change runtime catalog or deploy.
8. build --write, run relevant tests, then use the project deployment workflow.

To revise an existing record, set mode=replace and previousSha256 to the canonical record file SHA. Keep its ID stable. Do not use import-existing after bootstrap.
