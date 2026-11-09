'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const codec = require('../static/project-file.js'), shared = require('../static/shared-project.js');
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../catalog.json'), 'utf8'));
let seq = 0;
const options = { catalog, now: '2026-09-29T00:00:00.000Z', newId: () => `optics-${++seq}` };
const board = { widthMm: 600, heightMm: 450, pitchMm: 12.5, edgeOffsetMm: 12.5, thicknessMm: 12.7, holeType: 'M6_through', mountingHoles: [] };
const make = instances => codec.create({ metadata: { name: '光路参数工程' }, catalogVersion: catalog.version,
  layout: { board, instances }, optical: {}, extras: [], moduleQuantities: [], ui: { selectedIds: [], view: null } }, options);
const config = { elementType: 'waveplate', inserted: true, surfaceAngleDeg: -45, pbsHandedness: 'right',
  fastAxisDeg: 22.5, retardanceDeg: 180, designWavelengthNm: 532, focalLengthMm: null, clearApertureMm: 25.4,
  waveplates: [{ inserted: true, fastAxisDeg: 22.5, retardanceDeg: 180, designWavelengthNm: 532 },
    { inserted: true, fastAxisDeg: 45, retardanceDeg: 90, designWavelengthNm: 532 }],
  source: { enabled: true, wavelengthNm: 532, powerMw: 1, beamDiameterMm: 2, polarizationType: 'elliptical',
    polarizationAngleDeg: 20, ellipticityDeg: -15, wavefrontRadiusMm: null, beamQualityM2: 1.2, directionAngleDeg: -90 } };
const source = make([{ id: 'waveplate', kitId: 'waveplate', xMm: 150, yMm: 150, rotationDeg: 90, optics: config }]);
const reopened = codec.parse(JSON.stringify(source), options).project;
assert.deepEqual(reopened.layout.instances[0].optics, config);
assert.notEqual(source.layout.instances[0].optics, config);
assert.notEqual(source.layout.instances[0].optics.source, config.source);
assert.notEqual(source.layout.instances[0].optics.waveplates[0], config.waveplates[0]);
assert.equal(reopened.optical && Object.keys(reopened.optical).length, 0, 'render settings cannot create a purchase selection');
const old = make([{ id: 'old', kitId: 'waveplate', xMm: 150, yMm: 150, rotationDeg: 0 }]);
assert.equal(Object.hasOwn(codec.parse(JSON.stringify(old), options).project.layout.instances[0], 'optics'), false);
console.log('PASS optics full project round-trip, two waveplates, nullable curvature, no default mutation or purchase injection');

const merged = shared.merge(make([]), source, options).project;
const mounted = shared.mountOnBoard(make([]), source, options).project;
const portable = shared.extractBoard(mounted, mounted.layout.subBoards[0].id, options);
const selected = shared.subset(source, ['waveplate'], options);
for (const project of [merged, mounted, portable, selected]) {
  assert.deepEqual(project.layout.instances[0].optics, config);
  assert.notEqual(project.layout.instances[0].optics.source, source.layout.instances[0].optics.source);
}
merged.layout.instances[0].optics.source.wavelengthNm = 780;
mounted.layout.instances[0].optics.waveplates[1].retardanceDeg = 270;
assert.deepEqual(source.layout.instances[0].optics, config);
assert.deepEqual(portable.layout.instances[0].optics, config);
console.log('PASS shared selection, merge, small-board mount/extraction and independent nested optics edits');

const reject = optics => {
  const bad = structuredClone(source); bad.layout.instances[0].optics = optics;
  assert.throws(() => codec.parse(bad, options));
};
for (const bad of [null, [], {}, { elementType: 'mirror' }, { elementType: 'bad', inserted: true },
  { ...config, inserted: 1 }, { ...config, pbsHandedness: 'up' }, { ...config, source: {} },
  { ...config, stepPath: '/etc/passwd' }, { ...config, waveplates: Array.from({ length: 9 }, () => ({ inserted: true })) },
  { ...config, waveplates: [{ inserted: 'true' }] }, { ...config, waveplates: [{ inserted: true, model: 'forged' }] },
  { ...config, source: { enabled: true, assetUrl: 'https://bad' } },
  { ...config, source: { enabled: true, polarizationType: [] } }]) reject(bad);
