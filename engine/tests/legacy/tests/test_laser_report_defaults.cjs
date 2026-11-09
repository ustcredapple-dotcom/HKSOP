'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const E = require('../static/optical-engine.js'), R = require('../static/optical-renderer.js');
const codec = require('../static/project-file.js'), shared = require('../static/shared-project.js');
const copy = x => JSON.parse(JSON.stringify(x)), published = require('../catalog.json');
const catalog = copy(published), laser = copy(catalog.kits.find(k => k.id === 'laser-308nm'));
// Local fixtures exercise report inheritance independently of catalog release timing.
delete laser.layout.sourceReport;
laser.layout.opticalPortsMm[0].wavelengthNm = 308;
laser.layout.opticalDefaults = {source: {wavelengthNm: 308.366, powerMw: 118, beamDiameterMm: 1.264, beamQualityM2: 1.071}};
const ecdl = copy(laser); ecdl.id = 'qa-ecdl-report-source'; ecdl.name = 'ECDL report fixture';
ecdl.layout.opticalDefaults = {source: {wavelengthNm: 1030, powerMw: 50}};
ecdl.layout.opticalPortsMm[0].wavelengthNm = 1030;
catalog.kits = catalog.kits.filter(k => k.id !== laser.id).concat([laser, ecdl]);
const board = {widthMm: 900, heightMm: 600, pitchMm: 25, edgeOffsetMm: 12.5, thicknessMm: 12.7, holeType: 'M6_through', mountingHoles: []};
const instance = (kit = laser, optics) => ({id: 'report-source', kitId: kit.id, xMm: 450, yMm: 300, rotationDeg: 0, ...(optics ? {optics} : {})});
const config = (kit = laser, optics) => R.configFor(instance(kit, optics), kit, {}, E, catalog);
let checks = 0;
const test = (name, fn) => {fn(); checks++; console.log('PASS ' + name);};

test('each laser inherits only its own report fields and remains off until chosen', () => {
  const before = copy(catalog), uv = config(), ir = config(ecdl);
  for (const [key, value] of Object.entries(laser.layout.opticalDefaults.source)) assert.equal(uv.source[key], value);
  assert.equal(uv.source.enabled, false); assert.equal(uv.source.directionAngleDeg, 180);
  assert.equal(ir.source.wavelengthNm, 1030); assert.equal(ir.source.powerMw, 50); assert.equal(ir.source.enabled, false);
  assert.equal(Object.hasOwn(ecdl.layout.opticalDefaults.source, 'beamDiameterMm'), false, 'a field absent from the report is not written into the catalog');
  assert.deepEqual(catalog, before); assert.equal(Object.hasOwn(instance(), 'optics'), false);
});

test('sparse saved source inherits precise report values without reverting to generic defaults', () => {
  const sparse = {elementType: 'source', inserted: true, source: {enabled: true}}, before = copy(sparse);
  for (const kit of [laser, ecdl]) {
    const o = config(kit, sparse);
    for (const [key, value] of Object.entries(kit.layout.opticalDefaults.source)) assert.equal(o.source[key], value);
    assert.equal(o.source.enabled, true); assert.equal(o.source.directionAngleDeg, 180);
  }
  assert.deepEqual(sparse, before);
  const withoutSource = config(laser, {elementType: 'source', inserted: true});
  assert.equal(withoutSource.source.wavelengthNm, 308.366); assert.equal(withoutSource.source.enabled, false);
});

test('explicit user values win, including false, zero, null and a legacy full configuration', () => {
  const kit = copy(laser); kit.layout.opticalDefaults.source.wavefrontRadiusMm = 2000; // Synthetic fallback to test explicit null.
  const stored = {elementType: 'source', inserted: false, configured: false,
    source: {enabled: false, powerMw: 0, wavelengthNm: 307.8, directionAngleDeg: 0, polarizationAngleDeg: 0, wavefrontRadiusMm: null}};
  const before = copy(stored), result = config(kit, stored);
  for (const [key, value] of Object.entries(stored.source)) assert.equal(result.source[key], value);
  assert.equal(result.inserted, false); assert.equal(result.configured, false);
  assert.equal(result.source.beamDiameterMm, 1.264); assert.deepEqual(stored, before);
  const legacy = E.defaults('source'); legacy.source.enabled = true;
  assert.deepEqual(config(kit, legacy), legacy, 'previously saved full parameters are not silently converted to the new report');
  result.source.powerMw = 17; assert.equal(kit.layout.opticalDefaults.source.powerMw, 118);
});

