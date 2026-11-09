# Component package starter

[中文](README.md)

Copy this directory to an independent workspace and replace the `packageId`, record IDs, names, and part numbers. This minimal template only registers a material/part record; it does not invent mounting holes, optical surfaces, or CAD. For a placeable kit, use a similar kit under `library/standard/` as a reference, include its required part records, assign new identities, and revise interfaces, optical behavior, and BOM for the real design.

Declare actual relative asset paths, runtime targets, and SHA256 hashes in `package.json`, then check, stage, and adopt the package using the [onboarding guide](../../../docs/component-intake.en.md). The template itself is not registered in the library.
