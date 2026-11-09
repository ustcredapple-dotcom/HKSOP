'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const { Engine, EPS } = require('./static/collision-engine.js');
const original = fs.readFileSync(path.join(__dirname, '../perf-baseline/layout.js'), 'utf8');
const context = { window: {}, Map, Set };
vm.createContext(context);
vm.runInContext(original.replace('  class BreadboardEditor {', '  window.OracleGeometry={polygonsTouch,circleTouchesPolygon};\n  class BreadboardEditor {'), context);
const Editor = context.window.BreadboardEditor, oracleGeometry = context.window.OracleGeometry;
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, 'catalog.json'), 'utf8'));
const realKits = new Map(catalog.kits.map(kit => [kit.id, kit]));
const allowed = catalog.kits.filter(kit => kit.layout?.placementAllowed !== false);
const copy = x => JSON.parse(JSON.stringify(x));
function editor(kits, instances = []) { const e = Object.create(Editor.prototype); e.kits = kits; e.instances = instances; e.board = { widthMm: 350, heightMm: 225, edgeOffsetMm: 12.5, pitchMm: 12.5, thicknessMm: 12.7, mountingHoles: [] }; return e; }
function oracle(kits, instances) {
  const e = editor(kits, instances), shape = instances.map(i => ({ polygons: e.worldPolygons(i), bounds: e.worldBounds(i) })), pairs = [];
  for (let j = 0; j < instances.length; j++) for (let i = 0; i < j; i++) {
    const a = shape[i], b = shape[j];
    if (a.bounds.xMin <= b.bounds.xMax + EPS && a.bounds.xMax >= b.bounds.xMin - EPS && a.bounds.yMin <= b.bounds.yMax + EPS && a.bounds.yMax >= b.bounds.yMin - EPS && a.polygons.some(p => b.polygons.some(q => oracleGeometry.polygonsTouch(p, q)))) pairs.push([instances[i].id, instances[j].id]);
  }
  return pairs;
}
const placed = (id, kitId, xMm = 0, yMm = 0, rotationDeg = 0) => ({ id, kitId, xMm, yMm, rotationDeg });
function polygonKit(id, polygons) { return { id, name: id, layout: { widthMm: 100, heightMm: 100, anchorXMm: 50, anchorYMm: 50, collisionPolygonsMm: polygons.map(p => p.map(([xMm, yMm]) => ({ xMm, yMm }))) } }; }
const rectangle = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
function random(seed = 8192) { return () => { seed = (1664525 * seed + 1013904223) >>> 0; return seed / 2 ** 32; }; }
function fixture(count, mode = 'clustered') {
  return Array.from({ length: count }, (_, n) => {
    const cluster = Math.floor(n / 8), within = n % 8;
    const x = mode === 'sparse' ? 100 + (n % 16) * 200 : 100 + (cluster % 8) * 250 + (within % 4) * 25;
    const y = mode === 'sparse' ? 100 + Math.floor(n / 16) * 200 : 100 + Math.floor(cluster / 8) * 250 + Math.floor(within / 4) * 25;
    return placed('i' + n, allowed[n % allowed.length].id, x, y, (n % 4) * 90);
  });
}

