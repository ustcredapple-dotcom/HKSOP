'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const codec = require('./static/project-file.js');
const clone = value => JSON.parse(JSON.stringify(value));
const now = '2026-09-24T10:00:00.000Z';
const catalog = { version: 'test-v3', kits: [
  { id: 'wave', name: '波片系统', opticalSlots: [{ id: 'wp', type: 'waveplate', quantity: 1 }] },
  { id: 'mirror', name: '反射镜', opticalSlots: [{ id: 'mirror', type: 'mirror', quantity: 1 }] },
  { id: 'inactive', name: '暂未摆放', opticalSlots: [{ id: 'mirror', type: 'mirror', quantity: 1 }] },
  { id: 'module', name: '独立模块', layout: { placementAllowed: false }, opticalSlots: [{ id: 'wp', type: 'waveplate', quantity: 2 }] }
] };
const options = { catalog, now, validateBoard: b => b };
function raw() {
  return {
    metadata: { name: '光路实验 A', notes: '保留部分选型\n第二行', createdAt: '2026-09-23T08:00:00.000Z' }, catalogVersion: catalog.version,
    layout: { board: { widthMm: 350, heightMm: 225, pitchMm: 12.5, edgeOffsetMm: 12.5, thicknessMm: 12.7, holeType: 'M6_through', mountingHoles: [{ columnIndex: 0, rowIndex: 1 }, { columnIndex: 26, rowIndex: 1 }, { columnIndex: 0, rowIndex: 15 }, { columnIndex: 26, rowIndex: 15 }] },
      instances: [{ id: 'a1', kitId: 'wave', xMm: -20, yMm: 25, rotationDeg: 270 }, { id: 'a2', kitId: 'wave', xMm: -20, yMm: 25, rotationDeg: 0 }, { id: 'm1', kitId: 'mirror', xMm: 200, yMm: 50, rotationDeg: 90 }] },
    optical: { 'a1::wp': { model: '', wavelength: '532', opticalType: 'half-wave', kind: 'standard' }, 'a2::wp': { model: 'W-780', wavelength: '780', kind: 'lubang', notes: '单独选型' }, 'm1::mirror': {}, 'module:module::wp': { model: '', wavelength: '1550' } },
    extras: [{ id: 'global', kitId: null, kind: 'standard', name: '螺钉', model: '', quantity: 4, unit: '个', notes: '' }, { id: 'instance-extra', kitId: 'wave', instanceId: 'a1', kind: 'standard', name: '实例垫片', quantity: 2, unit: '个' }, { id: 'inactive-extra', kitId: 'inactive', kind: 'lubang', name: '暂未使用配件', quantity: 3, unit: '片', model: 'DRAFT-1' }],
    moduleQuantities: [['module', 3]], ui: { mountingSelection: { rowParity: 'even', columnParity: 'odd' }, view: { x: -45, y: -30, w: 700, h: 500 }, selectedIds: ['a2', 'm1'] }
  };
}
function rejected(value, code, opts = options) {
  assert.throws(() => codec.parse(value, opts), error => error instanceof codec.ProjectFileError && (!code || error.code === code));
}
function project() { return codec.create(raw(), options); }
function extra(overrides = {}) { return { id: 'e1', kitId: 'wave', instanceId: 'a1', slotId: 'wp', kind: 'lubang', name: '波片', model: '', quantity: 1, unit: '片', wavelength: '632.8', opticalType: '', notes: '', ...overrides }; }

