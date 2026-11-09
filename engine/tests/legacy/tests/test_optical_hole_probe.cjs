'use strict';
const assert=require('node:assert/strict'), H=require('../static/optical-hole-probe.js'), E=require('../static/optical-engine.js');
let checks=0;const test=(name,fn)=>{fn();checks++;console.log(`PASS ${name}`)}, near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const board=(extra={})=>({widthMm:100,heightMm:100,pitchMm:25,edgeOffsetMm:12.5,holeType:'M6_through',mountingHoles:[],...extra});
const seg=(id,x1,y1,x2,y2,extra={})=>({id,from:{x:x1,y:y1},to:{x:x2,y:y2},beam:E.createBeam({powerMw:10}),...extra});
const build=(segments,b=board(),subBoards=[])=>H.build({board:b,subBoards},{segments});
test('horizontal and vertical beams index actual centres and share intersections',()=>{const h=build([seg('h',0,37.5,100,37.5),seg('v',62.5,0,62.5,100)]);assert.equal(h.holes.length,7);assert.deepEqual(h.holes.find(p=>p.x===62.5&&p.y===37.5).segmentIds,['h','v']);assert.equal(h.stats.gridSteps,8)});
test('diagonal paths expose only truly crossed holes, not nearby holes',()=>{const h=build([seg('d',0,0,100,100)]);assert.equal(h.holes.length,4);assert.ok(h.holes.every(p=>p.x===p.y));assert.equal(H.nearest(h,{x:12.5,y:37.5},5),null);const snapped=H.nearest(h,{x:35,y:42},20);assert.equal(snapped.x,37.5);assert.equal(snapped.y,37.5)});
test('segment endpoints do not extend the path for picking',()=>{const h=build([seg('short',20,37.5,62.5,37.5)]);assert.deepEqual(h.holes.map(p=>p.x),[37.5,62.5]);assert.equal(H.nearest(h,{x:12.5,y:37.5},10),null)});
test('counterbores and non-threaded boards cannot be selected',()=>{const b=board({mountingHoles:[{columnIndex:1,rowIndex:1}]});assert.deepEqual(build([seg('s',0,37.5,100,37.5)],b).holes.map(p=>p.x),[12.5,62.5,87.5]);assert.equal(build([seg('s',0,37.5,100,37.5)],board({holeType:'plain_through'})).holes.length,0)});
test('rotated small-board coordinates are correct and cover carrier holes',()=>{const small={id:'small',name:'小板',xMm:75,yMm:25,rotationDeg:90,board:board({widthMm:50,heightMm:50})};const h=build([seg('s',0,37.5,100,37.5)],board(),[small]);assert.equal(h.holes.length,4);const local=h.holes.filter(p=>p.boardId==='small');assert.equal(local.length,2);assert.ok(local.every(p=>p.columnIndex===0));near(local[0].x,62.5);near(local[1].x,37.5);assert.deepEqual(h.holes.filter(p=>!p.boardId).map(p=>p.x),[12.5,87.5])});
test('a non-threaded small board still masks threaded holes below it',()=>{const small={id:'plain',xMm:25,yMm:25,board:board({widthMm:50,heightMm:50,holeType:'plain_through'})};const h=build([seg('s',0,37.5,100,37.5)],board(),[small]);assert.deepEqual(h.holes.map(p=>p.x),[12.5,87.5])});
test('alignment tolerance is independent of cursor target size and zero power is excluded',()=>{assert.equal(build([seg('s',0,37.53,100,37.53)]).holes.length,0);const h=build([seg('s',0,37.51,100,37.51)]);assert.equal(h.holes.length,4);assert.ok(H.nearest(h,{x:37.5,y:57.5},21));assert.equal(build([seg('dark',0,37.5,100,37.5,{beam:{powerMw:0}})]).holes.length,0)});
test('probe passes exact hole centres and limits readings to indexed segments',()=>{const s={segments:[seg('a',0,37.5,100,37.5)]},h=H.build({board:board()},s);let p;const fake={probe:(session,point,tolerance)=>{p=point;assert.ok(tolerance<.021);return[{segmentId:'a'},{segmentId:'other'}]}};const r=H.probe(h,s,{x:40,y:43},{maxDistanceMm:20,engine:fake});assert.deepEqual(p,{x:37.5,y:37.5});assert.equal(r.readings.length,1);assert.deepEqual(H.probe(h,s,{x:0,y:100},{maxDistanceMm:1,engine:fake}),{hole:null,point:null,readings:[]})});
test('double-pass readings keep separate forward and return distances at the same hole',()=>{const optics=t=>E.normalizeOptics({elementType:t,inserted:true,configured:true});const source={id:'source',center:{x:0,y:37.5},optics:{...optics('source'),source:{enabled:true,directionAngleDeg:0,powerMw:10}}};const mirror={id:'mirror',center:{x:100,y:37.5},optics:{...optics('mirror'),surfaceAngleDeg:90}};let s=E.createSession({bounds:{xMin:0,yMin:0,xMax:125,yMax:100},elements:[source,mirror]});s=E.advancePending(s,s.pending[0].id);const h=H.build({board:board()},s);const r=H.probe(h,s,{x:41,y:41},{engine:E});assert.equal(r.hole.x,37.5);assert.equal(r.readings.length,2);assert.deepEqual(r.readings.map(v=>v.distanceFromSourceMm).sort((a,b)=>a-b),[37.5,162.5])});
test('large board builds by crossed grid lines rather than enumerating all holes',()=>{const h=build([seg('s',0,12.5,10000,12.5)],board({widthMm:10000,heightMm:10000,pitchMm:12.5}));assert.equal(h.holes.length,799);assert.equal(h.stats.gridSteps,799)});
test('empty and invalid input return empty indices and safe misses',()=>{assert.equal(H.build(null,null).holes.length,0);assert.equal(H.build({board:board()},{}).holes.length,0);assert.equal(build([seg('bad',NaN,0,100,0)]).holes.length,0);assert.equal(H.nearest({holes:[]},{x:0,y:0}),null);assert.equal(H.nearest({holes:[]},{x:NaN,y:0}),null)});


