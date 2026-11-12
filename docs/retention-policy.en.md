# Retention policy

[中文](retention-policy.md)

Updated user agreement, 2026-11-12: keep the current engine implementation and active component definitions, and preserve superseded versions in `library/history` when the user explicitly selects retention for that update. This supersedes the earlier current-only component and historical-dependency deletion rules.

History includes immutable component/kit/board definitions, CAD, drawings, rendering, BOM dependencies and necessary supporting evidence. Preserve original IDs, revisions and source hashes, and freeze the required dependency closure. Content may be deduplicated with protected, resolvable references. Do not retain an entire library snapshot merely to preserve a few dependencies. For a retention update, keep uncertain dependencies pending review.

Historical instances remain resolvable and renderable in the current engine. Historical components are excluded from the placement palette and rejected by new-placement entry points. Loading an old design is not new placement. Active replacements remain available for new designs; never silently redirect an old identity to new geometry or upgrade saved projects.

Every replacement requires the user’s explicit retain/discard choice, recorded in the stage/adoption receipt. Ask if no choice was supplied; new packages with nothing to replace need no choice. Retain means archive and verify the previous definition and dependencies before adopting a replacement. Discard means skip archiving this replaced version without another confirmation; it does not authorize removing unrelated previously retained history or shared active dependencies. When retention was selected, preservation failure must prevent destructive replacement or cleanup. Check only changed files and directly affected compatibility; reuse existing geometric and manufacturing acceptance without upgrading its status.

Project history remains limited to deduplicated, confirmed engineering JSON milestones; retain current project deliverables as needed. Required historical component resources live under `library/history`, not in duplicated full project deliveries. Old engines, unrelated debug revisions and full library snapshots are not required.

History and its referenced assets are continuing dependencies, not caches or orphaned files. Cleanup must consider active, historical and project references. Remove temporary rollback copies only after the active and historical versions have been verified. Backup and distribution include the required history, with incremental file synchronization and no whole-library repacking. External-drive current-deliverable retention does not authorize deleting separately identified historical dependencies.

Record provenance, restored versions, project references, actual checks and missing dependencies. File restoration does not prove physical fit or manufacturing approval. See the [component-history protocol](component-history.md) for the full workflow.
