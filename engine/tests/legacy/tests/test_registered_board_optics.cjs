'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const E=require('../static/optical-engine.js'),R=require('../static/optical-renderer.js'),H=require('../static/optical-hole-probe.js');
let checks=0;const test=(name,fn)=>{fn();checks++;console.log('PASS '+name)},near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const loop=xy=>xy.map(([xMm,yMm])=>({xMm,yMm}));
const dimensions={widthMm:100,heightMm:100,thicknessMm:12.7,pitchMm:25,edgeOffsetMm:12.5};
const regular=()=>({...dimensions,holeType:'M6_through',mountingHoles:[]});
const u={id:'u-board',revision:'cad-r1',name:'U形板',...dimensions,outlineMm:loop([[0,0],[100,0],[100,100],[70,100],[70,30],[30,30],[30,100],[0,100]]),cutoutsMm:[],holesMm:[{id:'T1',xMm:15,yMm:15,type:'thread',thread:'M6x1.0',diameterMm:6},{id:'T2',xMm:85,yMm:85,type:'thread',thread:'M4x0.7',diameterMm:4},{id:'C1',xMm:80,yMm:15,type:'counterbore',diameterMm:6.6,counterboreDiameterMm:11},{id:'P1',xMm:15,yMm:80,type:'clearance',diameterMm:6.6}],mountingHoleIds:['C1']};
const ring={id:'ring-board',revision:'cad-r1',name:'开窗板',...dimensions,outlineMm:loop([[0,0],[100,0],[100,100],[0,100]]),cutoutsMm:[loop([[25,25],[75,25],[75,75],[25,75]])],holesMm:[],mountingHoleIds:[]};
const catalog={registeredBoards:[u,ring]},boardFor=r=>({...regular(),registeredBoardId:r.id,registeredBoardRevision:r.revision,mountingHoles:r.mountingHoleIds.map(holeId=>({holeId}))});
const plate=(r,pose={})=>({id:'p',name:r.name,xMm:0,yMm:0,rotationDeg:0,board:boardFor(r),...pose});
const layout=p=>({board:regular(),instances:[],subBoards:[p]});
const segment=(id,x1,y1,x2,y2)=>({id,from:{x:x1,y:y1},to:{x:x2,y:y2},beam:E.createBeam({powerMw:10})});
const source=(x,y,angle)=>({id:'s',center:{x,y},optics:{...E.defaults('source'),source:{...E.defaults('source').source,enabled:true,directionAngleDeg:angle}}});
const sceneWith=(module,s)=>({bounds:{xMin:-100,yMin:-100,xMax:250,yMax:250},modules:[module],elements:[s]});
const sourceModule=r=>R.sceneFor(layout(plate(r)),new Map(),{},[],E,catalog).modules[0];

