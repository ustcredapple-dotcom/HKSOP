# Engineering workflows

[中文](README.md)

Read [HKSOP_CONTEXT.en.md](HKSOP_CONTEXT.en.md) before selecting a workflow. Each directory has Chinese and English guides; SKILL.md is the operational instruction entry point.

[Standard optics entry point](hksop-standard-optics/README.en.md): Locate component packages, projects, and delivery inputs, then select the appropriate workflow. Use the compiler to generate catalogs rather than maintaining a second supported-parts list in a skill.

[Component design](hksop-component-design/README.en.md): Design mounting interfaces, optical datums, and supporting models while preserving local coordinates, post axes, mounting holes, and metric optical axis heights. Hand results to intake and retain unverified capability states.

[Component intake](hksop-component-upload/README.en.md): Prepare a package outside the library, validate, stage, and adopt it, then rebuild the catalog and runtime. Record stable IDs, asset hashes, BOMs, and verification results. Intake alone does not update other websites or cloud CAD.

[Manufacturing package](hksop-manufacturing-package/README.en.md): Freeze the project, component revisions, and file hashes. Organize quantities, materials, finishes, threads, models, drawings, and marking files by machined part. Record blocking items and retain review status until they are resolved.

[Customer delivery package](hksop-customer-package/README.en.md): Use the selected current project and collect its engineering JSON, actual assembly, optical views, BOM, and assembly instructions. Record hashes and state optical assumptions, unverified items, and actual cloud synchronization status.

[Modular optomechanical design](zzlab-modular-optics/README.en.md): Covers adapters, device assemblies, marking, and shop drawings for the modular post system. Verify optical surfaces, metric axis heights, holes, tool access, and assembly clearance.

[Motorized mirror-mount design](zzlab-motorized-mirror-design/README.en.md): Covers motor supports, drive connections, and modular adapters for commercial mirror mounts. Check the rear optical aperture, supports, motion envelopes, and part separation for machining. Motor firmware is outside this workflow.

[Component library maintenance](zzlab-optics-library/README.en.md): Imports and maintains component sources, CAD-derived top views, interactions, and procurement/manufacturing records. Verify provenance, geometry, optics, and manufacturing separately. External publication follows the current workspace scope.

[Layout JSON to 3D assemblies](zzlab-optics-json-to-3d/README.en.md): Rebuilds independent kit sub-assemblies and the full assembly from project JSON while retaining source hierarchy. Verify holes, optical datums, internal transforms, and overall poses; record actual local and cloud deliveries.
