'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const codec = require('../static/project-file.js'), shared = require('../static/shared-project.js');
const stages = require('../static/moving-stages.js'), registered = require('../static/registered-boards.js');
const clone = value => JSON.parse(JSON.stringify(value));
const CAPABILITY = 'zzlab-collision-overrides-v1';
const kit = { id: 'optic', name: '测试光学元件', components: [], layout: {
  topViewUrl: '/optic.svg', widthMm: 10, heightMm: 10, anchorXMm: 5, anchorYMm: 5,
  baseBoundsMm: { xMin: -5, xMax: 5, yMin: -5, yMax: 5 }, mountingHoleOffsetsMm: [{ xMm: 0, yMm: 0 }]
} };
const live = JSON.parse(fs.readFileSync(path.join(__dirname, '../catalog.json'), 'utf8'));
const moduleRecord = live.stageModules[0];
const catalog = { version: 'collision-override-tests', kits: [kit], components: [], stageModules: [moduleRecord],
  registeredBoards: live.registeredBoards.filter(row => row.id === moduleRecord.runtime.topBoardId) };
let serial = 0;
const options = { catalog, now: '2026-10-06T08:00:00.000Z', newId: kind => `${kind}-copy-${++serial}` };
const board = { widthMm: 600, heightMm: 450, pitchMm: 12.5, edgeOffsetMm: 12.5, thicknessMm: 12.7, holeType: 'M6_through', mountingHoles: [] };
const instance = (id, boardId) => ({ id, kitId: kit.id, xMm: 25, yMm: 25, rotationDeg: 0, ...(boardId ? { boardId } : {}) });
const pair = (a, b) => ({ instanceIds: [a, b] });
const key = row => JSON.stringify([...row.instanceIds].sort());
function raw(layout = {}) { return { metadata: { name: '碰撞人工确认' }, layout: { board: clone(board), instances: ['a', 'b', 'c'].map(id => instance(id)), ...layout }, optical: {}, extras: [], moduleQuantities: [], ui: { selectedIds: [], view: null } }; }
function project(layout) { return codec.create(raw(layout), options); }
function stagePlate() {
  return { id: 'stage', name: moduleRecord.name,
    board: registered.normalizeBoard({ registeredBoardId: moduleRecord.runtime.topBoardId, registeredBoardRevision: moduleRecord.revision }, catalog),
    ...stages.topAtFixed({ xMm: 150, yMm: 150, rotationDeg: 90 }, moduleRecord, 1.25),
    stageMotion: { moduleId: moduleRecord.id, revision: moduleRecord.revision, qMm: 1.25 } };
}

test('create and JSON import preserve canonical instance-pair exemptions without changing input', () => {
  const input = raw({ collisionOverrides: [pair('c', 'b'), pair('b', 'a')] }), before = clone(input);
  const saved = codec.create(input, options);
  assert.deepEqual(input, before);
  assert.deepEqual(saved.layout.collisionOverrides, [pair('a', 'b'), pair('b', 'c')]);
  assert.deepEqual(saved.requires, [CAPABILITY]);
  assert.deepEqual(codec.parse(JSON.stringify(saved), options).project, saved);
  saved.layout.collisionOverrides[0].instanceIds[0] = 'changed';
  assert.deepEqual(input, before, 'canonical output must not alias input arrays');
});