test('snapping uses a nearby lit grid cell first but a dark region selects its own hole without invented optical path',()=>{
  const session={segments:[seg('beam',0,12.5,100,12.5)]},index=H.build({board:board()},session),fake={probe:()=>[{segmentId:'beam',distanceFromSourceMm:12.5}]};
  let result=H.snap(index,session,{x:15,y:20},{engine:fake,maxDistanceMm:10000});assert.equal(result.onBeam,true);assert.equal(result.hole.y,12.5);
  result=H.snap(index,session,{x:37.5,y:62.5},{engine:fake,maxDistanceMm:10000});assert.equal(result.onBeam,false);assert.equal(result.hole.y,62.5);assert.deepEqual(result.readings,[]);
  result=H.snap(index,session,{x:1000,y:1000},{engine:fake});assert.equal(result.onBeam,false);assert.deepEqual(result.point,{x:87.5,y:87.5});
});
test('ordinary holes are available with no trace and skip counterbores, plain holes and covered carrier holes',()=>{
  const b=board({mountingHoles:[{columnIndex:1,rowIndex:1}]}),index=H.build({board:b},null),r=H.snap(index,null,{x:37.5,y:37.5});assert.ok(r.hole);assert.notEqual(r.hole.id,'@root:1:1');assert.equal(r.onBeam,false);assert.deepEqual(r.readings,[]);
  const small={id:'plain',xMm:25,yMm:25,board:board({widthMm:50,heightMm:50,holeType:'plain_through'})};
  const covered=H.build({board:board(),subBoards:[small]},null);assert.equal(H.holeAt(covered,{boardId:null,columnIndex:1,rowIndex:1}),null);const n=H.nearestValid(covered,{x:50,y:50});assert.ok(n.x<25||n.x>75||n.y<25||n.y>75);
  assert.equal(H.snap(H.build({board:board({holeType:'plain_through'})},null),null,{x:30,y:30}).hole,null);
});
test('lazy nearest-hole search matches exhaustive physical grids with rotations and masked regions',()=>{
  const subBoards=[{id:'rotated',name:'上板',xMm:75,yMm:25,rotationDeg:90,board:board({widthMm:50,heightMm:50,mountingHoles:[{columnIndex:0,rowIndex:0}]})},{id:'plain',xMm:10,yMm:20,rotationDeg:30,board:board({widthMm:25,heightMm:30,holeType:'plain_through'})}];
  const index=H.build({board:board(),subBoards},null),all=[];for(const f of index.frames)for(let c=0;c<f.columns;c++)for(let r=0;r<f.rows;r++){const h=H.holeAt(index,{boardId:f.id,columnIndex:c,rowIndex:r});if(h)all.push(h)}
  for(let n=0;n<80;n++){const p={x:(n*17)%143-20,y:(n*29)%137-15},actual=H.nearestValid(index,p),best=Math.min(...all.map(h=>Math.hypot(h.x-p.x,h.y-p.y)));near(actual.distanceToCursorMm,best)}
});
test('large ordinary-hole queries and fully covered grids do not materialize the board grid',()=>{
  const huge=board({widthMm:10000,heightMm:10000,pitchMm:12.5}),index=H.build({board:huge},null);assert.equal(index.holes.length,0);const start=performance.now();
  for(let n=0;n<200;n++){const h=H.nearestValid(index,{x:5010+n/10,y:5120});assert.ok(h);assert.equal(h.y,5125)}
  const fullyCovered=H.build({board:huge,subBoards:[{id:'cover',xMm:0,yMm:0,board:{...huge,holeType:'plain_through'}}]},null);assert.equal(H.nearestValid(fullyCovered,{x:5000,y:5000}),null);
  assert.ok(performance.now()-start<1000,'200 near-grid queries remain bounded without full board enumeration');assert.equal(index.holes.length,0);
});