test('report direction and wavelength take priority over nominal port labels, with geometric fallbacks', () => {
  const kit = copy(laser); kit.layout.opticalDirectionDeg = -90;
  kit.layout.opticalDefaults.source.directionAngleDeg = 0;
  assert.equal(config(kit).source.directionAngleDeg, 0); assert.equal(config(kit).source.wavelengthNm, 308.366);
  delete kit.layout.opticalDefaults.source.directionAngleDeg;
  assert.equal(config(kit).source.directionAngleDeg, -90);
  delete kit.layout.opticalDirectionDeg; kit.layout.opticalPortsMm[0].directionX = 0; kit.layout.opticalPortsMm[0].directionY = 1;
  assert.equal(config(kit).source.directionAngleDeg, 90);
  delete kit.layout.opticalDefaults;
  assert.equal(config(kit).source.wavelengthNm, 308); // Deliberately retained nominal geometry label.
});

test('ray creation consumes report power, wavelength, diameter and M² after enabling emission', () => {
  const kits = new Map(catalog.kits.map(k => [k.id, k])), i = instance(laser, {elementType: 'source', inserted: true, source: {enabled: true}});
  const scene = R.sceneFor({board, instances: [i]}, kits, {}, [], E, catalog), trace = E.createSession(scene), reading = E.beamAt(trace.segments[0], 0);
  assert.equal(trace.sourceIds.length, 1); assert.equal(reading.powerMw, 118); assert.equal(reading.wavelengthNm, 308.366);
  assert.equal(reading.beamQualityM2, 1.071); assert.ok(Math.abs(reading.diameterMm - 1.264) < 1e-12);
  i.optics.source.enabled = false;
  assert.equal(E.createSession(R.sceneFor({board, instances: [i]}, kits, {}, [], E, catalog)).segments.length, 0);
});

test('sparse non-source catalog defaults inherit while unsupported optics remain blocked', () => {
  const lens = {id: 'qa-lens', category: 'lens', layout: {opticalType: 'lens', opticalDefaults: {focalLengthMm: 75, clearApertureMm: 19}}};
  const o = config(lens, {elementType: 'lens', inserted: true, focalLengthMm: null});
  assert.equal(o.focalLengthMm, null); assert.equal(o.clearApertureMm, 19);
  const blocked = copy(laser); blocked.layout.opticalDatumVerified = false;
  const result = config(blocked, {elementType: 'source', inserted: true, source: {enabled: true}});
  assert.equal(result.elementType, 'unsupported'); assert.equal(result.source.enabled, false);
});

let serial = 0;
const options = {catalog, now: '2026-10-05T00:00:00Z', newId: () => `report-${++serial}`};
const project = instances => codec.create({metadata: {name: 'Laser report persistence'}, catalogVersion: catalog.version,
  layout: {board, instances}, optical: {}, extras: [], moduleQuantities: [], ui: {selectedIds: [], view: null}}, options);
test('saved report parameters and sparse overrides survive project export, import and module copying', () => {
  const resolved = config(); resolved.source.enabled = true; resolved.source.powerMw = 91;
  const raw = project([instance(laser, resolved), {...instance(ecdl, {elementType: 'source', inserted: true, source: {enabled: false, powerMw: 0}}), id: 'ecdl'}]);
  const reopened = codec.parse(JSON.stringify(raw), options).project;
  assert.deepEqual(reopened.layout.instances.map(i => i.optics), raw.layout.instances.map(i => i.optics));
  const mounted = shared.mountOnBoard(project([]), reopened, options).project;
  const extracted = shared.extractBoard(mounted, mounted.layout.subBoards[0].id, options);
  assert.deepEqual(extracted.layout.instances.map(i => i.optics), raw.layout.instances.map(i => i.optics));
  assert.equal(config(ecdl, extracted.layout.instances[1].optics).source.wavelengthNm, 1030);
  extracted.layout.instances[0].optics.source.powerMw = 17;
  assert.equal(raw.layout.instances[0].optics.source.powerMw, 91);
});

test('actual editor clipboard freezes report parameters and keeps pasted source independent', () => {
  const root = path.resolve(__dirname, '..'), harness = {require, __dirname: root, console};
  vm.createContext(harness);
  const performance = fs.readFileSync(path.join(root, 'test_layout_performance_frontend.cjs'), 'utf8');
  vm.runInContext(performance.slice(0, performance.indexOf('{\n  const f=fixture(),e=f.editor')) + '\nglobalThis.makeEnvironment=environment;', harness);
  const env = harness.makeEnvironment(fs.readFileSync(path.join(root, 'static/layout.js'), 'utf8'));
  const resolved = config(); resolved.source.enabled = true;
  const editor = new env.Editor({catalog, saved: {board, instances: [instance(laser, resolved)]}, notify() {}});
  editor.select('report-source'); editor.copySelection(); editor.instances[0].optics.source.powerMw = 90;
  const pasted = editor.pasteSelection(), child = editor.instances.find(i => i.id === pasted.ids[0]);
  assert.deepEqual(copy(child.optics), resolved); assert.equal(Object.isFrozen(editor.clipboard.instances[0].optics.source), true);
  child.optics.source.powerMw = 45; assert.equal(editor.instances[0].optics.source.powerMw, 90);
  const reopened = codec.parse(JSON.stringify(project(copy(editor.instances))), options).project;
  assert.deepEqual(reopened.layout.instances.map(i => i.optics.source.powerMw), [90, 45]);
});