for (const [key, values] of Object.entries({ surfaceAngleDeg: [3601, true], retardanceDeg: [36001], fastAxisDeg: [-3601],
  designWavelengthNm: [0, 1e6 + 1], clearApertureMm: [0, 10001], focalLengthMm: [0, 1e-8, 1e6 + 1] })) {
  for (const value of [...values, '1', NaN, Infinity]) reject({ ...config, [key]: value });
}
for (const [key, values] of Object.entries({ enabled: [1, null], wavelengthNm: [0, 1e6 + 1], powerMw: [-1, 1e9 + 1],
  beamDiameterMm: [0, 10001], polarizationAngleDeg: [3601], ellipticityDeg: [46, -46],
  wavefrontRadiusMm: [0, 1e-8, 1e12 + 1], beamQualityM2: [.9, 101], directionAngleDeg: [-3601] })) {
  for (const value of [...values, '1', NaN, Infinity]) reject({ ...config, source: { ...config.source, [key]: value } });
}
for (const runtime of ['rays', 'segments', 'pending', 'renderProgress']) reject({ ...config, [runtime]: [] });
console.log('PASS strict bounded schema rejects malformed values, unknown fields, asset/BOM injection and temporary trace progress');

for (const elementType of ['empty', 'mirror', 'pbs', 'waveplate', 'lens', 'coupler', 'source', 'unsupported']) {
  const value = { elementType, inserted: false }, p = structuredClone(source);
  p.layout.instances[0].optics = value;
  assert.deepEqual(codec.parse(p, options).project.layout.instances[0].optics, value);
}
const edges = structuredClone(source), edgeOptics = edges.layout.instances[0].optics;
edgeOptics.focalLengthMm = -50; edgeOptics.waveplates = [];
Object.assign(edgeOptics.source, { enabled: false, powerMw: 0, beamQualityM2: 100, wavefrontRadiusMm: -1e12 });
assert.deepEqual(codec.parse(edges, options).project.layout.instances[0].optics, edgeOptics);
edgeOptics.focalLengthMm = 1e-6; edgeOptics.source.wavefrontRadiusMm = 1e-6;
assert.deepEqual(codec.parse(edges, options).project.layout.instances[0].optics, edgeOptics);
console.log('PASS empty slots, optional defaults, negative lenses and wavefront radius numerical boundaries');

// Exercise the actual editor clipboard/history, not a replacement clone helper.
const vm = require('node:vm'), root = path.resolve(__dirname, '..');
const harnessSource = fs.readFileSync(path.join(root, 'test_layout_performance_frontend.cjs'), 'utf8');
const harness = { require, __dirname: root, console };
vm.createContext(harness);
vm.runInContext(harnessSource.slice(0, harnessSource.indexOf('{\n  const f=fixture(),e=f.editor')) + '\nglobalThis.createFixture=fixture;', harness);
const { editor } = harness.createFixture(1);
editor.instances[0].optics = structuredClone(config);
editor.select('p0'); editor.copySelection();
editor.instances[0].optics.source.wavelengthNm = 780;
const paste = editor.pasteSelection();
const added = editor.instances.find(i => i.id === paste.ids[0]);
assert.deepEqual(JSON.parse(JSON.stringify(added.optics)), config, 'clipboard freezes optics at copy time');
assert.equal(Object.isFrozen(editor.clipboard.instances[0].optics.waveplates[0]), true);
added.optics.waveplates[1].retardanceDeg = 270;
assert.equal(editor.instances[0].optics.waveplates[1].retardanceDeg, 90);
editor.undo();
assert.equal(editor.instances.length, 1);
assert.equal(editor.instances[0].optics.source.wavelengthNm, 780);
editor.redo();
assert.equal(editor.instances.find(i => i.id === paste.ids[0]).optics.waveplates[1].retardanceDeg, 270);
console.log('PASS actual editor copy/paste freezes nested optics and undo/redo preserves independent parameters');
