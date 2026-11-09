# CLI reference

[中文](commands.md)

Run commands from the repository root. On a new machine, install the runtime dependencies described on the homepage and configure the optional CAD/Node.js environment as required.

```sh
python3 hksop.py catalog check
python3 hksop.py catalog build
python3 hksop.py catalog list
python3 hksop.py runtime build --profile editor
python3 hksop.py serve --profile editor --port 18945
python3 hksop.py package check /path/to/new-package
python3 hksop.py package stage /path/to/new-package --collection custom
python3 hksop.py package adopt runtime/staging/<stage-id>
```

Replace `<stage-id>` with the value returned by stage. Use standard instead of custom for standard packages. Stage again if the library changes before adoption. Example engineering files are under projects.

The current distribution includes existing drawings for the selected components. Preserve incomplete or unverified manufacturing states for individual parts; copying files is not an acceptance test.

The GitHub destination is the public ustcredapple-dotcom/HKSOP repository. config/local-environment.json only stores machine-local interpreter paths. Configure it from the example on another machine, or use the active Python and Node.js from PATH for CLI tracing.
