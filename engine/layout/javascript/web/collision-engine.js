/* Exact cached 2-D kit collisions. Geometry is immutable between catalog updates. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ZZLabCollisionEngine = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const EPS = 1e-5, EMPTY = Object.freeze({});
  const COUNTERS = ['localCompiles', 'worldTransforms', 'edgeBuilds', 'candidatePairs', 'narrowPhaseTests', 'pairCacheHits', 'edgeBoxTests', 'segmentTests'];
  const zero = () => Object.fromEntries(COUNTERS.map(key => [key, 0]));
  const box = points => {
    let xMin = Infinity, yMin = Infinity, xMax = -Infinity, yMax = -Infinity;
    for (const point of points) { xMin = Math.min(xMin, point.xMm); yMin = Math.min(yMin, point.yMm); xMax = Math.max(xMax, point.xMm); yMax = Math.max(yMax, point.yMm); }
    return { xMin, yMin, xMax, yMax };
  };
  const boxesTouch = (a, b) => a.xMin <= b.xMax + EPS && a.xMax >= b.xMin - EPS && a.yMin <= b.yMax + EPS && a.yMax >= b.yMin - EPS;
  const rect = b => [{ xMm: b.xMin, yMm: b.yMin }, { xMm: b.xMax, yMm: b.yMin }, { xMm: b.xMax, yMm: b.yMax }, { xMm: b.xMin, yMm: b.yMax }];
  const merge = (a, b) => ({ xMin: Math.min(a.xMin, b.xMin), yMin: Math.min(a.yMin, b.yMin), xMax: Math.max(a.xMax, b.xMax), yMax: Math.max(a.yMax, b.yMax) });
  function edges(points) {
    return points.map((a, index) => {
      const b = points[(index + 1) % points.length], dx = b.xMm - a.xMm, dy = b.yMm - a.yMm;
      return { a, b, dx, dy, lengthSquared: dx * dx + dy * dy, xMin: Math.min(a.xMm, b.xMm), xMax: Math.max(a.xMm, b.xMm), yMin: Math.min(a.yMm, b.yMm), yMax: Math.max(a.yMm, b.yMm) };
    });
  }
  function tree(edgeList, indices) {
    let bounds = edgeList[indices[0]];
    for (let i = 1; i < indices.length; i++) bounds = merge(bounds, edgeList[indices[i]]);
    const result = { bounds: { xMin: bounds.xMin, yMin: bounds.yMin, xMax: bounds.xMax, yMax: bounds.yMax }, count: indices.length };
    if (indices.length <= 8) { result.indices = indices; return result; }
    const horizontal = bounds.xMax - bounds.xMin >= bounds.yMax - bounds.yMin;
    indices.sort((a, b) => horizontal ? (edgeList[a].xMin + edgeList[a].xMax) - (edgeList[b].xMin + edgeList[b].xMax) : (edgeList[a].yMin + edgeList[a].yMax) - (edgeList[b].yMin + edgeList[b].yMax));
    const half = Math.floor(indices.length / 2);
    result.left = tree(edgeList, indices.slice(0, half)); result.right = tree(edgeList, indices.slice(half)); return result;
  }
  function signature(layout) {
    return [layout, layout.collisionPolygonsMm, layout.collisionBoundsMm, layout.widthMm, layout.heightMm, layout.anchorXMm, layout.anchorYMm,
      layout.baseBoundsMm, layout.mountingHoleOffsetsMm, layout.mountingHoleRadiusMm, layout.placementAllowed, layout.topViewUrl];
  }
  const sameSignature = (a, b) => a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  function compile(layout, includeBase = false) {
    let polygons = layout.collisionPolygonsMm;
    if (!(Array.isArray(polygons) && polygons.length && polygons.every(p => Array.isArray(p) && p.length >= 3 && p.every(v => v && Number.isFinite(v.xMm) && Number.isFinite(v.yMm))))) {
      let b = layout.collisionBoundsMm;
      if (!(b && ['xMin', 'yMin', 'xMax', 'yMax'].every(key => Number.isFinite(b[key])) && b.xMax > b.xMin && b.yMax > b.yMin)) {
        const width = Number(layout.widthMm) || 25, height = Number(layout.heightMm) || 25;
        const ax = Number.isFinite(Number(layout.anchorXMm)) ? Number(layout.anchorXMm) : width / 2;
        const ay = Number.isFinite(Number(layout.anchorYMm)) ? Number(layout.anchorYMm) : height / 2;
        b = { xMin: -ax, yMin: ay - height, xMax: width - ax, yMax: ay };
      }
      polygons = [rect(b)];
    }
    const base = layout.baseBoundsMm;
    if (includeBase && base && ['xMin', 'yMin', 'xMax', 'yMax'].every(key => Number.isFinite(base[key]))) polygons = [...polygons, rect(base)];
    return polygons.map(raw => {
      const points = raw.map(p => ({ xMm: p.xMm, yMm: p.yMm })), localEdges = edges(points);
      return { points, bounds: box(points), tree: tree(localEdges, localEdges.map((_, index) => index)) };
    });
  }
  function pointDistance(point, edge) {
    const t = edge.lengthSquared ? Math.max(0, Math.min(1, ((point.xMm - edge.a.xMm) * edge.dx + (point.yMm - edge.a.yMm) * edge.dy) / edge.lengthSquared)) : 0;
    return Math.hypot(point.xMm - edge.a.xMm - t * edge.dx, point.yMm - edge.a.yMm - t * edge.dy);
  }
  function segmentsTouch(a, b, count) {
    count('edgeBoxTests');
    if (!boxesTouch(a, b)) return false;
    count('segmentTests');
    if (pointDistance(a.a, b) <= EPS || pointDistance(a.b, b) <= EPS || pointDistance(b.a, a) <= EPS || pointDistance(b.b, a) <= EPS) return true;
    const cross = (edge, p) => edge.dx * (p.yMm - edge.a.yMm) - edge.dy * (p.xMm - edge.a.xMm);
    return (cross(a, b.a) > 0) !== (cross(a, b.b) > 0) && (cross(b, a.a) > 0) !== (cross(b, a.b) > 0);
  }
  function pointInPolygon(point, polygon) {
    let inside = false;
    for (const edge of polygon.edges) {
      const a = edge.a, b = edge.b;
      if (pointDistance(point, edge) <= EPS) return true;
      if ((a.yMm > point.yMm) !== (b.yMm > point.yMm) && point.xMm < (b.xMm - a.xMm) * (point.yMm - a.yMm) / (b.yMm - a.yMm) + a.xMm) inside = !inside;
    }
    return inside;
  }
  function treeTouches(a, b, edgesA, edgesB, count) {
    if (!boxesTouch(a.bounds, b.bounds)) return false;
    if (a.indices && b.indices) {
      for (const ia of a.indices) for (const ib of b.indices) if (segmentsTouch(edgesA[ia], edgesB[ib], count)) return true;
      return false;
    }
    if (!a.indices && (b.indices || a.count >= b.count)) return treeTouches(a.left, b, edgesA, edgesB, count) || treeTouches(a.right, b, edgesA, edgesB, count);
    return treeTouches(a, b.left, edgesA, edgesB, count) || treeTouches(a, b.right, edgesA, edgesB, count);
  }
  function transformPoint(point, pose) {
    return { xMm: pose.x + point.xMm * pose.c - point.yMm * pose.s, yMm: pose.y + point.xMm * pose.s + point.yMm * pose.c };
  }
  function transformTree(local, pose) {
    const result = { bounds: box(rect(local.bounds).map(p => transformPoint(p, pose))), count: local.count };
    if (local.indices) result.indices = local.indices;
    else { result.left = transformTree(local.left, pose); result.right = transformTree(local.right, pose); }
    return result;
  }
  class Engine {
    constructor({ kits, catalog } = {}) {
      this._kits = kits instanceof Map ? kits : new Map((kits || catalog?.kits || []).map(kit => [kit.id, kit]));
      this._locals = new Map(); this._worlds = new Map(); this._pairCache = new Map(); this._dirty = new Set();
      this._order = []; this._pairs = []; this._serial = 0; this._revision = 0; this._total = zero(); this._pending = zero(); this._last = zero();
      this._count = key => { this._pending[key]++; this._total[key]++; };
    }
    _layout(kitId) { return this._kits.get(kitId)?.layout || EMPTY; }
    get revision() {
      for (const local of this._locals.values()) if (!sameSignature(local.signature, signature(this._layout(local.kitId)))) this.invalidateKit(local.kitId);
      return this._revision;
    }
    invalidateKit(kitId) {
      for (const [key, local] of this._locals) if (local.kitId === kitId) this._locals.delete(key);
      this._revision++;
      for (const world of this._worlds.values()) if (world.kitId === kitId) this._dirty.add(world.uid);
    }
    setKits(kits) {
      this._kits = kits instanceof Map ? kits : new Map(kits.map(kit => [kit.id, kit])); this.clear();
    }
    clear() {
      this._locals.clear(); this._worlds.clear(); this._pairCache.clear(); this._dirty.clear(); this._order = []; this._pairs = []; this._revision++;
    }
    _local(kitId, includeBase = false) {
      const key = JSON.stringify([kitId, includeBase]);
      const layout = this._layout(kitId), current = this._locals.get(key), sig = signature(layout);
      if (current && sameSignature(current.signature, sig)) return current;
      const local = { kitId, key, signature: sig, polygons: compile(layout, includeBase) };
      this._locals.set(key, local); this._revision++; this._count('localCompiles'); return local;
    }
    world(instance) {
      const { id, kitId, xMm, yMm, rotationDeg } = instance;
      if (typeof id !== 'string' || typeof kitId !== 'string' || ![xMm, yMm, rotationDeg].every(Number.isFinite)) throw new TypeError('Collision instances require IDs and finite poses.');
      const local = this._local(kitId, kitId === 'laser-308nm' && instance.laserAdapter?.enabled === true), previous = this._worlds.get(id);
      if (previous && previous.kitId === kitId && previous.xMm === xMm && previous.yMm === yMm && previous.rotationDeg === rotationDeg && previous.local === local) return previous;
      const angle = rotationDeg * Math.PI / 180, pose = { x: xMm, y: yMm, c: Math.round(Math.cos(angle)), s: Math.round(Math.sin(angle)) };
      const shapes = local.polygons.map(p => {
        const points = p.points.map(point => transformPoint(point, pose));
        return { points, bounds: box(points), local: p, pose, edges: null, tree: null };
      });
      let bounds = shapes[0].bounds; for (let i = 1; i < shapes.length; i++) bounds = merge(bounds, shapes[i].bounds);
      const result = { id, kitId, xMm, yMm, rotationDeg, uid: previous?.uid ?? ++this._serial, local, shapes, polygons: shapes.map(p => p.points), bounds };
      this._worlds.set(id, result); this._dirty.add(result.uid); this._count('worldTransforms'); return result;
    }
    _prepare(shape) {
      if (shape.edges) return;
      shape.edges = edges(shape.points); shape.tree = transformTree(shape.local.tree, shape.pose); this._count('edgeBuilds');
    }
    _touch(a, b) {
      this._count('narrowPhaseTests');
      for (const pa of a.shapes) for (const pb of b.shapes) {
        if (!boxesTouch(pa.bounds, pb.bounds)) continue;
        this._prepare(pa); this._prepare(pb);
        if (treeTouches(pa.tree, pb.tree, pa.edges, pb.edges, this._count) || pointInPolygon(pa.points[0], pb) || pointInPolygon(pb.points[0], pa)) return true;
      }
      return false;
    }
    update(instances) {
      if (!Array.isArray(instances)) throw new TypeError('Collision instances must be an array.');
      const seen = new Set();
      for (const instance of instances) { if (seen.has(instance.id)) throw new TypeError('Collision instance IDs must be unique.'); seen.add(instance.id); }
      const records = instances.map(instance => this.world(instance)), order = records.map(record => record.id), indices = new Map(order.map((id, index) => [id, index]));
      let removed = false;
      for (const [id, record] of this._worlds) if (!seen.has(id)) { this._worlds.delete(id); this._dirty.delete(record.uid); removed = true; }
      // Catalog-local shapes are also bounded by the current live kit set.
      const activeKits = new Set(records.map(record => record.local.key));
      for (const key of this._locals.keys()) if (!activeKits.has(key)) this._locals.delete(key);
      const reordered = order.length !== this._order.length || order.some((id, index) => id !== this._order[index]);
      const dirty = new Set(this._dirty), changedIds = records.filter(record => dirty.has(record.uid)).map(record => record.id);
      if (dirty.size || removed) {
        const next = new Map(), collisions = [];
        const sorted = records.slice().sort((a, b) => a.bounds.xMin - b.bounds.xMin || a.uid - b.uid);
        for (let i = 0; i < sorted.length; i++) {
          const a = sorted[i];
          for (let j = i + 1; j < sorted.length; j++) {
            const b = sorted[j]; if (b.bounds.xMin > a.bounds.xMax + EPS) break;
            if (!boxesTouch(a.bounds, b.bounds)) continue;
            this._count('candidatePairs');
            const key = a.uid < b.uid ? `${a.uid}:${b.uid}` : `${b.uid}:${a.uid}`, old = this._pairCache.get(key);
            let touch;
            if (!dirty.has(a.uid) && !dirty.has(b.uid) && old !== undefined) { touch = old.touch; this._count('pairCacheHits'); }
            else touch = this._touch(a, b);
            next.set(key, { a: a.id, b: b.id, touch });
            if (touch) collisions.push([a.id, b.id]);
          }
        }
        this._pairCache = next; this._pairs = collisions;
      }
      if (dirty.size || removed || reordered) {
        for (const pair of this._pairs) if (indices.get(pair[0]) > indices.get(pair[1])) [pair[0], pair[1]] = [pair[1], pair[0]];
        // Match the former Editor loop: each later instance against its predecessors.
        this._pairs.sort((a, b) => indices.get(a[1]) - indices.get(b[1]) || indices.get(a[0]) - indices.get(b[0]));
      }
      this._order = order; this._dirty.clear(); this._last = this._pending; this._pending = zero();
      return { pairs: this._pairs, changedIds, stats: this.getStats() };
    }
    getStats() { return { last: { ...this._last }, total: { ...this._total }, cache: { kits: this._locals.size, instances: this._worlds.size, candidatePairs: this._pairCache.size }, revision: this._revision }; }
  }
  return Object.freeze({ Engine, EPS });
});