test('table reference grid remains measurable for plain root boards and ignores fictitious root counterbores',()=>{
  const layout={baseMode:'table',board:board({holeType:'plain_through',mountingHoles:[{columnIndex:1,rowIndex:1}]})};
  const optics=E.normalizeOptics({elementType:'source',inserted:true,source:{enabled:true,directionAngleDeg:0,powerMw:10}}),session=E.createSession({bounds:{xMin:0,yMin:0,xMax:100,yMax:100},elements:[{id:'s',center:{x:0,y:37.5},optics}]});
  const index=H.build(layout,session);assert.equal(index.holes.length,4);assert.ok(index.holes.every(h=>h.referenceGrid&&h.boardName==='桌面'));
  const lit=H.snap(index,session,{x:39,y:38},{engine:E});assert.equal(lit.hole.id,'@root:1:1');assert.equal(lit.onBeam,true);near(lit.readings[0].distanceFromSourceMm,37.5);
  const dark=H.snap(index,session,{x:37.5,y:87.5},{engine:E});assert.equal(dark.hole.referenceGrid,true);assert.equal(dark.onBeam,false);assert.deepEqual(dark.readings,[]);
});
test('table reference points yield to real small-board holes and never show through its counterbores',()=>{
  const small={id:'small',name:'实物小板',xMm:25,yMm:25,rotationDeg:0,board:board({widthMm:50,heightMm:50,mountingHoles:[{columnIndex:0,rowIndex:0}]})};
  const layout={baseMode:'table',board:board({holeType:'plain_through'}),subBoards:[small]},session={segments:[seg('s',0,37.5,100,37.5)]},index=H.build(layout,session);
  assert.deepEqual(index.holes.map(h=>[h.x,h.referenceGrid]),[[12.5,true],[87.5,true],[62.5,false]]);
  assert.equal(H.holeAt(index,{boardId:null,columnIndex:1,rowIndex:1}),null);assert.equal(H.holeAt(index,{boardId:'small',columnIndex:0,rowIndex:0}),null);
  const child=H.nearestValid(index,{x:62.5,y:37.5});assert.equal(child.boardId,'small');assert.equal(child.referenceGrid,false);
  small.board.holeType='plain_through';const plain=H.build(layout,null);assert.equal(H.holeAt(plain,{boardId:'small',columnIndex:1,rowIndex:0}),null);assert.equal(H.holeAt(plain,{boardId:null,columnIndex:2,rowIndex:1}),null);
});
console.log(`${checks} optical hole probe checks passed`);
