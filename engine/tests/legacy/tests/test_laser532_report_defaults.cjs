'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const E = require('../static/optical-engine.js'), R = require('../static/optical-renderer.js'), codec = require('../static/project-file.js');
const root = path.resolve(__dirname, '..'), catalog = require('../catalog.json');
const baseline = JSON.parse(fs.readFileSync(path.join(root, 'data_evidence/laser-532nm-report-2026-10-05/catalog-before.json'), 'utf8'));
const copy = value => JSON.parse(JSON.stringify(value));
const kit = catalog.kits.find(k => k.id === 'laser-532nm'), beforeKit = baseline.kits.find(k => k.id === kit.id);
const report = kit.layout.sourceReport, measured = {wavelengthNm:532.00020, powerMw:21630, beamDiameterMm:1.574, beamQualityM2:1.040, polarizationType:'linear'};
const part = optics => ({id:'green-source', kitId:kit.id, xMm:450, yMm:225, rotationDeg:0, ...(optics ? {optics} : {})});
const resolve = optics => R.configFor(part(optics), kit, {}, E, catalog);
const board = {widthMm:900, heightMm:450, pitchMm:25, edgeOffsetMm:12.5, thicknessMm:12.7, holeType:'M6_through', mountingHoles:[]};
let checks = 0;
const test = (name, fn) => {fn(); checks++; console.log('PASS ' + name);};
assert.ok(kit.layout.sourceReport, 'Tests require the registered 532 report data');

test('actual 532 catalog registers the correct report and converts 21.63 W to 21630 mW', () => {
  assert.equal(report.reportId, 'PLP-2026-03-007265-01');
  assert.equal(catalog.components.find(c => c.id === kit.id).model, 'FL-SF-532-20-CW');
  assert.equal(report.reportedParameters.extinctionRatioDb, 21.1);
  assert.deepEqual(new Set(report.applyFields), new Set(Object.keys(measured)));
  for (const [key, value] of Object.entries(measured)) assert.equal(kit.layout.opticalDefaults.source[key], value, key);
  assert.equal(kit.layout.opticalDefaults.source.powerMw, 21.63 * 1000);
  assert.notEqual(kit.layout.opticalDefaults.source.powerMw, 21.63);
  assert.equal(report.reportedParameters.axisRelativeToBoardDeg, null);
  assert.equal(report.reportedParameters.windowWavefrontRadiusMm, null);
  assert.equal(Object.hasOwn(kit.layout.opticalDefaults.source, 'extinctionRatioDb'), false, 'PER does not invent an engine Stokes input');
});

test('a new unconfigured 532 source inherits its report without automatically emitting', () => {
  const original = copy(kit), source = resolve().source;
  for (const [key, value] of Object.entries(measured)) assert.equal(source[key], value, key);
  assert.equal(source.enabled, false); assert.equal(source.directionAngleDeg, 180);
  assert.deepEqual(kit, original); assert.equal(Object.hasOwn(part(), 'optics'), false);
});

test('old sparse source instances inherit missing fields while retaining explicit zero, false and null', () => {
  const sparse = {elementType:'source', inserted:true, source:{enabled:true}}, stored = copy(sparse);
  const resolved = resolve(sparse);
  assert.equal(resolved.source.enabled, true);
  for (const [key, value] of Object.entries(measured)) assert.equal(resolved.source[key], value);
  const stopped = resolve({elementType:'source', inserted:false, configured:false, source:{enabled:false, powerMw:0, wavefrontRadiusMm:null, directionAngleDeg:0}});
  assert.equal(stopped.inserted, false); assert.equal(stopped.configured, false); assert.equal(stopped.source.enabled, false);
  assert.equal(stopped.source.powerMw, 0); assert.equal(stopped.source.wavefrontRadiusMm, null); assert.equal(stopped.source.directionAngleDeg, 0);
  assert.equal(stopped.source.wavelengthNm, 532.00020); assert.deepEqual(sparse, stored);
});

