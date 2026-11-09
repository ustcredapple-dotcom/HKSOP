# Workspace configuration

[中文](README.md)

`distribution.json` defines this curated edition and its private GitHub destination. Current STEP files, top views, orthographic drawings, and supporting drawings for selected components are included. `workspace.json` records default build/runtime settings, and `retention-policy.json` records retention rules.

To select interpreters, copy `local-environment.example.json` to `local-environment.json` and set the actual `runtimePython`, `cadPython`, and `node` paths. This machine-specific file is ignored by Git; shared configuration must not contain personal machine paths.