test('report panel escapes source text and applying it edits the form only, preserving unmeasured settings', () => {
  const kit = copy(laser);
  kit.layout.sourceReport = {title: 'Report <308>', reportId: 'SN&2026', summary: ['118 mW < measured'], simulationNotes: ['PER alone does not specify the Stokes vector.']};
  Object.assign(kit.layout.opticalDefaults.source, {enabled: true, polarizationType: 'linear', directionAngleDeg: 180, polarizationAngleDeg: 0, wavefrontRadiusMm: null});
  const markup = R.sourceReportMarkup(kit);
  assert.match(markup, /Report &lt;308&gt;/); assert.match(markup, /SN&amp;2026/); assert.match(markup, /118 mW &lt; measured/);
  assert.match(markup, /PER alone/); assert.match(markup, /采用报告参数/); assert.equal(R.sourceReportMarkup(laser), '');
  const root = path.resolve(__dirname, '..'), harness = {require, __dirname: root, console}; vm.createContext(harness);
  const performance = fs.readFileSync(path.join(root, 'test_layout_performance_frontend.cjs'), 'utf8');
  vm.runInContext(performance.slice(0, performance.indexOf('{\n  const f=fixture(),e=f.editor')) + '\nglobalThis.makeEnvironment=environment;', harness);
  const source = ['layout.js', 'optical-engine.js', 'optical-hole-probe.js', 'optical-renderer.js'].map(f => fs.readFileSync(path.join(root, 'static', f), 'utf8')).join('\n');
  const env = harness.makeEnvironment(source), target = {kit, config: config(kit)}, before = copy(target), node = id => env.document.getElementById(id);
  node('optics-type').value = 'source'; node('optics-source-enabled').checked = false;
  node('optics-polarization-angle').value = '37'; node('optics-wavefront').value = '-600'; node('optics-ellipticity').value = '12';
  const form = env.Editor.prototype.opticalFormMarkup.call({_opticalTarget: target}, config(kit));
  assert.match(form, /optics-source-use-report/); assert.match(form, /Report &lt;308&gt;/);
  env.Editor.prototype.applyReportedSourceParameters.call({_opticalTarget: target});
  for (const [key, id] of Object.entries({wavelengthNm: 'optics-wavelength', powerMw: 'optics-power', beamDiameterMm: 'optics-diameter', beamQualityM2: 'optics-m2', polarizationType: 'optics-polarization', directionAngleDeg: 'optics-direction'})) assert.equal(node(id).value, String(kit.layout.opticalDefaults.source[key]));
  assert.equal(node('optics-source-enabled').checked, false); assert.equal(node('optics-polarization-angle').value, '37');
  assert.equal(node('optics-wavefront').value, '-600'); assert.equal(node('optics-ellipticity').value, '12');
  assert.deepEqual(target, before, 'form fill does not change instance, config or catalog before Save');
  assert.match(node('optics-source-report-status').textContent, /保存后/);
  node('optics-type').value = 'lens'; node('optics-power').value = '19';
  env.Editor.prototype.applyReportedSourceParameters.call({_opticalTarget: target}); assert.equal(node('optics-power').value, '19');
  node('optics-type').value = 'source'; node('optics-direction').value = '27';
  kit.layout.sourceReport.applyFields = ['wavelengthNm','powerMw','beamDiameterMm','beamQualityM2','polarizationType'];
  env.Editor.prototype.applyReportedSourceParameters.call({_opticalTarget: target});
  assert.equal(node('optics-direction').value, '27', 'an unreported direction must not overwrite the current instance direction');
  assert.equal(node('optics-power').value, '118');
  assert.doesNotMatch(R.sourceReportMarkup(kit), /器件出光方向/, 'button description lists only explicitly registered report fields');
  kit.layout.sourceReport.applyFields = [];
  assert.doesNotMatch(R.sourceReportMarkup(kit), /采用报告参数/);
  node('optics-power').value = '16'; env.Editor.prototype.applyReportedSourceParameters.call({_opticalTarget: target});
  assert.equal(node('optics-power').value, '16');
});
console.log(`${checks} laser report default and persistence checks passed`);