test('strict codec rejects malformed, duplicate, forged and stale instance pairs', () => {
  const invalid = [null, {}, 'a,b', [null], [[]], [{}], [{ instanceIds: null }], [{ instanceIds: 'a,b' }],
    [pair('a', 'a')], [pair('a', 'missing')], [pair('a', '')], [pair('a', 3)],
    [{ instanceIds: [] }], [{ instanceIds: ['a'] }], [{ instanceIds: ['a', 'b', 'c'] }],
    [{ instanceIds: ['a', 'b'], kitId: 'optic' }], [{ instanceIds: ['a', 'b'], allowAll: true }],
    [pair('a', 'b'), pair('a', 'b')], [pair('a', 'b'), pair('b', 'a')]];
  for (const collisionOverrides of invalid) {
    assert.throws(() => project({ collisionOverrides }), codec.ProjectFileError);
    const imported = project(); imported.layout.collisionOverrides = collisionOverrides; imported.requires = [CAPABILITY];
    assert.throws(() => codec.parse(imported, options), codec.ProjectFileError);
  }
  const stale = project({ collisionOverrides: [pair('a', 'b')] });
  stale.layout.instances = stale.layout.instances.filter(row => row.id !== 'b');
  assert.throws(() => codec.parse(stale, options), error => error.code === 'unknown_instance');
});

test('nonempty exemptions require explicit import capability, including legacy imports', () => {
  const saved = project({ collisionOverrides: [pair('a', 'b')] });
  for (const requires of [undefined, [], [stages.CAPABILITY]]) {
    const incoming = clone(saved);
    if (requires === undefined) delete incoming.requires; else incoming.requires = requires;
    assert.throws(() => codec.parse(incoming, options), error => error.code === 'missing_capability');
    assert.ok(codec.create(incoming, options).requires.includes(CAPABILITY), 'create declares supported capability automatically');
  }
  const legacy = raw({ collisionOverrides: [pair('a', 'b')] });
  assert.throws(() => codec.parse(legacy, options), error => error.code === 'missing_capability');
  legacy.requires = [CAPABILITY];
  assert.deepEqual(codec.parse(legacy, options).project.layout.collisionOverrides, [pair('a', 'b')]);
  for (const requires of [[CAPABILITY, CAPABILITY], [CAPABILITY, 'unknown'], [true], null]) {
    assert.throws(() => codec.parse({ ...saved, requires }, options), codec.ProjectFileError);
  }
});

test('old projects and explicit empty overrides do not add new capability requirements', () => {
  const old = project();
  assert.equal(old.requires, undefined);
  assert.equal(old.layout.collisionOverrides, undefined);
  assert.deepEqual(codec.parse(JSON.stringify(old), options).project, old);
  const empty = project({ collisionOverrides: [] });
  assert.equal(empty.requires, undefined);
  assert.deepEqual(codec.parse(empty, options).project.layout.collisionOverrides, []);
});

test('10000 unique exemptions are supported and the next pair is rejected', () => {
  assert.equal(codec.MAX_COLLISION_OVERRIDES, 10000);
  const instances = Array.from({ length: 142 }, (_, index) => instance(`i${index}`));
  const rows = [];
  for (let a = 0; a < instances.length; a++) for (let b = a + 1; b < instances.length; b++) rows.push(pair(instances[a].id, instances[b].id));
  const valid = project({ instances, collisionOverrides: rows.slice(0, 10000) });
  assert.equal(codec.parse(JSON.stringify(valid), options).project.layout.collisionOverrides.length, 10000);
  assert.throws(() => project({ instances, collisionOverrides: rows.slice(0, 10001) }), codec.ProjectFileError);
});

test('shared whole/selected scopes retain only exemptions with both endpoints retained', () => {
  const source = project({ collisionOverrides: [pair('a', 'b'), pair('a', 'c')] }), before = clone(source);
  assert.deepEqual(shared.subset(source, null, options).layout.collisionOverrides, source.layout.collisionOverrides);
  assert.deepEqual(shared.subset(source, ['a', 'b'], options).layout.collisionOverrides, [pair('a', 'b')]);
  assert.deepEqual(shared.subset(source, ['a'], options).layout.collisionOverrides, []);
  assert.deepEqual(source, before);
});

