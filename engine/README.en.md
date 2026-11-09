# Protocol engine

[中文](README.md)

This directory contains the current HKSOP implementation. The root `hksop.py` entry point delegates package validation, compilation, intake, and runtime construction to `compiler/cli.py`.

`layout/` handles placement, mounting holes, supports, collisions, and board layers; `optics/` handles optical interactions; `rendering/` provides rendering code; `cad/` contains CAD helpers; `exports/` handles BOM and delivery output; and `apps/` contains the web and editor implementations. Specialized tools live in `tools/`; check their inputs and scope before using them.

`runtime-map.json` maps source files into a compatible runtime layout so existing relative imports remain valid. Rebuild the runtime after source changes. See the [CLI reference](../docs/commands.en.md).
