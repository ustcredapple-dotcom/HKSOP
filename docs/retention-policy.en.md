# Retention policy

[中文](retention-policy.md)

These user rules were established on 2026-11-08 and override older instructions to retain complete snapshots, old CAD, or historical delivery collections.

Keep only the active engine implementation and current component definitions with the CAD, drawings, rendering, and notes they still use. Different active models and mounting variants can coexist; an R1/R2 filename alone does not prove a file is obsolete.

For an actual project, retain its current final engineering JSON and the current 3D/CAD, drawings, manufacturing package, customer package, and purchasing list only as needed. Historical retention is limited to manually confirmed or formally delivered engineering JSON milestones, deduplicated by content. Do not retain autosaves, temporary debugging layouts, or complete intake-demo histories.

Do not retain old engines, old library snapshots, historical project models/CAD/drawings, old manufacturing/customer packages, or complete reconstruction archives. Do not silently retain historical dependencies just to reopen an old JSON file.

Historical JSON is for layout traceability. Check it against the current library when reopened; it cannot be claimed to reproduce deleted old geometry exactly. Current project-specific components belong in the active custom library rather than in a historical full-library snapshot.

Intake transactions may use temporary rollback staging. Clean it after successful acceptance. Generated files, caches, and expired staging directories are not permanent versions. Backups use the same retained set and must not reintroduce discarded history.

Check current dependencies before reorganizing and verify files and links afterwards. Compact project logs, version numbers, source hashes, and acceptance conclusions may be retained as text evidence. Work remains limited to the authorized workspace and does not authorize deleting other projects, services, or databases.
