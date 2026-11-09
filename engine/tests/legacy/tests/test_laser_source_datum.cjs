'use strict';
// Source spectra can be known while a source's mechanical optical datum is not.
// Use isolated catalog fixtures so collecting more laser reports cannot change
// the safety and report-form contract exercised here.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const E = require('../static/optical-engine.js');
const R = require('../static/optical-renderer.js');
const copy = value => JSON.parse(JSON.stringify(value));
let checks = 0;
const test = (name, run) => { run(); checks++; console.log('ok - ' + name); };

const reportFields = ['wavelengthNm', 'powerMw', 'beamDiameterMm', 'beamQualityM2', 'polarizationType'];
const sourceFields = {wavelengthNm: 'optics-wavelength', powerMw: 'optics-power', beamDiameterMm: 'optics-diameter',
  beamQualityM2: 'optics-m2', polarizationType: 'optics-polarization', polarizationAngleDeg: 'optics-polarization-angle',
  ellipticityDeg: 'optics-ellipticity', directionAngleDeg: 'optics-direction', wavefrontRadiusMm: 'optics-wavefront'};
const laser = {
  id: 'qa-unmeasured-source', name: '399 nm · 光口待实测', category: 'laser',
  layout: {
    opticalType: 'source', opticalDatumVerified: false, opticalAxisHeightMm: null,
    opticalSimulationNote: '主光口横向位置与高度待实测。',
    opticalPortsMm: [{xMm: -20, yMm: 10, directionX: -1, directionY: 0, wavelengthNm: 399}],
    opticalDefaults: {elementType: 'source', inserted: true, source: {
      enabled: false, wavelengthNm: 398.90264, powerMw: 1210, beamDiameterMm: .802, beamQualityM2: 1.048,
      polarizationType: 'linear', polarizationAngleDeg: 0, ellipticityDeg: 0,
      directionAngleDeg: 180, wavefrontRadiusMm: null,
    }},
    sourceReport: {title: '399 nm 报告', reportId: 'QA-399', applyFields: reportFields,
      summary: ['实测波长与功率已登记。'], simulationNotes: ['主光口高度和横向位置待实测，暂不追踪。']},
  },
};
const board = {widthMm: 900, heightMm: 600, thicknessMm: 12.7, pitchMm: 25, edgeOffsetMm: 12.5, holeType: 'M6_through', mountingHoles: []};
const instance = optics => ({id: 'source', kitId: laser.id, xMm: 450, yMm: 300, rotationDeg: 0, ...(optics ? {optics} : {})});
const config = (optics, kit = laser) => R.configFor(instance(optics), kit, {}, E, {});
const sceneFor = (optics, kit = laser, heights = []) => R.sceneFor({board, instances: [instance(optics)]}, new Map([[laser.id, kit]]), {}, heights, E, {});

test('unmeasured source keeps report fields for fresh, sparse and old unsupported settings without mutating them', () => {
  const saved = [undefined, {elementType: 'source', source: {enabled: true, powerMw: 150}},
    {elementType: 'unsupported', inserted: false, source: {enabled: true, wavelengthNm: 398.9, wavefrontRadiusMm: -500}}];
  const catalogBefore = copy(laser);
  for (const stored of saved) {
    const before = stored && copy(stored), resolved = config(stored);
    assert.equal(resolved.elementType, 'source');
    assert.equal(resolved.source.enabled, false);
    assert.equal(resolved.source.powerMw, stored?.source.powerMw ?? 1210);
    assert.equal(resolved.source.wavelengthNm, stored?.source.wavelengthNm ?? 398.90264);
    assert.equal(resolved.source.beamQualityM2, 1.048);
    assert.equal(resolved.source.wavefrontRadiusMm, stored?.source.wavefrontRadiusMm ?? null);
    assert.deepEqual(stored, before);
    assert.match(R.sourceReportMarkup(laser), /QA-399/);
  }
  assert.deepEqual(laser, catalogBefore);
});

