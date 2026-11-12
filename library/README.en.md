# Component library

[中文](README.md)

Edit the independent `package.json` manifests and record files registered in `registry.json`. `standard/` contains standard kits, `components/` shared purchased and machined parts, `modules/` composite modules, `boards/` board definitions, and `custom/` the project-specific definitions required by this edition.

`assets/sha256/` stores unique model, top-view, and current drawing files by content hash. Package-level `cad/`, `rendering/`, and `drawings/` folders use relative links within the repository; `resource-map.json` records the mappings. Each package has Chinese and English directory guides linking to its records and assets.

Run `python3 hksop.py catalog build` from the repository root to regenerate the unified catalog and search indexes. `snapshots/web-current` is a current compatibility index, not a historical library. Existing drawing revisions and acceptance states are retained; file availability does not constitute new manufacturing approval. See the [onboarding guide](../docs/component-intake.en.md).

`history/` retains frozen component versions and supporting-resource links required by old designs. Referenced shared assets remain protected. Existing instances remain resolvable/renderable, while historical components are excluded from the placement palette and rejected for new placement. See the [retention policy](../docs/retention-policy.en.md).