test('full legacy and user-configured source parameters do not silently switch to the new report', () => {
  const legacy = E.defaults('source'); legacy.source.enabled = true;
  assert.deepEqual(resolve(legacy), legacy);
  const custom = E.defaults('source'); Object.assign(custom.source, {enabled:true, wavelengthNm:532.08, powerMw:21000,
    beamDiameterMm:1.8, beamQualityM2:1.2, polarizationType:'elliptical', polarizationAngleDeg:37,
    ellipticityDeg:12, wavefrontRadiusMm:-250, directionAngleDeg:0});
  assert.deepEqual(resolve(custom), custom);
  const options = {catalog, now:'2026-10-05T00:00:00Z', newId:() => 'green-report-project'};
  const project = codec.create({metadata:{name:'532 report parameters'}, catalogVersion:catalog.version,
    layout:{board, instances:[part(custom)]}, optical:{}, extras:[], moduleQuantities:[], ui:{selectedIds:[], view:null}}, options);
  const reopened = codec.parse(JSON.stringify(project), options).project;
  assert.deepEqual(reopened.layout.instances[0].optics, custom);
  reopened.layout.instances[0].optics.source.powerMw = 19000;
  assert.equal(custom.source.powerMw, 21000);
});

test('the emitted beam uses report power, exact wavelength, effective diameter and M²', () => {
  const instance = part({elementType:'source', inserted:true, source:{enabled:true}}), kits = new Map(catalog.kits.map(k => [k.id,k]));
  const scene = R.sceneFor({board, instances:[instance]}, kits, {}, [], E, catalog), trace = E.createSession(scene);
  assert.equal(trace.sourceIds.length, 1);
  const emitted = E.beamAt(trace.segments[0], 0);
  assert.equal(emitted.powerMw, 21630); assert.equal(emitted.wavelengthNm, 532.00020); assert.equal(emitted.beamQualityM2, 1.040);
  assert.ok(Math.abs(emitted.diameterMm - 1.574) < 1e-12);
  assert.equal(scene.elements[0].axisHeightMm, 95.7);
});

test('532 mechanical coordinates and the entire 308/ECDL registrations stay unchanged', () => {
  for (const key of ['widthMm','heightMm','anchorXMm','anchorYMm','baseBoundsMm','collisionBoundsMm','collisionPolygonsMm',
    'mountingHoleOffsetsMm','mountingHoleRadiusMm','minimumAlignedMountingHoles','opticalAxisHeightMm','topViewPath'])
    assert.deepEqual(kit.layout[key], beforeKit.layout[key], key);
  const geometry = ports => ports.map(({wavelengthNm, ...position}) => position);
  assert.deepEqual(geometry(kit.layout.opticalPortsMm), geometry(beforeKit.layout.opticalPortsMm));
  for (const id of ['laser-308nm','laser-ecdl-1030nm']) assert.deepEqual(catalog.kits.find(k => k.id === id), baseline.kits.find(k => k.id === id));
  assert.deepEqual(catalog.components.find(c => c.id === 'laser-308nm'), baseline.components.find(c => c.id === 'laser-308nm'));
  assert.deepEqual(catalog.registeredBoards, baseline.registeredBoards);
});

test('report controls expose source evidence and keep unmeasured angle/direction out of reset fields', () => {
  const markup = R.sourceReportMarkup(kit);
  assert.match(markup, /PLP-2026-03-007265-01/); assert.match(markup, /采用报告参数/);
  assert.ok(report.summary.length > 0 && report.simulationNotes.length > 0);
  for (const key of ['polarizationAngleDeg','ellipticityDeg','wavefrontRadiusMm','directionAngleDeg','enabled']) assert.ok(!report.applyFields.includes(key));
  assert.match(markup, /仅填入报告登记的波长、功率、光斑、M²、偏振类型。/);
});
console.log(`${checks} actual 532 report default and persistence checks passed`);
