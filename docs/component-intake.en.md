# Component onboarding

[中文](component-intake.md)

Prepare an independent package outside the library. Use a stable English packageId; display names, manufacturers, and model names may contain Chinese. Standard and custom packages use the same outer format, with truthful internal parameters.

Declare components, kits, or registeredBoards records in package.json. Parts hold procurement/manufacturing information. Kits reference part BOMs and describe mounting interfaces, optical reference surfaces, placement, and interactions. Board records retain their real holes and revision.

Use common.json and variants for multiple mounting orientations when appropriate. Only identical fields belong in common data; a different base, interface, or optical surface cannot be represented by rotating a picture.

Register the actual CAD, drawings, top views, and evidence under assets, with package-relative paths, runtime targets, and SHA256 hashes. Targets can use forms such as assets/step/example.step, assets/drawings/example.pdf, or static/topviews/example.svg. Changed content receives a new target filename.

Record display, placement, simulation, procurement, and manufacturing states separately with evidence. Leave unverified capabilities pending rather than replacing them with a single supported flag.

Run package check and package stage. Resolve contract or resource failures before adoption, and stage again if the library has changed. Reuse checks and runtime builds already completed by the transaction. Build only missing or invalidated outputs, and inspect only uncovered new/changed resource, placement, optical-datum, and BOM mappings. Append actual results to the project log. Manufacturing deliveries and external publication follow the specified task and target.

Package check validates package structure. Stage also checks catalog contracts, BOM references, and declared assets. Neither certifies CAD geometry, manufacturing readiness, or physical optical performance.

See the [package schema](../engine/schemas/hksop-package.schema.json) and [starter template](../engine/templates/component-package/README.en.md). Legacy schemas remain compatibility references. For a placeable kit, use a similar package under library/standard and preserve field semantics while inserting the real new parameters.

Experimental nonstandard components may be kept under library/custom/&lt;id&gt;/drafts with their original protocol, CAD, and notes, without registry registration. These drafts are stored but are not supported by the engine. Once normalized, use stage/adopt; supported components appear in the generated unified catalog.

## Reuse AI verification by default

User agreement, 2026-11-09: accept previously completed AI verification and check only additions, changes, and their directly affected behavior. This applies to ordinary and fast intake without an extra opt-in. Reuse existing models, BOMs, drawings, top views, hashes, and verification records; do not repeat measurements, rendering, or page-by-page review.

Read the current receipt or manifest to identify the revision and inputs, fill only missing package fields/assets, and run check → stage → adopt. Inspect only new/changed integration mappings and runtime behavior not already covered for the same version and environment. Reuse checks and builds completed by the transaction. Do not add duplicate full-library regression, CAD verification, or browser sessions. Changed content, incompatible dependencies, missing evidence, or an actual contradiction triggers checks only for the affected scope.

Record the reused source/revision, this change, checks actually performed, and pending items in the existing log or receipt. Preserve the separate status of nominal geometry, physical fit, full adjustment travel, manufacturing approval, and cloud synchronization. See the [detailed reuse procedure](../skills/zzlab-optics-library/references/acceptance-reuse.md).