test('create and parse round-trip all editable data, independent of collisions', () => {
  const input = raw(), before = clone(input), saved = codec.create(input, options);
  assert.deepEqual(input, before);
  assert.equal(saved.format, 'zzlab-optics-project'); assert.equal(saved.version, 1);
  assert.equal(saved.metadata.createdAt, input.metadata.createdAt); assert.equal(saved.metadata.updatedAt, now);
  const parsed = codec.parse(JSON.stringify(saved), options);
  assert.equal(parsed.legacy, false); assert.deepEqual(parsed.warnings, []); assert.deepEqual(parsed.project, saved);
  assert.deepEqual(saved.optical, input.optical); assert.deepEqual(saved.extras, input.extras);
  assert.deepEqual(saved.moduleQuantities, [['module', 3]]); assert.equal(saved.layout.instances[0].xMm, -20);
  parsed.project.optical['a1::wp'].wavelength = '999'; assert.equal(saved.optical['a1::wp'].wavelength, '532');
});
test('UMD runs without DOM and exposes browser API', () => {
  const sandbox = {}; vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(__dirname + '/static/project-file.js', 'utf8'), sandbox);
  assert.equal(typeof sandbox.ZZLabProjectFile.create, 'function'); assert.equal(sandbox.ZZLabProjectFile.EXTENSION, '.zzoptics.json');
});
test('legacy localStorage version 2 keeps modules, empty optical fields, and inactive extras', () => {
  const r = raw(); const old = { version: 2, layout: r.layout, extras: r.extras, optical: r.optical, moduleQuantities: r.moduleQuantities, mountingSelection: r.ui.mountingSelection };
  const parsed = codec.parse(old, options);
  assert.equal(parsed.legacy, true); assert.deepEqual(parsed.project.optical, r.optical); assert.deepEqual(parsed.project.extras, r.extras);
  assert.deepEqual(parsed.project.moduleQuantities, r.moduleQuantities); assert.deepEqual(parsed.project.ui.mountingSelection, r.ui.mountingSelection);
});
test('legacy conflicting editable data is rejected instead of silently choosing a copy', () => {
  const r = raw(); rejected({ layout: r.layout, board: r.layout.board }, 'conflicting_layout');
  rejected({ layout: r.layout, moduleQuantities: null, items: [{ kitId: 'module', quantity: 2 }] }, 'invalid_shape');
  rejected({ layout: r.layout, ui: r.ui, mountingSelection: { rowParity: 'any', columnParity: 'any' } }, 'conflicting_ui');
  assert.deepEqual(codec.parse({ layout: r.layout, ui: r.ui, mountingSelection: r.ui.mountingSelection }, options).project.ui.mountingSelection, r.ui.mountingSelection);
});
test('legacy layout JSON migrates partial optical extras and retains instance accessory extras', () => {
  const r = raw(), input = { catalogVersion: 'test-old', layout: r.layout, extras: [extra(), r.extras[1]], ui: r.ui,
    boardSpecification: { material: 'FAKE', sourceUrl: 'javascript:alert(1)' }, layoutValidation: { valid: true } };
  const { project: parsed, warnings } = codec.parse(input, options);
  assert.equal(parsed.optical['a1::wp'].model, ''); assert.equal(parsed.optical['a1::wp'].wavelength, '632.8');
  assert.deepEqual(parsed.extras, [r.extras[1]]); assert.equal(warnings.length, 1);
  assert.equal('boardSpecification' in parsed, false); assert.equal('material' in parsed.layout.board, false);
});
test('legacy kit-scoped optical extras expand per instance without multiplying quantity', () => {
  const e = extra(); delete e.instanceId;
  const parsed = codec.parse({ layout: raw().layout, extras: [e] }, options).project;
  assert.equal(parsed.optical['a1::wp'].quantity, 1); assert.equal(parsed.optical['a2::wp'].quantity, 1); assert.deepEqual(parsed.extras, []);
});
test('legacy standalone module optics and quantity survive import', () => {
  const e = extra({ kitId: 'module', quantity: 2 }); delete e.instanceId;
  const parsed = codec.parse({ layout: raw().layout, extras: [e], moduleQuantities: [['module', 4]] }, options).project;
  assert.equal(parsed.optical['module:module::wp'].wavelength, '632.8'); assert.equal(parsed.optical['module:module::wp'].quantity, 2); assert.deepEqual(parsed.moduleQuantities, [['module', 4]]);
});
test('legacy inactive kit-scoped optical templates remain preserved extras', () => {
  const e = extra({ kitId: 'inactive', slotId: 'mirror', opticalType: '' }); delete e.instanceId;
  const parsed = codec.parse({ layout: raw().layout, extras: [e] }, options).project;
  assert.deepEqual(parsed.extras, [e]);
});
test('legacy raw layouts alone may omit rotation; new projects cannot', () => {
  const layout = raw().layout; delete layout.instances[0].rotationDeg;
  assert.equal(codec.parse(layout, options).project.layout.instances[0].rotationDeg, 0);
  const p = project(); delete p.layout.instances[0].rotationDeg; rejected(p, 'missing_field');
  layout.instances[0].rotationDeg = 45; rejected(layout, 'invalid_value');
});
test('existing mounting holes becoming physically invalid remain editable drafts', () => {
  const r = raw(); r.layout.board.widthMm = 50; r.layout.board.heightMm = 50; r.layout.board.thicknessMm = 3;
  const saved = codec.create(r, options); assert.deepEqual(saved.layout.board.mountingHoles, r.layout.board.mountingHoles);
  assert.deepEqual(codec.parse(saved, options).project.layout.board, saved.layout.board);
  r.layout.board.mountingHoles = [{ columnIndex: 0, rowIndex: 0 }, { columnIndex: 1, rowIndex: 0 }, { columnIndex: 0, rowIndex: 1 }, { columnIndex: 1, rowIndex: 1 }];
  assert.equal(codec.create(r, options).layout.board.mountingHoles.length, 4, '25 mm spacing is a production check, not a file-format check');
});
test('unknown format or future version never falls back to legacy', () => {
  const p = project(); rejected({ ...p, format: 'third-party-layout' }, 'unsupported_format');
  rejected({ ...p, version: 2 }, 'unsupported_version'); delete p.version; rejected(p, 'unsupported_version');
  rejected({ version: 99, layout: raw().layout }, 'unsupported_version');
});
test('unknown or forged fields and source-asset URLs are rejected', () => {
  let p = project(); p.assets = { step: '/etc/passwd' }; rejected(p, 'unknown_field');
  p = project(); p.layout.board.material = 'fake'; rejected(p, 'unknown_field');
  p = project(); p.layout.instances[0].topViewUrl = 'https://evil.test/img'; rejected(p, 'unknown_field');
  p = project(); p.catalogReferenced[0].sourceUrl = 'https://evil.test'; rejected(p, 'unknown_field');
});
test('unknown kits and unknown slots are rejected in every reference surface', () => {
  for (const alter of [p => p.layout.instances[0].kitId = 'missing', p => p.extras[0].kitId = 'missing', p => p.moduleQuantities[0][0] = 'missing', p => p.catalogReferenced[0].id = 'missing']) { const p = project(); alter(p); rejected(p, 'unknown_kit'); }
  const p = project(); p.optical['a1::missing'] = {}; rejected(p, 'unknown_slot');
});
test('duplicate instances, extras, module counts, and selected IDs fail atomically', () => {
  for (const alter of [p => p.layout.instances.push(clone(p.layout.instances[0])), p => p.extras.push(clone(p.extras[0])), p => p.moduleQuantities.push(['module', 1]), p => p.ui.selectedIds.push('a2')]) { const p = project(); alter(p); const before = clone(p); rejected(p, 'duplicate_id'); assert.deepEqual(p, before); }
});
test('unknown instance associations never disappear silently', () => {
  const p = project(); p.optical['deleted::wp'] = {}; rejected(p, 'unknown_instance');
  for (const alter of [p => p.extras[1].instanceId = 'deleted', p => p.extras[1].kitId = 'mirror', p => p.ui.selectedIds = ['deleted']]) { const q = project(); alter(q); rejected(q, 'unknown_instance'); }
});
test('bad finite coordinates, rotations and module quantities are rejected', () => {
  for (const bad of [NaN, Infinity, -Infinity, '25', true]) { const p = project(); p.layout.instances[0].xMm = bad; rejected(p); }
  for (const bad of [45, -90, 360, '90', null]) { const p = project(); p.layout.instances[0].rotationDeg = bad; rejected(p, 'invalid_value'); }
  for (const bad of [0, -1, 1.5, 10000, '2', true]) { const p = project(); p.moduleQuantities[0][1] = bad; rejected(p, 'invalid_number'); }
});
test('bad board format and unsafe core dimensions are rejected', () => {
  for (const change of [{ widthMm: '350' }, { widthMm: 24 }, { heightMm: 3001 }, { pitchMm: null }, { pitchMm: 3 }, { edgeOffsetMm: 1 }, { thicknessMm: null }, { holeType: null }, { holeDiameterMm: 6 }, { thread: 'M8' }, { mountingHoles: null }, { mountingHoles: [] }]) {
    const p = project(); Object.assign(p.layout.board, change);
    if ('mountingHoles' in change && Array.isArray(change.mountingHoles)) { p.layout.board.widthMm = 3000; p.layout.board.heightMm = 3000; }
    rejected(p);
  }
  const p = project(); p.layout.board.holeType = 'plain_through'; p.layout.board.thread = 'M6x1.0'; rejected(p, 'invalid_board');
});
test('mounting-hole structure is still strict', () => {
  for (const change of [holes => holes.pop(), holes => holes[0].columnIndex = -1, holes => holes[0].rowIndex = 1.5, holes => holes[1] = clone(holes[0]), holes => holes[0].rowIndex = 1000001]) {
    const p = project(); change(p.layout.board.mountingHoles); rejected(p);
  }
});
test('null object/array fields cannot silently turn into defaults', () => {
  for (const field of ['metadata', 'optical', 'extras', 'moduleQuantities', 'ui']) { const p = project(); p[field] = null; rejected(p); }
  const p = project(); p.ui.selectedIds = null; rejected(p); p.ui.selectedIds = []; p.ui.mountingSelection = null; rejected(p);
});
test('invalid optical types, quantities, module targets and duplicate entries fail', () => {
  let p = project(); p.optical['m1::mirror'] = { opticalType: 'quarter-wave' }; rejected(p, 'invalid_optical_type');
  p = project(); p.optical['a1::wp'].quantity = 2; rejected(p, 'invalid_optical_quantity');
  p = project(); p.optical['module:wave::wp'] = {}; rejected(p, 'invalid_optical_target');
  p = project(); p.moduleQuantities = [['wave', 2]]; rejected(p, 'invalid_module');
  const e = extra(); rejected({ layout: raw().layout, extras: [e, { ...e, id: 'second' }] }, 'duplicate_optical');
  rejected({ layout: raw().layout, optical: { 'a1::wp': { wavelength: '532' } }, extras: [e] }, 'conflicting_optical');
});
test('view state must be finite and usable; mounting parity cannot be guessed', () => {
  for (const value of [0, -1, Number.MIN_VALUE, Infinity]) { const p = project(); p.ui.view.w = value; rejected(p, 'invalid_number'); }
  const p = project(); p.ui.mountingSelection.rowParity = 'unknown'; rejected(p, 'invalid_value');
});
test('oversized UTF-8 files, fields and instance arrays are rejected', () => {
  rejected('{"notes":"' + '中'.repeat(Math.ceil(codec.MAX_BYTES / 3)) + '"}', 'file_too_large');
  let p = project(); p.metadata.notes = 'x'.repeat(20001); rejected(p, 'invalid_text');
  p = project(); p.layout.instances = Array.from({ length: 501 }, (_, index) => ({ id: 'i' + index, kitId: 'wave', xMm: index, yMm: 0, rotationDeg: 0 })); rejected(p, 'invalid_shape');
});
test('prototype keys and non-JSON shapes cannot execute or mutate data', () => {
  for (const key of ['__proto__', 'constructor', 'prototype']) rejected('{"layout":{"' + key + '":{} }}', 'unsafe_key');
  const value = Object.create({ malicious: true }); value.layout = raw().layout; rejected(value, 'unsafe_shape');
  let accessed = false; const getter = {}; Object.defineProperty(getter, 'layout', { enumerable: true, get() { accessed = true; throw Error(); } }); rejected(getter, 'unsafe_shape'); assert.equal(accessed, false);
  const cycle = {}; cycle.self = cycle; rejected(cycle, 'invalid_shape');
  const p = project(); p.extras = [,]; rejected(p, 'invalid_shape');
  assert.equal({}.malicious, undefined);
});
test('board callback cannot mutate canonical state and failure prevents import', () => {
  const saved = codec.create(raw(), { ...options, validateBoard: b => { b.widthMm = 1; return b; } }); assert.equal(saved.layout.board.widthMm, 350);
  rejected(saved, 'invalid_board', { ...options, validateBoard: () => false });
});
test('invalid JSON, empty root, and missing catalog fail with useful error codes', () => {
  rejected('nope', 'invalid_json'); rejected('null', 'invalid_shape'); rejected('[]', 'invalid_shape');
  rejected(project(), 'catalog_required', {});
});
test('duplicate JSON keys including escaped aliases cannot silently discard selections', () => {
  rejected('{"optical":{},"optical":{"a1::wp":{"wavelength":"532"}}}', 'duplicate_key');
  rejected('{"optical":{"a1::wp":{"model":"A","mo\\u0064el":"B"}}}', 'duplicate_key');
  const saved = project(); saved.metadata.notes = 'Quoted "text", slash \\ and { JSON-looking content }';
  assert.deepEqual(codec.parse(JSON.stringify(saved), options).project, saved);
});
test('real catalog sample converts and round-trips without trusting derived specifications', () => {
  const real = JSON.parse(fs.readFileSync(__dirname + '/catalog.json', 'utf8'));
  const saved = JSON.parse(fs.readFileSync(__dirname + '/../../outputs/ZZLab光路套件网页交付/示例_精细轮廓与四角沉孔.json', 'utf8'));
  const parsed = codec.parse(saved, { catalog: real, now }).project;
  assert.equal(parsed.layout.instances.length, 2); assert.equal(parsed.layout.board.mountingHoles.length, 4);
  assert.equal('boardSpecification' in parsed, false);
  assert.deepEqual(codec.parse(JSON.stringify(parsed), { catalog: real, now }).project, parsed);
});
