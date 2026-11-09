'use strict';
// Independent whole-editor oracle: pre-optimization validation versus current code.
// Normalize only explicit center-grid and minimum-hole policy changes, deriving
// the new alignment record independently; retain every other physical issue.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const copy=x=>JSON.parse(JSON.stringify(x)),sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const oldSource=fs.readFileSync(__dirname+'/../perf-baseline/layout.js','utf8'),newSource=fs.readFileSync(__dirname+'/static/layout.js','utf8'),engineSource=fs.readFileSync(__dirname+'/static/collision-engine.js','utf8');
const catalog=JSON.parse(fs.readFileSync(__dirname+'/catalog.json','utf8'));
function editor(source,engine=false){
 const context={window:{},document:{},Map,Set};vm.createContext(context);
 if(engine){vm.runInContext(engineSource,context);context.window.ZZLabCollisionEngine=context.ZZLabCollisionEngine}
 vm.runInContext(source,context);
 const e=Object.create(context.window.BreadboardEditor.prototype);
 Object.assign(e,{board:{widthMm:350,heightMm:225,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]},instances:[],kits:new Map(copy(catalog.kits).map(k=>[k.id,k]))});return e;
}
const before=editor(oldSource),after=editor(newSource,true),results=[];
const instance=(id,kitId,x=112.5,y=112.5,rotationDeg=0)=>({id,kitId,xMm:x,yMm:y,rotationDeg});
function expectedAlignment(e){return e.instances.flatMap(i=>{
 const layout=e.kits.get(i.kitId)?.layout,raw=layout?.mountingHoleOffsetsMm;if(!Array.isArray(raw)||!raw.length||raw.some(h=>!Number.isFinite(h.xMm)||!Number.isFinite(h.yMm)))return[];
 const unique=[];for(const h of raw)if(!unique.some(u=>Math.abs(u.xMm-h.xMm)<=1e-5&&Math.abs(u.yMm-h.yMm)<=1e-5))unique.push(h);
 const c=Math.round(Math.cos(i.rotationDeg*Math.PI/180)),s=Math.round(Math.sin(i.rotationDeg*Math.PI/180)),board=e.board;
 const positions=unique.map(h=>({xMm:i.xMm+c*h.xMm-s*h.yMm,yMm:i.yMm+s*h.xMm+c*h.yMm})).filter(h=>[[h.xMm,board.widthMm],[h.yMm,board.heightMm]].every(([v,limit])=>{const n=(v-board.edgeOffsetMm)/board.pitchMm;return v>=board.edgeOffsetMm-1e-5&&v<=limit-board.edgeOffsetMm+1e-5&&Math.abs(n-Math.round(n))<=1e-5})).map(h=>({xMm:Math.round(h.xMm*1e6)/1e6,yMm:Math.round(h.yMm*1e6)/1e6}));
 return[{instanceId:i.id,kitId:i.kitId,alignedCount:positions.length,totalCount:unique.length,requiredCount:layout.minimumAlignedMountingHoles??unique.length,partial:positions.length>0&&positions.length<unique.length,alignedPositionsMm:positions}];
})}
// Independent disk/polygon oracle for the explicit brown-contour-only policy.
function diskTouchesPolygon(center,radius,polygon){
 let inside=false;for(let n=0,j=polygon.length-1;n<polygon.length;j=n++){
  const a=polygon[j],b=polygon[n],dx=b.xMm-a.xMm,dy=b.yMm-a.yMm,length=dx*dx+dy*dy,t=length?Math.max(0,Math.min(1,((center.xMm-a.xMm)*dx+(center.yMm-a.yMm)*dy)/length)):0;
  if(Math.hypot(center.xMm-a.xMm-t*dx,center.yMm-a.yMm-t*dy)<=radius+1e-5)return true;
  if((a.yMm>center.yMm)!==(b.yMm>center.yMm)&&center.xMm<(b.xMm-a.xMm)*(center.yMm-a.yMm)/(b.yMm-a.yMm)+a.xMm)inside=!inside;
 }return inside;
}
function check(name,mutate,expected){
 mutate(before);mutate(after);
 const a=copy(before.validation()),b=copy(after.validation());
 // A part center need not coincide with a threaded board hole. The old oracle
 // imposed that extra restriction even when its real mounting holes aligned.
 a.issues=a.issues.filter(issue=>issue.code!=='off_grid'||!issue.instanceIds.every(id=>{const instance=before.instances.find(i=>i.id===id),holes=before.kits.get(instance?.kitId)?.layout?.mountingHoleOffsetsMm;return Array.isArray(holes)&&holes.length>0&&holes.every(h=>Number.isFinite(h.xMm)&&Number.isFinite(h.yMm))}));
 a.issues=a.issues.flatMap(issue=>{if(issue.code!=='mounting_hole_obstructed')return[issue];const index=Number(issue.holeIds[0].slice(1))-1,h=before.board.mountingHoles[index],center={xMm:before.board.edgeOffsetMm+h.columnIndex*before.board.pitchMm,yMm:before.board.edgeOffsetMm+h.rowIndex*before.board.pitchMm},blockers=before.instances.filter(i=>before.worldPolygons(i).some(p=>diskTouchesPolygon(center,5.5,p)));return blockers.length?[{...issue,instanceIds:blockers.map(i=>i.id),message:`${issue.holeIds[0]} 安装沉孔被器件 ${blockers.map(i=>before.label(i)).join('、')} 遮挡，请移开器件或重新自动选孔。`}]:[]});
 a.mountingAlignment=expectedAlignment(before);
 a.issues=a.issues.flatMap(issue=>{if(issue.code!=='mounting_mismatch')return[issue];const row=a.mountingAlignment.find(r=>r.instanceId===issue.instanceIds[0]),kit=before.kits.get(row?.kitId);if(kit?.layout?.minimumAlignedMountingHoles==null)return[issue];if(row.alignedCount>=row.requiredCount)return[];const i=before.instances.find(i=>i.id===row.instanceId);return[{...issue,message:`${before.label(i)} ${kit.name} 的安装孔已对齐 ${row.alignedCount}/${row.totalCount}，至少需要 ${row.requiredCount} 个不同的孔，请调整孔距或位置。`}]});a.valid=!a.issues.length;
 assert.deepEqual(b,a,name);
 assert.equal(after.validation(),after.validation(),name+' should reuse unchanged validation');
 if(expected)expected(b);
 results.push({name,issueCount:a.issues.length,collisionCount:a.issues.filter(i=>i.code==='collision').length,sha256:sha(JSON.stringify(a))});
}
const rectangle=(x0,y0,x1,y1)=>[{xMm:x0,yMm:y0},{xMm:x1,yMm:y0},{xMm:x1,yMm:y1},{xMm:x0,yMm:y1}];
function synthetic(id,polygons,base={xMin:-5,yMin:-5,xMax:5,yMax:5}){return{id,name:id,layout:{topViewUrl:id+'.svg',widthMm:40,heightMm:40,anchorXMm:20,anchorYMm:20,baseBoundsMm:base,collisionPolygonsMm:polygons,mountingHoleOffsetsMm:[{xMm:0,yMm:0}]}}}
check('install synthetic exact-contact and concavity catalog',e=>{
 e.kits.set('square',synthetic('square',[rectangle(-10,-10,10,10)]));
 e.kits.set('u',synthetic('u',[[{xMm:0,yMm:0},{xMm:40,yMm:0},{xMm:40,yMm:40},{xMm:30,yMm:40},{xMm:30,yMm:10},{xMm:10,yMm:10},{xMm:10,yMm:40},{xMm:0,yMm:40}]]));
 e.kits.set('small',synthetic('small',[rectangle(-3,-3,3,3)]));
 e.instances=[instance('a','square'),instance('b','square',132.5,112.5)];
},r=>assert.equal(r.issues.filter(i=>i.code==='collision').length,1));
check('edge contact',e=>{e.instances[1].xMm=132.5;e.instances[1].yMm=112.5});
check('corner contact',e=>{e.instances[1].xMm=132.5;e.instances[1].yMm=132.5},r=>assert.ok(r.issues.some(i=>i.code==='collision')));
check('tiny actual separation',e=>{e.instances[1].xMm=132.50002},r=>assert.ok(!r.issues.some(i=>i.code==='collision')));
check('contained part',e=>{e.instances=[instance('a','square'),instance('b','small')]},r=>assert.ok(r.issues.some(i=>i.code==='collision')));
check('open concavity remains non-colliding',e=>{e.instances=[instance('u','u',75,75),instance('s','small',95,100)]},r=>assert.ok(!r.issues.some(i=>i.code==='collision')));
check('move into concave arm',e=>{e.instances[1].xMm=80},r=>assert.ok(r.issues.some(i=>i.code==='collision')));
check('upper contour may overhang if base stays inside',e=>{e.instances=[instance('u','u',325,112.5)]},r=>assert.ok(!r.issues.some(i=>i.code==='out_of_bounds')));
check('base outside remains rejected',e=>{e.instances[0].xMm=347.5},r=>assert.ok(r.issues.some(i=>i.code==='out_of_bounds')));
check('four unobstructed mounting holes',e=>{e.instances=[instance('a','square')];e.board.mountingHoles=[{columnIndex:0,rowIndex:0},{columnIndex:26,rowIndex:0},{columnIndex:0,rowIndex:16},{columnIndex:26,rowIndex:16}]});
check('mounting hole obstructed by actual outline',e=>{e.instances[0].xMm=12.5;e.instances[0].yMm=12.5},r=>assert.ok(r.issues.some(i=>i.code==='mounting_hole_obstructed')));
check('same board object changed to insufficient thickness',e=>{e.board.thicknessMm=5},r=>assert.ok(r.issues.some(i=>i.code==='board_mounting_invalid')));
check('same mounting array changed to wrong phase',e=>{e.board.thicknessMm=12.7;e.board.mountingHoles[1].columnIndex=25},r=>assert.ok(r.issues.some(i=>i.code==='board_mounting_invalid')));
check('board replacement invalidates mounting validation',e=>{e.board={...e.board,widthMm:100,heightMm:100}},r=>assert.ok(r.issues.some(i=>i.code==='board_mounting_invalid')));
check('clear holes and restore board',e=>{e.board={...e.board,widthMm:350,heightMm:225,mountingHoles:[]};e.instances=[]});
check('25 mm carrier accepts a center between holes when all four screws align',e=>{e.kits.set('four-screws',{...synthetic('four-screws',[rectangle(-5,-5,5,5)]),layout:{...synthetic('four-screws',[rectangle(-5,-5,5,5)]).layout,mountingHoleOffsetsMm:[{xMm:-12.5,yMm:-12.5},{xMm:12.5,yMm:-12.5},{xMm:12.5,yMm:12.5},{xMm:-12.5,yMm:12.5}]}});e.board.pitchMm=25;e.instances=[instance('screws','four-screws',100,100)]},r=>assert.equal(r.valid,true));
check('center on a 25 mm board hole does not hide actual screw mismatch',e=>{e.instances[0].xMm=112.5;e.instances[0].yMm=112.5},r=>assert.ok(r.issues.some(i=>i.code==='mounting_mismatch')));
check('restore 12.5 mm carrier',e=>{e.board.pitchMm=12.5;e.instances=[]});