test('explicit engine source inputs cannot bypass an unmeasured datum, even with a supplied height', () => {
  // Supplying a resolved height isolates the optical-datum guard from the
  // existing null-height guard; a guessed X/Y port must still not launch a ray.
  const scene = sceneFor({elementType: 'source', source: {enabled: true}}, laser,
    [{instanceId: 'source', effectiveAxisHeightMm: 80, heightResolved: true}]);
  assert.equal(scene.elements[0].axisHeightMm, 80);
  assert.equal(scene.elements[0].simulationIssue.code, 'optical_datum_unknown');
  assert.equal(E.createSession(scene).segments.length, 0);
  for (const source of [{instanceId: 'source'}, {instanceId: 'source', enabled: true, powerMw: 1000, wavelengthNm: 399}]) {
    const trace = E.createSession(scene, [source]);
    assert.equal(trace.segments.length, 0); assert.equal(trace.pending.length, 0);
    assert.deepEqual(trace.sourceIds, []);
    assert.ok(trace.warnings.some(w => w.code === 'optical_datum_unknown' && w.instanceId === 'source'));
  }
  // Also check callers who pass enabled=true directly in an already built scene.
  scene.elements[0].optics.source.enabled = true;
  const direct = E.createSession(scene);
  assert.equal(direct.segments.length, 0);
  assert.ok(direct.warnings.some(w => w.code === 'optical_datum_unknown'));
});

test('verified source emission and other unsupported catalog types retain their previous behavior', () => {
  const verified = copy(laser); verified.layout.opticalDatumVerified = true; verified.layout.opticalAxisHeightMm = 80;
  const scene = sceneFor({elementType: 'source', source: {enabled: true}}, verified);
  const trace = E.createSession(scene);
  assert.equal(trace.segments.length, 1); assert.deepEqual(trace.sourceIds, ['source']);
  const reading = E.beamAt(trace.segments[0], 0);
  assert.equal(reading.wavelengthNm, 398.90264); assert.equal(reading.powerMw, 1210);
  assert.equal(reading.beamQualityM2, 1.048); assert.ok(Math.abs(reading.diameterMm - .802) < 1e-12);
  const other = copy(laser); other.layout.opticalType = 'mirror';
  assert.equal(config({elementType: 'mirror', inserted: true}, other).elementType, 'unsupported');
  const noReport = copy(laser); delete noReport.layout.sourceReport;
  assert.equal(config({elementType: 'source', source: {enabled: true}}, noReport).elementType, 'unsupported');
});

// Use the production frontend fixture's minimal DOM, retaining actual form
// rendering, applying, reading and optical normalization code.
const root = path.resolve(__dirname, '..'), harness = {require, __dirname: root, console};
vm.createContext(harness);
const performance = fs.readFileSync(path.join(root, 'test_layout_performance_frontend.cjs'), 'utf8');
vm.runInContext(performance.slice(0, performance.indexOf('{\n  const f=fixture(),e=f.editor')) + '\nglobalThis.makeEnvironment=environment;', harness);
const scripts = ['layout.js', 'optical-engine.js', 'optical-hole-probe.js', 'optical-renderer.js']
  .map(file => fs.readFileSync(path.join(root, 'static', file), 'utf8')).join('\n');
const env = harness.makeEnvironment(scripts), proto = env.Editor.prototype;
const getNode = env.document.getElementById.bind(env.document);
const knownIds = new Set(['optics-type', 'optics-aperture', 'optics-inserted', 'optics-source-enabled',
  'optics-source-report-status', ...Object.values(sourceFields)]);
env.document.getElementById = id => knownIds.has(id) ? getNode(id) : null;
function formFixture(kit = laser) {
  const resolved = config(undefined, kit), target = {kit, config: resolved, simulationIssue: R.catalogSimulationIssue(kit)};
  getNode('optics-type').value = resolved.elementType;
  getNode('optics-aperture').value = String(resolved.clearApertureMm);
  getNode('optics-inserted').checked = resolved.inserted;
  getNode('optics-source-enabled').checked = false;
  for (const [key, id] of Object.entries(sourceFields)) getNode(id).value = resolved.source[key] === null ? '' : String(resolved.source[key]);
  return {_opticalTarget: target};
}