test('registered optics only exposes explicit threaded holes, preserving IDs and thread sizes',()=>{
 const l=layout(plate(u)),session={segments:[segment('ray',0,15,100,15)]},index=H.build(l,session,{catalog});
 assert.deepEqual(index.holes.map(h=>[h.boardId,h.holeId,h.x,h.y]),[['p','T1',15,15]]);
 assert.equal(H.holeAt(index,{boardId:'p',columnIndex:0,rowIndex:0}),null);
 assert.equal(H.holeAt(index,{boardId:'p',holeId:'C1'}),null);assert.equal(H.holeAt(index,{boardId:'p',holeId:'P1'}),null);
 const h=H.holeAt(index,{boardId:'p',holeId:'T2'});assert.equal(h.thread,'M4x0.7');assert.equal(h.rowIndex,undefined);
 assert.equal(H.nearestValid(index,{x:15,y:15}).holeId,'T1');assert.equal(index.stats.gridSteps,4);
});
test('concave notches reveal carrier holes while actual board material masks them',()=>{
 const index=H.build(layout(plate(u)),{segments:[segment('r',0,62.5,100,62.5)]},{catalog});
 assert.ok(H.holeAt(index,{columnIndex:1,rowIndex:2}));assert.ok(H.holeAt(index,{columnIndex:2,rowIndex:2}));
 assert.equal(H.holeAt(index,{columnIndex:0,rowIndex:2}),null);
 assert.deepEqual(index.holes.map(h=>[h.x,h.y]),[[37.5,62.5],[62.5,62.5]]);
 const n=H.nearestValid(index,{x:37.5,y:62.5});assert.equal(n.boardId,null);near(n.distanceToCursorMm,0);
});
test('a window cannot be falsely pruned because all four search-rectangle corners are covered',()=>{
 const index=H.build(layout(plate(ring)),null,{catalog});assert.equal(index.holes.length,0);
 assert.ok(H.holeAt(index,{columnIndex:1,rowIndex:1}));assert.equal(H.holeAt(index,{columnIndex:0,rowIndex:0}),null);
 const h=H.nearestValid(index,{x:37.5,y:37.5});assert.ok(h);near(h.distanceToCursorMm,0);assert.equal(h.boardId,null);
 for(let i=0;i<50;i++){const p={x:i*17%100,y:i*31%100},n=H.nearestValid(index,p);const brute=[37.5,62.5].flatMap(x=>[37.5,62.5].map(y=>Math.hypot(x-p.x,y-p.y)));near(n.distanceToCursorMm,Math.min(...brute));}
});
test('explicit holes compose with small-board rotations and keep the exact optical path coordinate',()=>{
 const p=plate(u,{xMm:100,rotationDeg:90}),l=layout(p),session={segments:[segment('ray',0,15,100,15)]},index=H.build(l,session,{catalog});
 const h=H.holeAt(index,{boardId:'p',holeId:'T1'});near(h.x,85);near(h.y,15);assert.equal(h.localXMm,15);
 let actual;const result=H.probe(index,session,{x:83,y:18},{engine:{probe:(s,point)=>{actual=point;return[{segmentId:'ray'}]}}});
 assert.equal(result.hole.holeId,'T1');near(actual.x,85);near(actual.y,15);
});
test('registered root boards never invent regular grid holes and unknown revisions fail closed',()=>{
 const index=H.build({board:boardFor(u)},null,{catalog});assert.equal(H.holeAt(index,{columnIndex:1,rowIndex:1}),null);assert.equal(H.nearestValid(index,{x:15,y:15}).holeId,'T1');
 const p=plate(u);p.board.registeredBoardRevision='missing';assert.throws(()=>H.build(layout(p),null,{catalog}),/版本/);assert.throws(()=>R.sceneFor(layout(p),new Map(),{},[],E,catalog),/版本/);
});
test('scene preserves actual outline and windows after translating and rotating the board',()=>{
 const p=plate(ring,{xMm:120,yMm:30,rotationDeg:90}),m=R.sceneFor(layout(p),new Map(),{},[],E,catalog).modules[0];
 near(m.polygon[0].x,120);near(m.polygon[0].y,30);near(m.polygon[1].x,120);near(m.polygon[1].y,130);
 near(m.cutouts[0][0].x,95);near(m.cutouts[0][0].y,55);
 assert.equal(sourceModule(u).polygon.length,8);assert.equal(sourceModule(u).cutouts,undefined);
});
test('rays in a U-shaped opening enter the module only on the real material boundary',()=>{
 const m=sourceModule(u),s=E.createSession(sceneWith(m,source(50,150,-90)));assert.equal(s.pending[0].kind,'module');near(s.pending[0].point.x,50);near(s.pending[0].point.y,30);near(s.pending[0].pathMm,120);
 const done=E.advancePending(s,s.pending[0].id);assert.equal(done.pending.length,0);
 const miss=E.createSession(sceneWith(m,source(35,75,0)));near(miss.pending[0].point.x,70);near(miss.pending[0].point.y,75);
});
test('a source in an internal window is outside the module until it hits a rim; opposite rims are separate entries',()=>{
 const m=sourceModule(ring),s=E.createSession(sceneWith(m,source(50,50,-90)));assert.equal(s.segments[0].activeModuleIds.length,0);near(s.pending[0].point.y,25);
 let crossing=E.createSession(sceneWith(m,source(50,150,-90)));near(crossing.pending[0].point.y,100);
 crossing=E.advancePending(crossing,crossing.pending[0].id);near(crossing.pending[0].point.y,25);near(crossing.pending[0].pathMm,125);
 crossing=E.advancePending(crossing,crossing.pending[0].id);assert.equal(crossing.pending.length,0);
});
test('sampled curved contours over 32 points are accepted, repeated closing vertices do not contain all space, malformed loops fail',()=>{
 const polygon=Array.from({length:96},(_,i)=>({x:50+40*Math.cos(i*Math.PI/48),y:50+40*Math.sin(i*Math.PI/48)}));polygon.push({...polygon[0]});
 const m={id:'round',polygon},s=E.createSession(sceneWith(m,source(0,50,0)));near(s.pending[0].point.x,10);assert.equal(s.scene.modules[0].polygon.length,97);
 const closed=sourceModule(ring);closed.polygon.push({...closed.polygon[0]});closed.cutouts[0].push({...closed.cutouts[0][0]});const q=E.createSession(sceneWith(closed,source(50,50,-90)));near(q.pending[0].point.y,25);
 assert.throws(()=>E.createSession(sceneWith({...m,cutouts:[[{x:NaN,y:0},{x:1,y:0},{x:1,y:1}]]},source(0,50,0))),/多边形/);
});
test('measurement A/B keeps explicit hole IDs and uses real coordinates without fictitious row/column labels',()=>{
 const context={BreadboardEditor:class {},ZZLabOpticalHoleProbe:H};vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/measurement.js'),'utf8'),context);
 const l=layout(plate(u)),index=H.build(l,null,{catalog}),a=H.holeAt(index,{boardId:'p',holeId:'T1'}),b=H.holeAt(index,{boardId:'p',holeId:'T2'});
 const editor={catalog,snapshot:()=>l,kits:new Map(),measurement:{ids:[a.id,b.id],holes:{[a.id]:a,[b.id]:b}}};
 const result=context.BreadboardEditor.prototype.measurementResult.call(editor);near(result.dxMm,70);near(result.dyMm,70);assert.match(result.points[0].name,/T1.*M6x1\.0/);assert.match(result.points[1].name,/T2.*M4x0\.7/);assert.ok(!result.points.some(p=>/NaN|undefined|第.*行/.test(p.name)));
});
console.log(`${checks} registered-board optical geometry and measurement checks passed`);
