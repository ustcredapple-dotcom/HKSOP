/* Pick physical threaded-hole centres, or explicit table reference-grid points. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ZZLabOpticalHoleProbe = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';
  const finite = Number.isFinite, EPS = 1e-8;

  function registeredRecord(board, catalog) {
    if (!board.registeredBoardId) return null;
    const helper = root.ZZLabRegisteredBoards || (typeof module === 'object' && module.exports ? require('./registered-boards.js') : null);
    if (!helper) throw new Error('注册面包板的真实孔位数据尚未加载。');
    const record = helper.recordFor(board, catalog);
    if (!record) throw new Error('找不到注册面包板的对应版本，不能用规则网格代替。');
    return { helper, record };
  }

  function convex(loop) {
    let sign = 0;
    for (let i = 0; i < loop.length; i++) {
      const a=loop[i], b=loop[(i+1)%loop.length], c=loop[(i+2)%loop.length];
      const z=(b.xMm-a.xMm)*(c.yMm-b.yMm)-(b.yMm-a.yMm)*(c.xMm-b.xMm);
      if (Math.abs(z) <= EPS) continue;
      if (sign && Math.sign(z) !== sign) return false;
      sign = Math.sign(z);
    }
    return Boolean(sign);
  }

  function frame(board, pose, order, referenceGrid = false, catalog) {
    const registered = registeredRecord(board, catalog), record = registered?.record;
    if (record) board = {...board, widthMm:record.widthMm, heightMm:record.heightMm, pitchMm:record.pitchMm, edgeOffsetMm:record.edgeOffsetMm};
    const angle = (pose.rotationDeg || 0) * Math.PI / 180;
    const c = Math.cos(angle), s = Math.sin(angle);
    const x = pose.xMm || 0, y = pose.yMm || 0;
    const offset = board.edgeOffsetMm ?? 12.5, pitch = board.pitchMm ?? 12.5;
    const width = board.widthMm, height = board.heightMm;
    const threadedHoles = record ? record.holesMm.filter(h => h.type === 'thread') : null;
    return {
      id: pose.id || null, name: pose.name || record?.name || (referenceGrid ? '桌面' : '大面包板'), order, board, referenceGrid,
      record, threadedHoles, threadedById: new Map((threadedHoles || []).map(h => [h.id, h])),
      materialContains: registered ? p => registered.helper.contains(board, {xMm:p.x,yMm:p.y}, catalog) : null,
      // Four covered corners prove coverage only for a convex region without windows.
      canCoverRectangle: !record || (!(record.cutoutsMm || []).length && convex(record.outlineMm)),
      offset, pitch, width, height,
      columns: Math.max(0, Math.floor((width - 2 * offset) / pitch + EPS) + 1),
      rows: Math.max(0, Math.floor((height - 2 * offset) / pitch + EPS) + 1),
      toLocal: p => ({ x: c * (p.x - x) + s * (p.y - y), y: -s * (p.x - x) + c * (p.y - y) }),
      toWorld: p => ({ x: x + c * p.x - s * p.y, y: y + s * p.x + c * p.y }),
      counterbores: new Set((referenceGrid ? [] : board.mountingHoles || []).map(h => `${h.columnIndex}:${h.rowIndex}`)),
    };
  }

  const measurable = f => Boolean(f.record) || f.referenceGrid || (f.board.holeType || 'M6_through') === 'M6_through';

  function contains(f, world) {
    const p = f.toLocal(world);
    return f.materialContains ? f.materialContains(p) : p.x >= -EPS && p.y >= -EPS && p.x <= f.width + EPS && p.y <= f.height + EPS;
  }

  function projection(segment, point) {
    const dx = segment.to.x - segment.from.x, dy = segment.to.y - segment.from.y;
    const length2 = dx * dx + dy * dy;
    if (!(length2 > EPS * EPS)) return null;
    const t = ((point.x - segment.from.x) * dx + (point.y - segment.from.y) * dy) / length2;
    const u = Math.max(0, Math.min(1, t));
    return { t, distance: Math.hypot(point.x - segment.from.x - u * dx, point.y - segment.from.y - u * dy) };
  }

  function build(layout, session, options = {}) {
    // This tolerance is numerical/alignment tolerance, unrelated to hit-target size.
    const tolerance = finite(options.alignmentToleranceMm) ? Math.min(.05, Math.max(0, options.alignmentToleranceMm)) : .02;
    const result = { holes: [], frames: [], alignmentToleranceMm: tolerance, stats: { gridSteps: 0, explicitSteps: 0, segments: 0, boards: 0 } };
    if (!layout?.board) return result;
    const frames = [frame(layout.board, {}, 0, layout.baseMode === 'table', options.catalog), ...(layout.subBoards || []).map((p, i) => frame(p.board, p, i + 1, false, options.catalog))];
    const usable = frames.filter(f => [f.width, f.height, f.pitch, f.offset].every(finite) && f.pitch > 0 && f.width > 0 && f.height > 0);
    result.frames = usable;
    result.stats.boards = usable.length;
    const found = new Map();
    const add = (f, location, segment) => {
      const candidate = holeAt(result, {boardId:f.id, ...location});
      if (!candidate) return;
      const hit = projection(segment, candidate);
      if (!hit || hit.distance > tolerance + EPS) return;
      let hole = found.get(candidate.id);
      if (!hole) { hole=candidate; found.set(hole.id, hole); }
      if (!hole.segmentIds.includes(segment.id)) hole.segmentIds.push(segment.id);
    };
    for (const segment of session?.segments || []) {
      if (segment.internalAssemblySegment) continue;
      if (!segment.from || !segment.to || ![segment.from.x, segment.from.y, segment.to.x, segment.to.y].every(finite)) continue;
      if (finite(segment.beam?.powerMw) && segment.beam.powerMw <= 0) continue;
      result.stats.segments++;
      for (const f of usable) {
        if (!measurable(f)) continue;
        const a = f.toLocal(segment.from), b = f.toLocal(segment.to), dx = b.x - a.x, dy = b.y - a.y;
        if (f.record) {
          // Registered CAD holes are explicit. Never synthesise pitch-grid holes.
          for (const hole of f.threadedHoles) {
            if (hole.xMm < Math.min(a.x,b.x)-tolerance || hole.xMm > Math.max(a.x,b.x)+tolerance ||
                hole.yMm < Math.min(a.y,b.y)-tolerance || hole.yMm > Math.max(a.y,b.y)+tolerance) continue;
            result.stats.explicitSteps++;
            add(f, {holeId:hole.id}, segment);
          }
          continue;
        }
        if (Math.max(a.x, b.x) < f.offset - tolerance || Math.min(a.x, b.x) > f.width - f.offset + tolerance ||
            Math.max(a.y, b.y) < f.offset - tolerance || Math.min(a.y, b.y) > f.height - f.offset + tolerance) continue;
        // Walk only columns/rows crossed by a segment, not every hole on the board.
        const horizontal = Math.abs(dx) >= Math.abs(dy), delta = horizontal ? dx : dy;
        if (Math.abs(delta) <= EPS) continue;
        const majorA = horizontal ? a.x : a.y, majorB = horizontal ? b.x : b.y;
        const count = horizontal ? f.columns : f.rows;
        const first = Math.max(0, Math.ceil((Math.min(majorA, majorB) - tolerance - f.offset) / f.pitch));
        const last = Math.min(count - 1, Math.floor((Math.max(majorA, majorB) + tolerance - f.offset) / f.pitch));
        for (let index = first; index <= last; index++) {
          result.stats.gridSteps++;
          const t = (f.offset + index * f.pitch - majorA) / delta;
          const minor = horizontal ? a.y + t * dy : a.x + t * dx;
          const otherIndex = Math.round((minor - f.offset) / f.pitch);
          add(f, {columnIndex:horizontal ? index : otherIndex, rowIndex:horizontal ? otherIndex : index}, segment);
        }
      }
    }
    result.holes = [...found.values()].sort((a, b) => String(a.boardId || '').localeCompare(String(b.boardId || '')) || a.localYMm - b.localYMm || a.localXMm - b.localXMm || a.id.localeCompare(b.id));
    return result;
  }

  function nearest(index, point, maxDistanceMm = Infinity) {
    if (!point || !finite(point.x) || !finite(point.y) || !(maxDistanceMm >= 0)) return null;
    let best = null;
    for (const hole of index?.holes || []) {
      const distanceToCursorMm = Math.hypot(point.x - hole.x, point.y - hole.y);
      if (distanceToCursorMm > maxDistanceMm + EPS || (best && distanceToCursorMm >= best.distanceToCursorMm - EPS)) continue;
      best = { ...hole, distanceToCursorMm };
    }
    return best;
  }

  function probe(index, session, point, options = {}) {
    const hole = nearest(index, point, options.maxDistanceMm ?? 25);
    if (!hole) return { hole: null, point: null, readings: [] };
    const exact = { x: hole.x, y: hole.y }, engine = options.engine;
    if (!engine?.probe) throw new Error('沿光路测距需要光路计算器。');
    const segmentIds = new Set(hole.segmentIds);
    const readings = engine.probe(session, exact, index.alignmentToleranceMm + EPS).filter(r => segmentIds.has(r.segmentId));
    return { hole, point: exact, readings };
  }

  function holeAt(index, location) {
    const f = index?.frames?.find(f => f.id === (location?.boardId || null));
    if (!f || !measurable(f)) return null;
    let local, identity;
    if (f.record) {
      const hole=f.threadedById.get(location?.holeId);
      if (!hole) return null;
      local={x:hole.xMm,y:hole.yMm};
      identity={id:`${f.id || '@root'}:hole:${hole.id}`,holeId:hole.id,thread:hole.thread||null};
    } else {
      const c=location?.columnIndex,r=location?.rowIndex;
      if (!Number.isInteger(c)||!Number.isInteger(r)||c<0||r<0||c>=f.columns||r>=f.rows||f.counterbores.has(`${c}:${r}`)) return null;
      local={x:f.offset+c*f.pitch,y:f.offset+r*f.pitch};
      identity={id:`${f.id || '@root'}:${c}:${r}`,columnIndex:c,rowIndex:r};
    }
    const world=f.toWorld(local);
    if (!contains(f,world)||index.frames.some(other=>other.order>f.order&&contains(other,world))) return null;
    return {...identity,boardId:f.id,boardName:f.name,referenceGrid:f.referenceGrid,x:world.x,y:world.y,
      localXMm:local.x,localYMm:local.y,pitchMm:f.pitch,segmentIds:[]};
  }

  // Search grid rectangles by their minimum distance, subdividing only where a
  // nearer valid hole can exist. This stays small even on a 10000 mm board and
  // skips an entire covered region without materialising every board hole.
  function nearestValid(index, point, maxDistanceMm = Infinity) {
    if (!point || !finite(point.x) || !finite(point.y) || !(maxDistanceMm >= 0)) return null;
    let best = null, limit = maxDistanceMm * maxDistanceMm;
    const queue = [], frames = index?.frames || [];
    const push = n => {
      const { f, c0, c1, r0, r1 } = n, p = f.toLocal(point);
      const x0 = f.offset + c0 * f.pitch, x1 = f.offset + c1 * f.pitch;
      const y0 = f.offset + r0 * f.pitch, y1 = f.offset + r1 * f.pitch;
      n.distance2 = Math.max(x0 - p.x, 0, p.x - x1) ** 2 + Math.max(y0 - p.y, 0, p.y - y1) ** 2;
      if (n.distance2 > limit + EPS) return;
      const corners = [{x:x0,y:y0},{x:x1,y:y0},{x:x1,y:y1},{x:x0,y:y1}].map(f.toWorld);
      if (frames.some(other => other.order > f.order && other.canCoverRectangle && corners.every(p => contains(other,p)))) return;
      queue.push(n);
    };
    for (const f of [...frames].reverse()) {
      if (!measurable(f)) continue;
      if (f.record) {
        for (const registered of f.threadedHoles) {
          const hole=holeAt(index,{boardId:f.id,holeId:registered.id});
          if (!hole) continue;
          const distance2=(hole.x-point.x)**2+(hole.y-point.y)**2;
          if (distance2<=limit+EPS&&(!best||distance2<limit-EPS)) {limit=distance2;best={...hole,distanceToCursorMm:Math.sqrt(distance2)};}
        }
      } else if (f.columns&&f.rows) push({ f, c0: 0, c1: f.columns - 1, r0: 0, r1: f.rows - 1 });
    }
    while (queue.length) {
      queue.sort((a,b) => b.distance2-a.distance2 || a.f.order-b.f.order);
      const n = queue.pop(), { f, c0, c1, r0, r1 } = n;
      if (n.distance2 > limit + EPS) break;
      if (c0 === c1 && r0 === r1) {
        const hole = holeAt(index, { boardId:f.id, columnIndex:c0, rowIndex:r0 });
        if (hole && (!best || n.distance2 < limit - EPS)) { limit=n.distance2; best={...hole,distanceToCursorMm:Math.sqrt(limit)}; }
      } else if (c1-c0 >= r1-r0) {
        const mid=Math.floor((c0+c1)/2); push({...n,c1:mid}); push({...n,c0:mid+1});
      } else {
        const mid=Math.floor((r0+r1)/2); push({...n,r1:mid}); push({...n,r0:mid+1});
      }
    }
    return best;
  }

  function snap(index, session, point, options = {}) {
    const ordinary = nearestValid(index, point, options.fallbackDistanceMm ?? Infinity);
    if (!ordinary) return { hole:null, point:null, readings:[], onBeam:false };
    const owner = [...(index.frames || [])].reverse().find(f => contains(f,point));
    // Beam preference is local to one grid cell, even when zoomed far out. A
    // click on a dark hole must not jump across the board to find a lit one.
    const radius = Math.min(options.maxDistanceMm ?? Infinity, (owner?.pitch || ordinary.pitchMm) * .75);
    const lit = session && options.engine?.probe ? probe(index, session, point, {...options,maxDistanceMm:radius}) : null;
    if (lit?.readings.length) return {...lit,onBeam:true};
    return { hole:ordinary, point:{x:ordinary.x,y:ordinary.y}, readings:[], onBeam:false };
  }
  return { build, nearest, probe, holeAt, nearestValid, snap };
});
