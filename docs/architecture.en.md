# Architecture

[中文](architecture.md)

This curated edition retains the HKSOP engine/library/skills/projects architecture. Independent component packages are registered in the registry. The compiler generates the catalog, entity and package indexes, HTML inventory, and runtime.

Standard packages use the standard/modules categories, with shared purchasing and manufacturing records in components. The selection includes dependencies required by structured BOMs, board definitions, and common protocol parameters, plus the custom definitions used by the 1-to-3 and DoublePass examples. It is not a wholesale copy of custom; see [selection.json](selection.json).

Current STEP models, top views, orthographic/shop drawings, and marking files are deduplicated by SHA256. Package folders use relative links within the repository. Examples reference library assets rather than storing complete duplicate project assemblies, machining packages, or historical layouts.

On 2026-11-09 the user expanded distribution to include the selected components' current drawings in this repository. Original revisions and acceptance states are retained. Copying and hash verification do not constitute new manufacturing drawing approval; see [cad-restoration.json](cad-restoration.json).

Machine-local runtime directories, build outputs, and interpreter settings are excluded from Git. The user subsequently requested public visibility, with current component models, top views, and supporting drawings committed alongside the source.