test('all real catalog projections match old world coordinates in all quarter turns', () => {
  const engine = new Engine({ kits: realKits }), e = editor(realKits);
  for (const kit of catalog.kits) for (const angle of [0, 90, 180, 270]) {
    const instance = placed(kit.id, kit.id, -37.5, 212.5, angle), world = engine.world(instance);
    assert.deepEqual(world.polygons, copy(e.worldPolygons(instance)));
    assert.deepEqual(world.bounds, copy(e.worldBounds(instance)));
  }
});
test('actual PBS/motor bounding-box overlap remains clear until contours really intersect', () => {
  const instances = [placed('pbs', 'pbs-adjustable', 37.5, 187.5, 270), placed('motor', 'motor-05-45', 37.5, 137.5, 90)];
  const engine = new Engine({ kits: realKits }); assert.deepEqual(engine.update(instances).pairs, []);
  instances[1].yMm = 162.5; assert.deepEqual(engine.update(instances).pairs, [['pbs', 'motor']]);
  instances[1].yMm = 137.5; assert.deepEqual(engine.update(instances).pairs, []);
});
test('concave voids and disconnected loops are not filled by their bounds', () => {
  const kits = new Map([
    ['l', polygonKit('l', [[[0, 0], [40, 0], [40, 10], [10, 10], [10, 40], [0, 40]]])],
    ['small', polygonKit('small', [rectangle(0, 0, 5, 5)])],
    ['separate', polygonKit('separate', [rectangle(-40, -5, -30, 5), rectangle(30, -5, 40, 5)])]
  ]);
  const engine = new Engine({ kits });
  for (const instances of [[placed('a', 'l'), placed('b', 'small', 20, 20)], [placed('a', 'separate'), placed('b', 'small')], [placed('a', 'l'), placed('b', 'small', 8, 20)], [placed('a', 'separate'), placed('b', 'small', 33, 0)]]) assert.deepEqual(engine.update(instances).pairs, oracle(kits, instances));
});
test('edge contact, vertex contact, containment, epsilon gaps and rotations match exact old rules', () => {
  const kit = polygonKit('box', [rectangle(0, 0, 10, 10)]), kits = new Map([['box', kit]]), engine = new Engine({ kits });
  for (const gap of [-EPS, 0, EPS / 2, EPS, EPS * 1.01, EPS * 2]) for (const angle of [0, 90, 180, 270]) for (const y of [0, 10, 10 + EPS / 2, 2]) {
    const instances = [placed('a', 'box'), placed('b', 'box', 10 + gap, y, angle)]; assert.deepEqual(engine.update(instances).pairs, oracle(kits, instances), JSON.stringify(instances));
  }
  assert.deepEqual(engine.update([placed('a', 'box'), placed('b', 'box', 1, 1)]).pairs, [['a', 'b']]);
});
test('random real contour cases and all moving poses agree with the previous brute-force oracle', () => {
  const rng = random(99421), engine = new Engine({ kits: realKits });
  for (let round = 0; round < 12; round++) {
    const instances = Array.from({ length: 14 }, (_, i) => placed('id-' + i, allowed[Math.floor(rng() * allowed.length)].id, Math.round(rng() * 12) * 12.5, Math.round(rng() * 12) * 12.5, Math.floor(rng() * 4) * 90));
    assert.deepEqual(engine.update(instances).pairs, oracle(realKits, instances));
    const moving = instances[Math.floor(rng() * instances.length)]; moving.xMm += 12.5; moving.rotationDeg = (moving.rotationDeg + 90) % 360;
    assert.deepEqual(engine.update(instances).pairs, oracle(realKits, instances));
  }
});
test('unchanged frames, new instance-object copies, and viewport/selection changes do no geometry work', () => {
  const instances = fixture(50), engine = new Engine({ kits: realKits }); engine.update(instances);
  const first = engine.world(instances[0]); engine.update(copy(instances));
  const stats = engine.getStats();
  assert.equal(engine.world(instances[0]), first);
  for (const field of ['localCompiles', 'worldTransforms', 'narrowPhaseTests', 'edgeBuilds', 'segmentTests']) assert.equal(stats.last[field], 0, field);
});
test('moving one instance reuses unrelated exact pair results', () => {
  const instances = fixture(50), engine = new Engine({ kits: realKits }); engine.update(instances);
  instances[0].xMm += 12.5;
  const expected = oracle(realKits, instances), result = engine.update(instances);
  assert.deepEqual(result.pairs, expected); assert.deepEqual(result.changedIds, ['i0']); assert.equal(result.stats.last.worldTransforms, 1);
  assert.ok(result.stats.last.narrowPhaseTests <= 49); assert.ok(result.stats.last.pairCacheHits > 0);
  assert.equal(result.stats.last.localCompiles, 0);
});
test('world() reads before validation retain dirtiness, and moved-away pairs disappear', () => {
  const instances = [placed('a', 'waveplate', 100, 100), placed('b', 'waveplate', 100, 100)], engine = new Engine({ kits: realKits });
  assert.deepEqual(engine.update(instances).pairs, [['a', 'b']]);
  instances[0].xMm = -10000; engine.world(instances[0]);
  assert.deepEqual(engine.update(instances).pairs, []); assert.deepEqual(engine.getStats().cache, { kits: 1, instances: 2, candidatePairs: 0 });
});
test('deletion, clear, restoring a deleted ID and kit changes cannot retain stale pairs', () => {
  const engine = new Engine({ kits: realKits }), instances = fixture(50); engine.update(instances);
  engine.update(instances.slice(0, 2)); assert.equal(engine.getStats().cache.instances, 2); assert.ok(engine.getStats().cache.candidatePairs <= 1); assert.ok(engine.getStats().cache.kits <= 2);
  const restored = [placed('i0', 'waveplate', 0, 0), placed('i1', 'pbs-fixed', 0, 0)]; assert.deepEqual(engine.update(restored).pairs, oracle(realKits, restored));
  engine.clear(); assert.deepEqual(engine.update([]).pairs, []); assert.equal(engine.getStats().cache.instances, 0);
});
test('pair output follows original array order, even after reordering without geometry changes', () => {
  const instances = ['z', 'a', 'x', 'b'].map(id => placed(id, 'waveplate')), engine = new Engine({ kits: realKits });
  assert.deepEqual(engine.update(instances).pairs, oracle(realKits, instances));
  instances.reverse(); assert.deepEqual(engine.update(instances).pairs, oracle(realKits, instances));
  assert.equal(engine.getStats().last.worldTransforms, 0); assert.equal(engine.getStats().last.narrowPhaseTests, 0);
});
test('catalog replacement and explicit in-place invalidation refresh caches and revision', () => {
  const kit = polygonKit('box', [rectangle(0, 0, 10, 10)]), kits = new Map([['box', kit]]), engine = new Engine({ kits }), instances = [placed('a', 'box'), placed('b', 'box', 20, 0)];
  engine.update(instances); const before = engine.revision;
  kit.layout = { ...kit.layout, collisionPolygonsMm: polygonKit('box', [rectangle(0, 0, 25, 10)]).layout.collisionPolygonsMm };
  assert.ok(engine.revision > before); assert.deepEqual(engine.update(instances).pairs, [['a', 'b']]);
  kit.layout.collisionPolygonsMm[0][1].xMm = 10; kit.layout.collisionPolygonsMm[0][2].xMm = 10; engine.invalidateKit('box');
  assert.deepEqual(engine.update(instances).pairs, []);
  const replacement = polygonKit('box', [rectangle(0, 0, 30, 10)]); engine.setKits([replacement]); assert.deepEqual(engine.update(instances).pairs, [['a', 'b']]);
});
test('fallback collision rectangles retain prior anchor semantics and invalid polygons fall back', () => {
  for (const layout of [{ widthMm: 35, heightMm: 45, anchorXMm: 10, anchorYMm: 20 }, { collisionBoundsMm: { xMin: -10, xMax: 40, yMin: -15, yMax: 5 } }, { collisionPolygonsMm: [[{ xMm: NaN, yMm: 0 }, { xMm: 0, yMm: 1 }, { xMm: 1, yMm: 0 }]], widthMm: 25, heightMm: 35 }]) {
    const kits = new Map([['fallback', { id: 'fallback', layout }]]), engine = new Engine({ kits });
    for (const rotation of [0, 90, 180, 270]) { const instances = [placed('a', 'fallback', 0, 0, rotation), placed('b', 'fallback', 24, 0)]; assert.deepEqual(engine.update(instances).pairs, oracle(kits, instances)); }
  }
});
test('counterbore circle tests against cached world outlines retain old obstruction results', () => {
  const instances = fixture(20), engine = new Engine({ kits: realKits }), e = editor(realKits, instances); engine.update(instances);
  for (const instance of instances) for (const dx of [-20, -5.5, 0, 17.5, 45]) {
    const point = { xMm: instance.xMm + dx, yMm: instance.yMm + 12.5 };
    assert.equal(engine.world(instance).polygons.some(p => oracleGeometry.circleTouchesPolygon(point, 5.5, p)), e.worldPolygons(instance).some(p => oracleGeometry.circleTouchesPolygon(point, 5.5, p)));
  }
});

if (process.argv.includes('--benchmark')) {
  const median = values => values.sort((a, b) => a - b)[Math.floor(values.length / 2)];
  const timed = fn => { const start = performance.now(); const result = fn(); return { ms: performance.now() - start, result }; };
  const report = [];
  for (const count of [10, 50, 100, 250]) {
    const instances = fixture(count), engine = new Engine({ kits: realKits });
    const slow = timed(() => oracle(realKits, instances)), first = timed(() => engine.update(instances)); assert.deepEqual(first.result.pairs, slow.result);
    const unchanged = [], moves = [];
    for (let n = 0; n < 7; n++) unchanged.push(timed(() => engine.update(instances)).ms);
    for (let n = 0; n < 7; n++) { instances[0].xMm += n % 2 ? -12.5 : 12.5; moves.push(timed(() => engine.update(instances)).ms); }
    assert.deepEqual(engine.update(instances).pairs, oracle(realKits, instances));
    report.push({ count, oldBruteForceMs: slow.ms, initialEngineMs: first.ms, unchangedMedianMs: median(unchanged), moveOneMedianMs: median(moves), pairs: first.result.pairs.length });
  }
  console.log('COLLISION_BENCHMARK ' + JSON.stringify(report));
}