test('ordinary board extraction drops cross-board exemptions and keeps local pair identity', () => {
  const source = project({ subBoards: [{ id: 'small', name: '小板', board: clone(board), xMm: 0, yMm: 0, rotationDeg: 0 }],
    instances: [instance('a', 'small'), instance('b', 'small'), instance('c')], collisionOverrides: [pair('a', 'b'), pair('a', 'c')] });
  const before = clone(source), extracted = shared.extractBoard(source, 'small', options);
  assert.deepEqual(extracted.layout.collisionOverrides, [pair('a', 'b')]);
  assert.ok(extracted.layout.instances.every(row => row.boardId === undefined));
  assert.equal(extracted.layout.subBoards, undefined);
  assert.deepEqual(source, before);
});

test('merge remaps incoming IDs even when original IDs collide and never waives cross-copy pairs', () => {
  const target = project({ instances: [instance('a'), instance('b')], collisionOverrides: [pair('a', 'b')] });
  const source = project({ instances: [instance('a'), instance('b')], collisionOverrides: [pair('a', 'b')] });
  const before = clone([target, source]), first = shared.merge(target, source, options), second = shared.merge(first.project, source, options);
  const expected = [pair('a', 'b')];
  for (const result of [first, second]) {
    const map = new Map(result.mapping.map(row => [row.fromId, row.toId]));
    expected.push(pair(map.get('a'), map.get('b')));
  }
  assert.deepEqual(second.project.layout.collisionOverrides.map(key).sort(), expected.map(key).sort());
  assert.equal(second.project.layout.collisionOverrides.length, 3);
  assert.deepEqual([target, source], before);
});

test('mounting copies of ordinary modules retains existing and remaps only within each new board', () => {
  const target = project({ subBoards: [], instances: [instance('a'), instance('b')], collisionOverrides: [pair('a', 'b')] });
  const source = project({ instances: [instance('a'), instance('b')], collisionOverrides: [pair('a', 'b')] });
  const first = shared.mountOnBoard(target, source, options), second = shared.mountOnBoard(first.project, source, options);
  assert.equal(second.project.layout.collisionOverrides.length, 3);
  for (const result of [first, second]) {
    const own = new Set(result.insertedIds);
    const rows = second.project.layout.collisionOverrides.filter(row => row.instanceIds.some(id => own.has(id)));
    assert.equal(rows.length, 1);
    assert.ok(rows[0].instanceIds.every(id => own.has(id)));
    assert.deepEqual(shared.extractBoard(second.project, result.boardId, options).layout.collisionOverrides, rows);
  }
  assert.deepEqual(target.layout.collisionOverrides, [pair('a', 'b')]);
});

test('motion and collision capabilities coexist through stage extraction, mounting and round trip', () => {
  const source = project({ subBoards: [stagePlate()], instances: [instance('a', 'stage'), instance('b', 'stage'), instance('c')],
    collisionOverrides: [pair('a', 'b'), pair('a', 'c')] });
  assert.deepEqual(source.requires, [stages.CAPABILITY, CAPABILITY]);
  for (const requires of [[stages.CAPABILITY], [CAPABILITY]]) assert.throws(() => codec.parse({ ...source, requires }, options), error => error.code === 'missing_capability');
  for (const extracted of [shared.extractBoard(source, 'stage', options), shared.subset(source, ['a', 'b'], options)]) {
    assert.deepEqual(extracted.layout.collisionOverrides, [pair('a', 'b')]);
    assert.deepEqual(extracted.requires, [stages.CAPABILITY, CAPABILITY]);
    const target = project({ subBoards: [], instances: [instance('old-a'), instance('old-b')], collisionOverrides: [pair('old-a', 'old-b')] });
    const mounted = shared.mountOnBoard(target, extracted, options);
    assert.equal(mounted.project.layout.collisionOverrides.length, 2);
    const map = new Map(mounted.mapping.map(row => [row.fromId, row.toId]));
    assert.ok(mounted.project.layout.collisionOverrides.some(row => key(row) === key(pair(map.get('a'), map.get('b')))));
    assert.equal(mounted.project.layout.subBoards[0].stageMotion.qMm, 1.25);
    assert.deepEqual(codec.parse(JSON.stringify(mounted.project), options).project, mounted.project);
  }
});