let seed=20260924;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296};
const kits=catalog.kits.filter(k=>k.layout?.placementAllowed!==false);
for(let round=0;round<24;round++){
 const n=6+Math.floor(random()*13),data=Array.from({length:n},(_,i)=>instance('r'+i,kits[Math.floor(random()*kits.length)].id,12.5+Math.floor(random()*26)*12.5,12.5+Math.floor(random()*16)*12.5,Math.floor(random()*4)*90));
 check('actual catalog seeded scene '+round,e=>{e.instances=copy(data)});
 check('actual catalog pose update '+round,e=>{e.instances[0].xMm+=12.5;e.instances[0].rotationDeg=(e.instances[0].rotationDeg+90)%360});
}
check('reorder existing IDs',e=>{e.instances.reverse()});
check('delete live IDs',e=>{e.instances.splice(0,3)});
const reusedId=before.instances[0].id;
check('remove and reuse ID with another kit',e=>{e.instances.shift();e.instances.push(instance(reusedId,'square',125,125))});
check('replace catalog layout for an existing kit',e=>{const old=e.kits.get('square');e.kits.set('square',{...old,layout:{...old.layout,collisionPolygonsMm:[rectangle(-50,-50,50,50)]}})});
check('replace whole kit map',e=>{e.kits=new Map(copy([...e.kits]));e.kits.get('square').layout={...e.kits.get('square').layout,collisionPolygonsMm:[rectangle(-5,-5,5,5)]}});
check('empty project removes cached instances and pairs',e=>{e.instances=[]},r=>assert.equal(r.valid,true));
check('metadata cache fixture',e=>{e.instances=[instance('metadata','square',100,100)]});
check('in-place base bounds change',e=>{e.kits.get('square').layout.baseBoundsMm.xMax=300},r=>assert.ok(r.issues.some(i=>i.code==='out_of_bounds')));
check('in-place name updates validation message',e=>{e.kits.get('square').name='Renamed square'},r=>assert.ok(r.issues.some(i=>i.message.includes('Renamed square'))));
check('in-place base bounds restore',e=>{e.kits.get('square').layout.baseBoundsMm.xMax=5});
check('in-place placement permission change',e=>{e.kits.get('square').layout.placementAllowed=false},r=>assert.ok(r.issues.some(i=>i.code==='placement_unavailable')));
check('in-place topview URL change',e=>{e.kits.get('square').layout.placementAllowed=true;e.kits.get('square').layout.topViewUrl=null},r=>assert.ok(r.issues.some(i=>i.code==='placement_unavailable')));
check('in-place mounting offset change',e=>{e.kits.get('square').layout.topViewUrl='restored.svg';e.kits.get('square').layout.mountingHoleOffsetsMm[0].xMm=1},r=>assert.ok(r.issues.some(i=>i.code==='mounting_mismatch')));
check('mount radius cache fixture',e=>{e.kits.get('square').layout.mountingHoleOffsetsMm[0].xMm=0;e.kits.get('square').layout.mountingHoleRadiusMm=1;e.board.mountingHoles=[{columnIndex:8,rowIndex:7},{columnIndex:24,rowIndex:7},{columnIndex:8,rowIndex:15},{columnIndex:24,rowIndex:15}]},r=>assert.ok(!r.issues.some(i=>i.code==='mounting_hole_obstructed')));
check('mounting screw estimates outside the brown contour no longer obstruct counterbores',e=>{e.kits.get('square').layout.mountingHoleRadiusMm=10},r=>assert.ok(!r.issues.some(i=>i.code==='mounting_hole_obstructed')));
// The current renderer deliberately tightens an old missing-asset bug: an empty
// URL is unavailable. This invalid-input improvement is not oracle equivalence.
after.kits.get('square').layout.topViewUrl='';
assert.ok(after.validation().issues.some(i=>i.code==='placement_unavailable'));
const report={timestamp:new Date().toISOString(),baselineSha256:sha(oldSource),candidateSha256:sha(newSource),engineSha256:sha(engineSource),catalogVersion:catalog.version,checks:results.length,passed:true,intentionalAnchorDifference:'Known real mounting-hole patterns are validated by their holes; the obsolete center off_grid issue is removed from the baseline only. Explicit minimumAlignedMountingHoles entries use the independently counted unique aligned holes; alignment records are independently derived. Counterbore obstruction is independently normalized to exact brown-contour/disk intersection; blue base and screw estimates outside that contour no longer block holes. Every other mounting_mismatch, collision and boundary issue remains compared verbatim.',intentionalInvalidInputDifference:'Empty or whitespace-only topViewUrl is now placement_unavailable; old code accepted any string. Real catalog URLs unchanged.',results};
fs.writeFileSync(__dirname+'/data_evidence/performance_validation_equivalence.json',JSON.stringify(report,null,2)+'\n');
console.log(`${results.length} independent physical-validation comparisons passed (all messages, IDs and order; removed center-grid restriction explicitly normalized), including contact, concavity, mounting mutations, 24 actual-kit scenes, deletion and catalog replacement.`);