test('unmeasured source form exposes report controls but shows a disabled unchecked emission switch', () => {
  const editor = formFixture(), suggestedStart = copy(editor._opticalTarget.config);
  // openOpticalProperties(start:true) suggests true; the blocked form must
  // still refuse that suggestion while retaining all editable report fields.
  suggestedStart.source.enabled = true;
  const markup = proto.opticalFormMarkup.call(editor, suggestedStart);
  assert.match(markup, /optics-source-use-report/); assert.match(markup, /QA-399/);
  const enabled = markup.match(/<input\b[^>]*id="optics-source-enabled"[^>]*>/)?.[0];
  assert.ok(enabled); assert.match(enabled, /\bdisabled\b/); assert.doesNotMatch(enabled, /\bchecked\b/);
  for (const id of ['optics-power', 'optics-wavelength', 'optics-diameter', 'optics-wavefront']) {
    const input = markup.match(new RegExp('<input\\b[^>]*id="' + id + '"[^>]*>'))?.[0];
    assert.ok(input, id + ' remains available'); assert.doesNotMatch(input, /\bdisabled\b/);
  }
});

test('report application and save retain unknown geometry while preserving user polarization and wavefront', () => {
  const editor = formFixture(), before = copy(editor._opticalTarget);
  getNode('optics-power').value = '17'; getNode('optics-polarization-angle').value = '37';
  getNode('optics-ellipticity').value = '12'; getNode('optics-wavefront').value = '-600'; getNode('optics-direction').value = '27';
  proto.applyReportedSourceParameters.call(editor);
  assert.equal(getNode('optics-power').value, '1210');
  assert.equal(getNode('optics-polarization-angle').value, '37');
  assert.equal(getNode('optics-ellipticity').value, '12');
  assert.equal(getNode('optics-wavefront').value, '-600'); assert.equal(getNode('optics-direction').value, '27');
  assert.deepEqual(editor._opticalTarget, before, 'the report action only edits form fields until Save');
  const saved = copy(proto.readOpticalForm.call(editor)), reopened = config(saved);
  assert.equal(saved.source.powerMw, 1210); assert.equal(saved.source.enabled, false);
  assert.equal(reopened.elementType, 'source'); assert.equal(reopened.source.wavefrontRadiusMm, -600);
  assert.equal(reopened.source.polarizationAngleDeg, 37);
  const scene = sceneFor(saved); assert.equal(scene.elements[0].axisHeightMm, null);
  assert.equal(scene.elements[0].simulationIssue.code, 'optical_datum_unknown');
  assert.equal(E.createSession(scene, [{instanceId: 'source'}]).segments.length, 0);
});

test('legacy report actions never replace a saved wavefront without explicit applyFields opt-in', () => {
  for (const fields of [undefined, reportFields, [], 'wavefrontRadiusMm']) {
    const kit = copy(laser); kit.layout.opticalDefaults.source.wavefrontRadiusMm = 850;
    if (fields === undefined) delete kit.layout.sourceReport.applyFields;
    else kit.layout.sourceReport.applyFields = fields;
    const editor = formFixture(kit); getNode('optics-wavefront').value = '-600';
    proto.applyReportedSourceParameters.call(editor);
    assert.equal(getNode('optics-wavefront').value, '-600');
    assert.doesNotMatch(R.sourceReportMarkup(kit), /推算窗面波前/);
  }
});

test('explicit report opt-in applies a finite inferred wavefront or an intentional plane-wavefront null', () => {
  for (const radius of [850, -600, null]) {
    const kit = copy(laser); kit.layout.opticalDefaults.source.wavefrontRadiusMm = radius;
    kit.layout.sourceReport.applyFields = [...reportFields, 'wavefrontRadiusMm', 'notARealSourceField'];
    const editor = formFixture(kit), before = copy(editor._opticalTarget);
    getNode('optics-wavefront').value = '-77'; getNode('optics-polarization-angle').value = '23';
    proto.applyReportedSourceParameters.call(editor);
    assert.equal(getNode('optics-wavefront').value, radius === null ? '' : String(radius));
    assert.equal(getNode('optics-polarization-angle').value, '23'); assert.equal(getNode('optics-source-enabled').checked, false);
    assert.deepEqual(editor._opticalTarget, before);
    assert.match(R.sourceReportMarkup(kit), /推算窗面波前/);
    assert.doesNotMatch(R.sourceReportMarkup(kit), /保留当前出光开关、偏振角与波前/);
    assert.match(getNode('optics-source-report-status').textContent, /推算窗面波前/);
    assert.equal(proto.readOpticalForm.call(editor).source.wavefrontRadiusMm, radius);
  }
});

console.log(`${checks} source datum and report-wavefront regression checks passed`);
