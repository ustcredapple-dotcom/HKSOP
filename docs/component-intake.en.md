# Component onboarding

[中文](component-intake.md)

Prepare an independent package outside the library. Use a stable English packageId; display names, manufacturers, and model names may contain Chinese. Standard and custom packages use the same outer format, with truthful internal parameters.

Declare components, kits, or registeredBoards records in package.json. Parts hold procurement/manufacturing information. Kits reference part BOMs and describe mounting interfaces, optical reference surfaces, placement, and interactions. Board records retain their real holes and revision.

Use common.json and variants for multiple mounting orientations when appropriate. Only identical fields belong in common data; a different base, interface, or optical surface cannot be represented by rotating a picture.

Register the actual CAD, drawings, top views, and evidence under assets, with package-relative paths, runtime targets, and SHA256 hashes. Targets can use forms such as assets/step/example.step, assets/drawings/example.pdf, or static/topviews/example.svg. Changed content receives a new target filename.

Record display, placement, simulation, procurement, and manufacturing states separately with evidence. Leave unverified capabilities pending rather than replacing them with a single supported flag.

Run package check and package stage. Resolve contract or resource failures before adoption, and stage again if the library has changed. After adoption, build the isolated runtime and inspect top views, placement, optical datums/axis height, and BOM output in a project. Append actual results to the project log. Manufacturing deliveries and external publication follow the specified task and target.

Package check validates package structure. Stage also checks catalog contracts, BOM references, and declared assets. Neither certifies CAD geometry, manufacturing readiness, or physical optical performance.

See the [package schema](../engine/schemas/hksop-package.schema.json) and [starter template](../engine/templates/component-package/README.en.md). Legacy schemas remain compatibility references. For a placeable kit, use a similar package under library/standard and preserve field semantics while inserting the real new parameters.

Experimental nonstandard components may be kept under library/custom/&lt;id&gt;/drafts with their original protocol, CAD, and notes, without registry registration. These drafts are stored but are not supported by the engine. Once normalized, use stage/adopt; supported components appear in the generated unified catalog.
