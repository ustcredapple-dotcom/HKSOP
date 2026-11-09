/* Read-only index. Calls the production pure renderer; does not create a DOM or DB. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const catalogFile = path.resolve(process.argv[3] || path.join(root, 'catalog.json'));
const catalogBytes = fs.readFileSync(catalogFile), catalog = JSON.parse(catalogBytes);
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const Engine = require(path.join(root, 'static/optical-engine.js'));
const Renderer = require(path.join(root, 'static/optical-renderer.js'));
const components = new Map(catalog.components.map(c => [c.id, c]));
const postIds = new Set((catalog.universalPostSeries?.posts || []).map(p => p.componentId));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const profile = 'zzlab-account-policy-v1';
const derivationVersion = 'zzlab-interaction-index-v1';
function inference(kit) {
  const l = kit.layout || {};
  if (l.opticalType) return {basis: 'explicit-catalog-type', field: 'layout.opticalType', declaredType: l.opticalType};
  if (l.opticalPortsMm?.length) return {basis: 'legacy-port-inference', field: 'layout.opticalPortsMm', declaredType: null};
  if (kit.category === 'laser') return {basis: 'legacy-category-inference', field: 'category', declaredType: null};
  if (['coupling','pbs','waveplate','fixed','adjustable','motor'].includes(kit.category)) return {basis: 'legacy-category-inference', field: 'category', declaredType: null};
  return {basis: 'unknown-legacy-lens-fallback', field: null, declaredType: null};
}
const kits = catalog.kits.map(kit => {
  const l = kit.layout || {}, raw = inference(kit), runtimeType = Renderer.elementType(kit);
  const catalogIssue = Renderer.catalogSimulationIssue(kit);
  const instance = {id: '__protocol_probe__', kitId: kit.id, xMm: 0, yMm: 0, rotationDeg: 0};
  let fresh = null, normalizationError = null;
  try { fresh = Renderer.configFor(instance, kit, {}, Engine, catalog); }
  catch(error) { normalizationError = error.message; }
  const finiteDimensions = ['widthMm','heightMm','anchorXMm','anchorYMm'].every(k => Number.isFinite(l[k]));
  const placed = l.placementAllowed !== false && finiteDimensions;
  const holes = (l.mountingHoleOffsetsMm || []).filter(h => Number.isFinite(h.xMm) && Number.isFinite(h.yMm));
  const holeKeys = new Set(holes.map(h => JSON.stringify([h.xMm,h.yMm])));
  const minimum = l.minimumAlignedMountingHoles ?? holeKeys.size;
  const assembly = l.opticalAssembly;
  const fixedPostIds = new Set(l.fixedUniversalPostComponentIds || []);
  const replaceablePostIds = kit.components.filter(row => postIds.has(row.componentId) && !fixedPostIds.has(row.componentId)).map(row => row.componentId);
  const slots = kit.opticalSlots || [];
  const sourceRole = ['source','coupler'].includes(runtimeType);
  const warnings = [];
  if (raw.basis === 'unknown-legacy-lens-fallback') warnings.push({code:'unconfirmed_runtime_type',message:'Runtime falls back to lens; this is not an explicit physical classification. Do not treat it as a confirmed lens.'});
  else if (!raw.declaredType) warnings.push({code:'legacy_inferred_type',message:'Effective runtime type is inferred from a catalog category or ports, rather than an explicit opticalType.'});
  if (catalogIssue) warnings.push(catalogIssue);
  if (placed && !holeKeys.size) warnings.push({code:'mounting_holes_unknown',message:'May be laid out on table; threaded-board mounting cannot be declared compatible from an absent hole pattern.'});
  if (placed && !Number.isFinite(l.opticalAxisHeightMm) && !assembly) warnings.push({code:'axis_height_unknown',message:'Do not fill unknown optical height with zero or a common kit default.'});
  if (normalizationError) warnings.push({code:'normalizer_error',message:normalizationError});
  if (l.opticalGeometryEvidence?.mirrorThicknessMm != null) warnings.push({code:'mirror_thickness_calibration_fixed',message:'Recorded optical plane is calibrated for the evidenced mirror thickness; changing a purchase model does not dynamically recalibrate this datum.'});
  return {
    objectType:'kit', id:kit.id, name:kit.name, category:kit.category, permissionProfileId:profile,
    sourceFields:['layout','components','opticalSlots','category','bomPolicy'],
    placement:{declaredAllowed:has(l,'placementAllowed')?l.placementAllowed:null, hasMetricFrame:finiteDimensions,
      canCreateCanvasInstance:placed, states:placed?['root-board','sub-board','table']:['library-reference-or-whole-kit-procurement'],
      physicalBoardMounting:placed?(holeKeys.size?'requires-actual-hole-coincidence':'unconfirmed-no-hole-pattern'):'not-placeable',
      mountingHoleCount:holeKeys.size, minimumAlignedMountingHoles:holeKeys.size?minimum:null,
      collisionModel:l.collisionPolygonsMm?.length?'catalog-multipolygon-2d':'catalog-rectangle-fallback',
      containmentModel:'baseBoundsMm-rectangle', upperBodyMayOverhang:true, geometryStatus:l.geometryStatus||l.status||null,
      qualification:'Capabilities describe operation availability, not a certificate that a particular pose, height, collision state or board is valid.'},
    typeBinding:{...raw,effectiveRuntimeType:runtimeType, normalizer:'static/optical-renderer.js::elementType/configFor',
      contractPhysicalType:raw.declaredType,programState:l.opticalInteraction?'declared':'legacy-derived',opticalInteraction:l.opticalInteraction||null,routing:l.opticalInteraction?'declarative-planar-language-v1':assembly?'verified-internal-3d-assembly':runtimeType==='unsupported'?'layout-only-stop-on-ray':'planar-optical-element'},
    simulation:{catalogIssue,normalizationError,freshInstanceConfig:fresh,defaultsAreUserConfirmed:false,
      opticalDatumVerified:has(l,'opticalDatumVerified')?l.opticalDatumVerified:null,
      opticalAxisHeightMm:Number.isFinite(l.opticalAxisHeightMm)?l.opticalAxisHeightMm:null,
      axisHeightSource:l.opticalAxisHeightSource||null,opticalCenterMm:l.opticalCenterMm||null,
      surfaceAngleDeg:l.opticalSurfaceAngleDeg??null,portCount:l.opticalPortsMm?.length||0,
      opticalPortsMm:l.opticalPortsMm||[],sourceRoleConfigurable:sourceRole,
      sourceEmissionNeedsUserEnable:sourceRole,
      sourceEmissionCatalogPrerequisitesMet:sourceRole&&placed&&!catalogIssue&&Number.isFinite(l.opticalAxisHeightMm),
      defaultSourceEnabled:fresh?.source?.enabled??null,
      sourceReportApplyFields:l.sourceReport?.applyFields||[],
      internalElements:assembly?.internalElements?.map(e=>({id:e.id,type:e.type,slotId:e.slotId||null,sourceModel:e.sourceModel||null}))||[],
      internalGeometryVerified:assembly?assembly.verified===true:null,
      nominalExternalAxisHeightsMm:assembly?.externalAxisHeightsMm||[],
      runtimeEffects:{idealPbs:runtimeType==='pbs',waveplateSequence:runtimeType==='waveplate',
        twoWaveplateTargetSolver:runtimeType==='waveplate'&&slots.filter(s=>s.type==='waveplate').length===2,
        mirrorCoatingData:runtimeType==='mirror',thinLensGaussian:runtimeType==='lens',
        receivingCoupler:runtimeType==='coupler',objectiveSideView:Boolean(assembly)},
      mirrorCalibrationThicknessMm:l.opticalGeometryEvidence?.mirrorThicknessMm??null},
    procurement:{policy:kit.bomPolicy||'catalog-components',addsBaseKitRows:kit.components.length>0,
      baseRows:kit.components.map(row=>({componentId:row.componentId,quantityPerKit:row.quantity,kind:components.get(row.componentId)?.kind||null})),
      slots:slots.map(s=>({id:s.id,type:s.type,quantityPerKit:s.quantity,diameterMm:s.diameterMm??null,
        replacesComponentId:s.replacesComponentId||null,defaultExisting:s.defaultExisting===true,existingModel:s.existingModel||null})),
      notes:'Explicit inserted slot and replacement choices are instance-owned. Reference-only kits can still add opted-in replacements; base kit rows are not invented.'},
    elevation:{canSetAdditionalElevation:placed,automaticTargetStepMm:12.5,
      automaticTargetEligibility:placed?(assembly?'manual-only-multiple-3d-surfaces':Number.isFinite(l.opticalAxisHeightMm)?'requires-realizable-materials-and-layout':'blocked-until-axis-height-known'):'not-placeable',
      universalPostComponentIds:kit.components.filter(row=>postIds.has(row.componentId)).map(row=>row.componentId),
      fixedUniversalPostComponentIds:[...fixedPostIds],
      replaceableUniversalPostComponentIds:replaceablePostIds,
      nominalHeightCompatibility:assembly?.externalAxisHeightsMm?'declared-connected-height-domains; actual-3d-ray-hit-still-required':'global-equal-height',
      rootInstanceMode:replaceablePostIds.length?'replace-registered-posts-exactly':'additional-catalog-posts-spacers-and-fractional-shim',
      laserAdapterAvailable:placed&&kit.id==='laser-308nm'},
    interactionProfileIds:placed?['canvas-instance-v1','measurement-v1','project-copy-persistence-v1','account-cart-v1',...(assembly?['objective-sideview-v1']:['planar-optics-v1'])]:['library-reference-v1','account-cart-v1'],
    warnings
  };
});
const registeredBoards = (catalog.registeredBoards||[]).map(board => ({
  objectType:'registered-board',id:board.id,name:board.name,revision:board.revision,permissionProfileId:profile,
  sourceFields:['outlineMm','cutoutsMm','holesMm','mountingHoleIds','minimumAlignedMountingHoles','revision'],
  placement:{operations:board.stageOnly?['stage-module-top-only','move-module','rotate-module','edit-contents']:['use-as-root-board','add-as-sub-board','move-module','rotate-module','edit-contents'],
    geometryEditableInBrowser:false,dimensionsMm:[board.widthMm,board.heightMm,board.thicknessMm],
    outlinePolygonCount:1,cutoutCount:board.cutoutsMm?.length||0,holeCount:board.holesMm.length,
    holeCountsByType:Object.fromEntries(['thread','clearance','counterbore'].map(type=>[type,board.holesMm.filter(h=>h.type===type).length])),
    validM6ThreadHoleCount:board.holesMm.filter(h=>h.type==='thread'&&h.thread==='M6x1.0').length,
    eligibleFixedHoleIds:board.mountingHoleIds||[],minimumAlignedMountingHoles:board.minimumAlignedMountingHoles??4,
    fixedHoleSelectionMode:'existing-catalog-clearance-or-counterbore-only',
    rootTableModeMeaning:'If used as a table reference root, that root is not manufactured. A real child board remains a manufacturing item.'},
  procurement:{policy:board.stageOnly?'stage-module-bom-only':'registered-board-assets',manufacturesPhysicalBoard:true,stepRegistered:Boolean(board.stepPath),drawingRegistered:Boolean(board.drawingPath),
    sourceMaterial:board.sourceMaterial||null,sourceSurfaceTreatment:board.sourceSurfaceTreatment||null,
    excludesManufacturingOnlyWhenRootTable:true},
  simulation:{type:'module-boundary-not-optical-surface',usesActualOutlineAndCutouts:true,rayMeasurementUsesActualThreadHoles:true},
  elevation:{canSetChildBoardElevation:true,mode:'catalog-lbtek-25mm-baseless-m6-posts-then-op1-then-tenths-shim',automaticTargetStepMm:12.5},
  interactionProfileIds:['registered-board-v1','sub-board-module-v1','measurement-v1','project-copy-persistence-v1','account-cart-v1'],
  warnings:[{code:'fixed-source-revision',message:'A changed revision requires re-registration/reinsertion; project geometry and source file paths cannot override this catalog board.'}]
}));
const stageModules=(catalog.stageModules||[]).map(m=>({
  id:m.id,name:m.name,revision:m.revision,objectType:'moving-stage-sub-board',
  capability:'zzlab-stage-motion-v2',templateId:'moving-mechanical-board',
  instanceState:['moduleId','revision','qMm'],coordinateContract:'subBoard XY is current moving-top origin; fixed datum = topOrigin - R(centerTopOrigin + q axis)',
  motion:m.motion,stack:m.stack,topSurface:m.topSurface,lowerAttachmentHoles:m.lowerAttachmentHoles,
  placement:{kind:'sub-board',baseBoundsMm:m.runtime.baseBoundsMm,requiredAlignment:'all-fixed-base-holes; no re-snap of moving-top q',topBoardId:m.runtime.topBoardId,topBoardRevision:m.runtime.topBoardRevision},
  collision:{bodies:m.collisionBodies,policy:'vendor conservative full-travel envelope plus current top plate; sweep envelope reported separately'},
  simulation:{operator:null,children:'XY follows moving top; effective Z includes actual stack total height exactly once'},
  procurement:{policy:'catalog-module-bom-once',bom:m.bom,topBoardNotDuplicated:true},
  modelSelectionStatus:m.modelSelectionStatus,manufacturingStatus:m.manufacturingStatus,asBuiltAcceptance:m.asBuiltAcceptance
}));
for(const k of kits){const m=stageModules.find(m=>m.id===k.id);if(m){
  k.placement.canCreateCanvasInstance=false;k.placement.canCreateSubBoard=true;k.placement.states=['moving-stage-sub-board'];
  k.typeBinding.routing='moving-stage-child-transforms';k.simulation.catalogIssue=null;k.simulation.normalizationError=null;
  k.interactionProfileIds=['moving-stage-v2','sub-board-module-v1','measurement-v1','project-copy-persistence-v1','account-cart-v1'];
  k.warnings=[{code:'nominal-stage-design',message:'Registry/CAD verified; actual stage midpoint and fabricated assembly remain to be measured.'}];
}}
const runtimeFiles=['static/fixed-board-optics.js','static/global-height.js','manual_source_mount.py','static/manual-source-mount.js','collision_overrides.py','static/collision-overrides.js','moving_stages.py','static/moving-stages.js','static/shared-kits.js','static/index.html','static/app.js','static/shared-project.js','shared_kits.py','exports.py','bom.py','tools/library.py','static/optical-interaction-language.js','optical_interaction.py','tools/build-interaction-index.py','tools/build-interaction-index.cjs','static/optical-renderer.js','static/optical-engine.js','static/optical-assembly-engine.js','static/project-file.js','static/layout.js','static/stacked-boards.js','static/registered-boards.js','static/elevation.js','static/measurement.js','static/table-mode.js','layout.py','stacked_layout.py','registered_boards.py','elevation.py','laser_adapter.py','optics_settings.py','cart.py','access_settings.py','app.py'];
const result={schema:derivationVersion,protocol:'zzlab-optics-interaction-contract@1.0.0',libraryProtocol:'zzlab-optics-library-v1',catalogVersion:catalog.version,
  sourceCatalogSha256:hash(catalogBytes),derivation:{method:'Production pure JS APIs Renderer.elementType, Renderer.catalogSimulationIssue and Renderer.configFor(instance-without-optics, kit, empty-purchases, Engine, catalog). No DOM, browser, server, database or source mutation.',
    sourceRecordHashAlgorithm:'Filled by Python companion: SHA256(UTF8(json.dumps(original_catalog_record, ensure_ascii=False, sort_keys=True, separators=(comma,colon), allow_nan=False))).',
    engineInput:'Fresh instance id __protocol_probe__; no saved optics, no purchase selections; current catalog authoritative. This is not a migration of saved projects.',
    runtimeFiles:runtimeFiles.map(file=>({path:file,sha256:hash(fs.readFileSync(path.join(root,file)))}))},
  counts:{kits:kits.length,registeredBoards:registeredBoards.length,stageModules:stageModules.length},
  interactionProfiles:{
    'manual-source-mount-v1':{meaning:'Fixed catalog optical XY reference snaps to existing board holes independently of unverified mounting. Explicit instance user support/reference/height declaration is required; target height is never a default or catalog certification.'},
    'moving-stage-v2':{meaning:'Trusted module plus fixed revision and bounded q; fixed-base mounting, moving-top children, exact stack Z, module BOM once.'},
    'canvas-instance-v1':{contractSections:[2,3,4,7],meaning:'Placed catalog kit; screw-hole-phase snapping, 90-degree poses, 2D physical silhouette collision, base containment.'},
    'measurement-v1':{contractSections:[7,9],meaning:'Single-click actual valid hole/reference point, double-click base center, right-click properties; real path readings only.'},
    'project-copy-persistence-v1':{contractSections:[7,8,10],meaning:'Deep-copy instance-owned optical/purchase configuration; strict JSON project references; no asset-path overrides.'},
    'account-cart-v1':{contractSections:[10],meaning:'Account-bound independent cart; deleted overrides selected; source snapshot and revision checks.'},
    'objective-sideview-v1':{contractSections:[8,9],meaning:'Verified finite internal 3D planes, independently configured coating face, side-view trace and replay.'},
    'planar-optics-v1':{contractSections:[8,9],meaning:'Effective runtime optical type governs propagation; unsupported/unknown geometry stops; initial config is not evidence of a physical capability.'},
    'library-reference-v1':{contractSections:[1,12],meaning:'Listed catalog record; placement disabled. Procurement depends on actual base rows and explicit option policy.'},
    'registered-board-v1':{contractSections:[2,5,10],meaning:'Fixed catalog id/revision geometry and actual holes; existing fixed-hole selection only.'},
    'sub-board-module-v1':{contractSections:[5,6,7],meaning:'One child-board level; board and children move rigidly, contents editable in same canvas, parent fixed-hole constraints apply.'}
  },
  permissionProfiles:{[profile]:{guest:{access:'admin-guestAccessEnabled',localCanvas:true,projectDownload:true,listDownload:true,accountCart:false,publish:false,manufacturingDownload:'both guestAccessEnabled and guestManufacturingDownloadsEnabled'},readonly:{requiresAccountIdForCart:true,localCanvas:true,accountCart:true,manufacturingDownload:true,publish:false},user:{localCanvas:true,accountCart:true,manufacturingDownload:true,publish:true},admin:{localCanvas:true,accountCart:true,manufacturingDownload:true,publish:true,canManageGuestPolicy:true}}},
  interactionProfileReference:'interaction-contract.md',kits,registeredBoards,stageModules};
if(hash(fs.readFileSync(catalogFile))!==result.sourceCatalogSha256)throw new Error('Catalog changed while generating the index');
process.stdout.write(JSON.stringify(result,null,2)+'\n');
