'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const codec=require('./static/project-file.js'),shared=require('./static/shared-project.js');
const clone=v=>JSON.parse(JSON.stringify(v)),now='2026-09-24T12:00:00.000Z';
const footprint={topViewUrl:'actual.svg',widthMm:60,heightMm:60,anchorXMm:30,anchorYMm:30,baseBoundsMm:{xMin:-17.5,yMin:-17.5,xMax:17.5,yMax:17.5},mountingHoleOffsetsMm:[{xMm:-12.5,yMm:-12.5},{xMm:12.5,yMm:-12.5},{xMm:-12.5,yMm:12.5},{xMm:12.5,yMm:12.5}]};
const catalog={version:'shared-test',kits:[{id:'mirror',name:'反射镜架',layout:clone(footprint),opticalSlots:[{id:'optic',type:'mirror',quantity:1}]},{id:'wave',name:'波片',layout:clone(footprint),opticalSlots:[{id:'optic',type:'waveplate',quantity:1}]},{id:'inactive',name:'未放置器件',layout:clone(footprint),opticalSlots:[]},{id:'module',name:'独立模块',layout:{placementAllowed:false},opticalSlots:[{id:'optic',type:'mirror',quantity:3}]}]};
let serial=0;const options={catalog,now,validateBoard:b=>b,newId:kind=>kind+'-new-'+(++serial)};
const instance=(id,kitId,xMm,yMm,rotationDeg=0)=>({id,kitId,xMm,yMm,rotationDeg});
const extra=(id,kitId,quantity,instanceId)=>({id,kitId,kind:'standard',name:id,model:'M2x6',quantity,unit:'颗',notes:'',...(instanceId?{instanceId}:{})});
const board=()=>({widthMm:350,heightMm:225,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[{columnIndex:0,rowIndex:0},{columnIndex:26,rowIndex:0},{columnIndex:0,rowIndex:16},{columnIndex:26,rowIndex:16}]});
function source(){return codec.create({metadata:{name:'Shared',notes:'source notes',createdAt:now,updatedAt:now},catalogVersion:catalog.version,layout:{board:board(),instances:[instance('a','mirror',62.5,62.5),instance('b','mirror',112.5,62.5,90),instance('c','wave',175,100,270)]},optical:{'a::optic':{model:'',wavelength:'532',kind:'standard'},'b::optic':{model:'M-780',wavelength:'780'},'c::optic':{model:'',wavelength:'',opticalType:'half-wave'},'module:module::optic':{model:'MODULE-SOURCE',wavelength:'1064'}},extras:[extra('source-global',null,4),extra('source-mirror-kit','mirror',2),extra('source-wave-kit','wave',1),extra('source-instance','mirror',3,'a'),extra('source-inactive','inactive',11),extra('source-module','module',13)],moduleQuantities:[['module',4]],ui:{mountingSelection:{rowParity:'odd',columnParity:'even'},view:{x:-20,y:-10,w:400,h:260},selectedIds:['b']}},options)}
function current(){return codec.create({metadata:{name:'Current',notes:'keep current notes',createdAt:'2026-09-23T00:00:00.000Z',updatedAt:now},catalogVersion:catalog.version,layout:{board:board(),instances:[instance('old','mirror',225,112.5,180)]},optical:{'old::optic':{model:'CURRENT-OPTIC',wavelength:'405'},'module:module::optic':{model:'CURRENT-MODULE',wavelength:'488'}},extras:[extra('current-global',null,3),extra('current-per-kit','mirror',7),extra('current-instance','mirror',2,'old'),extra('current-inactive','inactive',5),extra('current-module','module',6)],moduleQuantities:[['module',9]],ui:{mountingSelection:{rowParity:'even',columnParity:'odd'},view:{x:5,y:10,w:300,h:200},selectedIds:['old']}},options)}
const has=(p,id)=>p.extras.some(e=>e.id===id);
function quantities(project,id){const i=project.layout.instances.find(i=>i.id===id);return project.extras.filter(e=>e.instanceId?e.instanceId===id:e.kitId===i.kitId).reduce((s,e)=>s+e.quantity,0)}
const reject=(fn,code)=>assert.throws(fn,e=>e instanceof shared.SharedProjectError&&e.code===code);
let passed=0;function test(name,fn){fn();passed++;console.log('PASS '+name)}

test('whole-canvas snapshot preserves board and relevant global/per-kit rows but removes unrelated modules/templates',()=>{
 const p=source(),before=clone(p),result=shared.subset(p,null,options);
 assert.deepEqual(p,before);assert.deepEqual(result.layout.board,p.layout.board);assert.equal(result.layout.instances.length,3);
 assert.ok(has(result,'source-global')&&has(result,'source-mirror-kit')&&has(result,'source-instance'));
 assert.ok(!has(result,'source-module')&&!has(result,'source-inactive'));assert.deepEqual(result.moduleQuantities,[]);
 assert.ok(!('module:module::optic'in result.optical));assert.deepEqual(result.ui.selectedIds,['a','b','c']);
});
test('selected subset strips global extras and mounting holes while retaining per-instance blank optical values',()=>{
 const p=source(),before=clone(p),result=shared.subset(p,['a'],options);
 assert.deepEqual(p,before);assert.deepEqual(result.layout.instances,[p.layout.instances[0]]);
 assert.deepEqual(result.layout.board.mountingHoles,[]);assert.deepEqual(result.ui.mountingSelection,{rowParity:'any',columnParity:'any'});
 assert.deepEqual(Object.keys(result.optical),['a::optic']);assert.deepEqual(result.optical['a::optic'],p.optical['a::optic']);
 assert.deepEqual(result.extras.map(e=>e.id),['source-mirror-kit','source-instance']);
 assert.deepEqual(result.moduleQuantities,[]);
 assert.ok(!has(shared.subset(p,['a','b','c'],options),'source-global'),'explicit all-selected subset is still selection scope');
});
test('invalid or empty subset is rejected atomically',()=>{
 const p=source(),before=clone(p);reject(()=>shared.subset(p,[],options),'empty_combination');reject(()=>shared.subset(p,['missing'],options),'unknown_instance');reject(()=>shared.subset(p,['a','a'],options),'invalid_selection');assert.deepEqual(p,before);
});
test('merge freezes both sides per-kit extras without giving current instances shared accessories',()=>{
 const cur=current(),incoming=source(),oldCur=clone(cur),oldSource=clone(incoming),r=shared.merge(cur,incoming,options),p=r.project;
 assert.deepEqual(cur,oldCur);assert.deepEqual(incoming,oldSource);
 assert.equal(p.layout.instances.length,4);assert.equal(quantities(p,'old'),9,'7 per-kit plus2 own, unchanged');
 const ids=Object.fromEntries(r.mapping.map(m=>[m.fromId,m.toId]));
 assert.equal(quantities(p,ids.a),9,'2 per-kit +3 own +4 shared-global');assert.equal(quantities(p,ids.b),2);assert.equal(quantities(p,ids.c),1);
 assert.equal(p.extras.filter(e=>e.kitId===null).length,1);assert.equal(p.extras.find(e=>e.kitId===null).quantity,3);
 assert.ok(!p.extras.some(e=>e.kitId==='mirror'&&!e.instanceId));assert.ok(has(p,'current-inactive')&&has(p,'current-module'));
 assert.deepEqual(p.optical[ids.a+'::optic'],incoming.optical['a::optic']);assert.equal(p.optical[ids.c+'::optic'].wavelength,'');
 assert.deepEqual(p.optical['old::optic'],cur.optical['old::optic']);assert.deepEqual(p.optical['module:module::optic'],cur.optical['module:module::optic']);
 assert.deepEqual(p.layout.board,cur.layout.board);assert.deepEqual(p.moduleQuantities,cur.moduleQuantities);assert.deepEqual(p.metadata,cur.metadata);
 assert.deepEqual(p.ui.view,cur.ui.view);assert.deepEqual(p.ui.mountingSelection,cur.ui.mountingSelection);assert.deepEqual(p.ui.selectedIds,r.insertedIds);
 assert.ok(r.insertedIds.every(id=>!['a','b','c','old'].includes(id)));assert.equal(new Set(p.extras.map(e=>e.id)).size,p.extras.length);
});
test('repeated insertions remain independent and add shared global quantity once per combination',()=>{
 const first=shared.merge(current(),source(),options),second=shared.merge(first.project,source(),options),p=second.project;
 assert.equal(p.layout.instances.length,7);assert.equal(quantities(p,'old'),9);
 for(const r of[first,second]){const ids=Object.fromEntries(r.mapping.map(m=>[m.fromId,m.toId]));assert.equal(quantities(p,ids.a),9);assert.equal(quantities(p,ids.b),2);assert.equal(quantities(p,ids.c),1)}
 assert.equal(p.extras.filter(e=>e.name==='source-global').reduce((s,e)=>s+e.quantity,0),8);
 assert.equal(p.extras.find(e=>e.id==='current-global').quantity,3);
 assert.equal(new Set(p.layout.instances.map(i=>i.id)).size,7);assert.deepEqual(p.ui.selectedIds,second.insertedIds);
 const firstId=first.insertedIds[0],secondId=second.insertedIds[0];p.optical[secondId+'::optic'].model='SECOND-ONLY';assert.equal(p.optical[firstId+'::optic'].model,'');
});
test('inactive same-kit template blocks insertion without losing the template or any original state',()=>{
 const cur=current();cur.layout.instances=[];cur.optical={'module:module::optic':cur.optical['module:module::optic']};cur.extras=cur.extras.filter(e=>!e.instanceId);cur.ui.selectedIds=[];
 const before=clone(cur);reject(()=>shared.merge(cur,source(),options),'inactive_template_conflict');assert.deepEqual(cur,before);assert.ok(has(cur,'current-per-kit'));
 assert.throws(()=>shared.merge(cur,source(),options),/反射镜架.*预存了每套配件.*打开共享工程/);
});
test('unaffected inactive templates remain in a successful merged project',()=>{
 const r=shared.merge(current(),shared.subset(source(),['a'],options),options);assert.deepEqual(r.project.extras.find(e=>e.id==='current-inactive'),current().extras.find(e=>e.id==='current-inactive'));
});
test('common offset preserves all relative coordinates and orientations even at board bounds',()=>{
 const s=source(),r=shared.merge(current(),s,{...options,offsetMm:{xMm:99999,yMm:99999}}),added=r.project.layout.instances.filter(i=>r.insertedIds.includes(i.id));
 for(let n=0;n<added.length;n++){assert.equal(added[n].rotationDeg,s.layout.instances[n].rotationDeg);assert.equal(added[n].xMm-s.layout.instances[n].xMm,r.offsetMm.xMm);assert.equal(added[n].yMm-s.layout.instances[n].yMm,r.offsetMm.yMm);assert.ok(added[n].xMm-17.5>=0&&added[n].xMm+17.5<=350);assert.ok(added[n].yMm-17.5>=0&&added[n].yMm+17.5<=225)}
 assert.equal((r.offsetMm.xMm/12.5)%1,0);assert.equal((r.offsetMm.yMm/12.5)%1,0);
});
test('same pitch with different edge phase aligns the entire combination onto the target grid',()=>{
 const s=source();s.layout.board.edgeOffsetMm=7.5;for(const i of s.layout.instances){i.xMm-=5;i.yMm-=5}
 const r=shared.merge(current(),s,options);for(const i of r.project.layout.instances.filter(i=>r.insertedIds.includes(i.id))){assert.equal(((i.xMm-12.5)/12.5)%1,0);assert.equal(((i.yMm-12.5)/12.5)%1,0)}
});
test('incompatible pitch, misaligned source holes, too-small board and invalid offset fail before applying anything',()=>{
 const cur=current(),before=clone(cur);let s=source();s.layout.board.pitchMm=25;reject(()=>shared.merge(cur,s,options),'incompatible_pitch');
 s=source();s.layout.instances[0].xMm+=1;reject(()=>shared.merge(cur,s,options),'incompatible_mounting');
 const small=current();small.layout.board.widthMm=100;small.layout.board.heightMm=100;reject(()=>shared.merge(small,source(),options),'group_does_not_fit');
 reject(()=>shared.merge(cur,source(),{...options,offsetMm:{xMm:NaN,yMm:0}}),'invalid_offset');assert.deepEqual(cur,before);
});
test('25 mm PBS mounting holes merge without forcing the centre onto a board hole',()=>{
 const cur=current();cur.layout.board={...cur.layout.board,pitchMm:25,mountingHoles:[]};cur.layout.instances[0].yMm=125;
 for(const rotation of[0,90,180,270]){
   const s=shared.subset(source(),['a','b'],options);s.layout.board={...s.layout.board,pitchMm:25,mountingHoles:[]};Object.assign(s.layout.instances[0],{xMm:50,yMm:50,rotationDeg:rotation});Object.assign(s.layout.instances[1],{xMm:100,yMm:50,rotationDeg:rotation});
   const before=clone(s),r=shared.merge(cur,s,{...options,offsetMm:{xMm:0,yMm:0}}),added=r.project.layout.instances.filter(i=>r.insertedIds.includes(i.id));
   assert.deepEqual(r.offsetMm,{xMm:0,yMm:0});assert.deepEqual(added.map(({id,...i})=>i),s.layout.instances.map(({id,...i})=>i));assert.deepEqual(s,before);
   for(const i of added){assert.notEqual(((i.xMm-12.5)/25)%1,0,'a valid PBS centre lies halfway between board holes');for(const h of footprint.mountingHoleOffsetsMm){const a=rotation*Math.PI/180,x=i.xMm+Math.round(Math.cos(a))*h.xMm-Math.round(Math.sin(a))*h.yMm,y=i.yMm+Math.round(Math.sin(a))*h.xMm+Math.round(Math.cos(a))*h.yMm;assert.equal(((x-12.5)/25)%1,0);assert.equal(((y-12.5)/25)%1,0)}}
 }
});
test('25 mm shared merge translates actual mounting-hole phase between different first-hole offsets',()=>{
 const cur=current();cur.layout.board={...cur.layout.board,pitchMm:25,mountingHoles:[]};cur.layout.instances[0].yMm=125;
 const s=shared.subset(source(),['a'],options);s.layout.board={...s.layout.board,pitchMm:25,edgeOffsetMm:7.5,mountingHoles:[]};Object.assign(s.layout.instances[0],{xMm:45,yMm:45});
 const r=shared.merge(cur,s,{...options,offsetMm:{xMm:0,yMm:0}}),i=r.project.layout.instances.at(-1);
 assert.deepEqual(r.offsetMm,{xMm:5,yMm:5});assert.equal(i.xMm,50);assert.equal(i.yMm,50);
 for(const h of footprint.mountingHoleOffsetsMm){assert.equal(((i.xMm+h.xMm-12.5)/25)%1,0);assert.equal(((i.yMm+h.yMm-12.5)/25)%1,0)}
});
test('an in-bounds base may retain its datum outside the first-hole rectangle',()=>{
 const otherCatalog=clone(catalog);Object.assign(otherCatalog.kits[0].layout,{baseBoundsMm:{xMin:0,yMin:0,xMax:25,yMax:25},mountingHoleOffsetsMm:[{xMm:12.5,yMm:12.5}]});
 const cur=current(),s=shared.subset(source(),['a'],options);cur.layout.board={...cur.layout.board,pitchMm:25,mountingHoles:[]};s.layout.board={...s.layout.board,pitchMm:25,mountingHoles:[]};Object.assign(s.layout.instances[0],{xMm:0,yMm:0});
 const r=shared.merge(cur,s,{...options,catalog:otherCatalog,offsetMm:{xMm:0,yMm:0}}),i=r.project.layout.instances.at(-1);
 assert.deepEqual(r.offsetMm,{xMm:0,yMm:0});assert.equal(i.xMm,0);assert.equal(i.yMm,0);assert.ok(i.xMm<r.project.layout.board.edgeOffsetMm);
});
const realCatalog=JSON.parse(fs.readFileSync(__dirname+'/catalog.json','utf8'));
const laserOptions={...options,catalog:realCatalog};
function laserProject(instances,overrides={},opts=laserOptions){return codec.create({metadata:{name:'Laser module'},catalogVersion:opts.catalog.version,layout:{board:{...board(),widthMm:625,heightMm:625,pitchMm:31.25,mountingHoles:[],...overrides},instances},optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],mountingSelection:{rowParity:'any',columnParity:'any'},view:null}},opts)}
function laserPose(rotation){const angle=rotation*Math.PI/180,c=Math.round(Math.cos(angle)),s=Math.round(Math.sin(angle)),dx=83.5*c+125*s,dy=83.5*s-125*c,snap=value=>12.5+Math.round((value-12.5)/31.25)*31.25;return instance('laser','laser-308nm',snap(312.5+dx)-dx,snap(312.5+dy)-dy,rotation)}
function alignedLaserHoles(i,b,cat=realCatalog){const holes=cat.kits.find(k=>k.id===i.kitId).layout.mountingHoleOffsetsMm,angle=i.rotationDeg*Math.PI/180,c=Math.round(Math.cos(angle)),s=Math.round(Math.sin(angle));return holes.filter(h=>[[i.xMm+c*h.xMm-s*h.yMm,b.widthMm],[i.yMm+s*h.xMm+c*h.yMm,b.heightMm]].every(([v,size])=>v>=b.edgeOffsetMm-1e-5&&v<=size-b.edgeOffsetMm+1e-5&&Math.abs((v-b.edgeOffsetMm)/b.pitchMm-Math.round((v-b.edgeOffsetMm)/b.pitchMm))<=1e-5)).length}
test('real two-of-four laser can be shared and merged at all four rotations',()=>{
 for(const rotation of[0,90,180,270]){
   const s=laserProject([laserPose(rotation)]),cur=laserProject([]),before=clone(s),r=shared.merge(cur,s,{...laserOptions,offsetMm:{xMm:0,yMm:0}}),added=r.project.layout.instances[0];
   assert.equal(alignedLaserHoles(s.layout.instances[0],s.layout.board),2);assert.equal(alignedLaserHoles(added,r.project.layout.board),2);
   assert.deepEqual(r.offsetMm,{xMm:0,yMm:0});assert.deepEqual(added,{...s.layout.instances[0],id:added.id});assert.deepEqual(s,before);assert.equal(cur.layout.instances.length,0);
 }
});
test('partial mounting shared groups keep relative coordinates and their true paired hole phase',()=>{
 const s=laserProject([laserPose(0),{...laserPose(0),id:'laser-two',xMm:960.25}],{widthMm:1250,heightMm:900}),cur=laserProject([],{widthMm:1280,heightMm:900,edgeOffsetMm:7.5}),before=clone(s);
 const r=shared.merge(cur,s,{...laserOptions,offsetMm:{xMm:0,yMm:0}}),added=r.project.layout.instances;
 assert.deepEqual(r.offsetMm,{xMm:-5,yMm:-5});assert.equal(added[1].xMm-added[0].xMm,656.25);assert.equal(added[1].yMm-added[0].yMm,0);
 for(let n=0;n<added.length;n++){assert.equal(alignedLaserHoles(added[n],r.project.layout.board),2);assert.equal(added[n].xMm-s.layout.instances[n].xMm,r.offsetMm.xMm);assert.equal(added[n].yMm-s.layout.instances[n].yMm,r.offsetMm.yMm)}assert.deepEqual(s,before);
});
test('shared minimum counts distinct holes while components without minimum still require all holes',()=>{
 const s=laserProject([laserPose(0)]),cur=laserProject([]),strict=clone(realCatalog);delete strict.kits.find(k=>k.id==='laser-308nm').layout.minimumAlignedMountingHoles;
 reject(()=>shared.merge(cur,s,{...laserOptions,catalog:strict}),'incompatible_mounting');
 const duplicated=clone(realCatalog),l=duplicated.kits.find(k=>k.id==='laser-308nm').layout;l.mountingHoleOffsetsMm=[{xMm:83.5,yMm:-125},{xMm:83.500001,yMm:-125},{xMm:83.5,yMm:-125}];
 reject(()=>shared.merge(cur,s,{...laserOptions,catalog:duplicated}),'incompatible_mounting');
 const shifted=clone(s);shifted.layout.instances[0].xMm+=1;reject(()=>shared.merge(cur,shifted,laserOptions),'incompatible_mounting');
});
test('shared merge never counts matching X and Y coordinates from different physical holes',()=>{
 const crossed=clone(realCatalog),l=crossed.kits.find(k=>k.id==='laser-308nm').layout;l.mountingHoleOffsetsMm=[{xMm:0,yMm:12.5},{xMm:25,yMm:12.5},{xMm:12.5,yMm:0},{xMm:12.5,yMm:25}];
 const opts={...laserOptions,catalog:crossed},s=laserProject([instance('laser','laser-308nm',312.5,312.5)],{pitchMm:25},opts),cur=laserProject([],{pitchMm:25},opts);
 reject(()=>shared.merge(cur,s,opts),'incompatible_mounting');
});
test('collision with existing layout is permitted for subsequent group dragging',()=>{
 const cur=current(),s=shared.subset(source(),['a'],options);s.layout.instances[0].xMm=cur.layout.instances[0].xMm;s.layout.instances[0].yMm=cur.layout.instances[0].yMm;
 const r=shared.merge(cur,s,{...options,offsetMm:{xMm:0,yMm:0}});assert.equal(r.project.layout.instances[0].xMm,r.project.layout.instances[1].xMm);assert.equal(r.project.layout.instances[0].yMm,r.project.layout.instances[1].yMm);
});
test('upper imagery can overhang when actual base and mounting points fit',()=>{
 const single=shared.subset(source(),['a'],options);const r=shared.merge(current(),single,{...options,offsetMm:{xMm:-999,yMm:-999}}),i=r.project.layout.instances.at(-1);assert.equal(i.xMm,25);assert.ok(i.xMm-30<0,'upper imagery extends beyond plate');assert.ok(i.xMm-17.5>=0,'actual base stays inside');
});
test('500-instance limit, unavailable kit, and mounting grid incompatibility are rejected',()=>{
 let s=source();s.layout.instances=Array.from({length:500},(_,n)=>instance('i'+n,'mirror',62.5,62.5));s.optical={};s.extras=[];s.ui.selectedIds=[];reject(()=>shared.merge(current(),s,options),'too_many_instances');
 const otherCatalog=clone(catalog);otherCatalog.kits[0].layout.topViewUrl='';reject(()=>shared.merge(current(),source(),{...options,catalog:otherCatalog}),'placement_unavailable');
 otherCatalog.kits[0].layout.topViewUrl='actual.svg';otherCatalog.kits[0].layout.mountingHoleOffsetsMm[0].xMm=1;reject(()=>shared.merge(current(),source(),{...options,catalog:otherCatalog}),'incompatible_mounting');
});
test('ID generators retry collisions and fail boundedly without mutating inputs',()=>{
 const cur=current(),before=clone(cur);let n=0;const r=shared.merge(cur,source(),{...options,newId:()=>n++<3?'old':'retry-'+n});assert.equal(new Set(r.project.layout.instances.map(i=>i.id)).size,4);
 reject(()=>shared.merge(cur,source(),{...options,newId:()=> 'old'}),'duplicate_id_generator');reject(()=>shared.merge(cur,source(),{...options,newId:()=> 'module:invalid'}),'invalid_id_generator');assert.deepEqual(cur,before);
});
test('each existing same-kit instance keeps its prior per-kit quantity',()=>{
 const cur=current();cur.layout.instances.push(instance('old-two','mirror',275,150));const r=shared.merge(cur,source(),options);
 assert.equal(quantities(r.project,'old'),9);assert.equal(quantities(r.project,'old-two'),7);
 assert.equal(quantities(r.project,r.insertedIds[1]),2);
});
test('expansion beyond the project item limit is rejected before generating any IDs',()=>{
 const cur=current(),s=source();s.extras=Array.from({length:1000},(_,i)=>extra('per-kit-'+i,'mirror',1));const before=clone(cur);let calls=0;
 reject(()=>shared.merge(cur,s,{...options,newId:()=>{calls++;return 'should-not-run'}}),'too_many_extras');assert.equal(calls,0);assert.deepEqual(cur,before);
});
for(const [parentPitch,childPitch]of[[25,12.5],[12.5,25]])test(`mounting ${childPitch} mm board onto ${parentPitch} mm flat board preserves both boards and local component poses`,()=>{
 const cur=current(),s=source();cur.layout.board={...cur.layout.board,widthMm:600,heightMm:450,pitchMm:parentPitch,mountingHoles:[]};s.layout.board.pitchMm=childPitch;
 if(childPitch===25)s.layout.board.mountingHoles=[{columnIndex:0,rowIndex:0},{columnIndex:12,rowIndex:0},{columnIndex:0,rowIndex:8},{columnIndex:12,rowIndex:8}];
 const before=clone(cur),sourceBefore=clone(s),r=shared.mountOnBoard(cur,s,options),p=r.project,plate=p.layout.subBoards[0],ids=new Map(r.mapping.map(m=>[m.toId,m.fromId]));
 assert.deepEqual(cur,before);assert.deepEqual(s,sourceBefore);assert.deepEqual(p.layout.board,before.layout.board);assert.deepEqual(plate.board,s.layout.board);
 assert.deepEqual(p.layout.instances[0],before.layout.instances[0]);assert.ok(!('boardId'in p.layout.instances[0]));
 assert.deepEqual(p.layout.instances.filter(i=>i.boardId===r.boardId).map(({id,boardId,...i})=>({id:ids.get(id),...i})),s.layout.instances);
 assert.deepEqual(r.offsetMm,{xMm:0,yMm:0});assert.equal(plate.xMm,0);assert.equal(plate.yMm,0);
 assert.deepEqual(p.metadata,before.metadata);assert.deepEqual(p.moduleQuantities,before.moduleQuantities);assert.deepEqual(p.ui.mountingSelection,before.ui.mountingSelection);
 assert.equal(quantities(p,'old'),9);assert.equal(quantities(p,r.insertedIds[0]),9);assert.deepEqual(p.optical[r.insertedIds[0]+'::optic'],s.optical['a::optic']);
 assert.equal(plate.board.thicknessMm,sourceBefore.layout.board.thicknessMm);assert.equal(plate.board.thread,sourceBefore.layout.board.thread);assert.equal(plate.board.holeDiameterMm,sourceBefore.layout.board.holeDiameterMm);
});
test('mount keeps different first-hole offsets and places first holes on the same carrier phase',()=>{
 const cur=current(),s=source();cur.layout.board={...cur.layout.board,widthMm:600,heightMm:450,pitchMm:25,edgeOffsetMm:20,mountingHoles:[]};s.layout.board.edgeOffsetMm=7.5;
 const before=clone(s),r=shared.mountOnBoard(cur,s,options),plate=r.project.layout.subBoards[0];assert.equal(plate.xMm,12.5);assert.equal(plate.yMm,12.5);
 assert.equal(plate.xMm+plate.board.edgeOffsetMm,cur.layout.board.edgeOffsetMm);assert.deepEqual(plate.board,before.layout.board);assert.deepEqual(s,before);
 const requested=shared.mountOnBoard(cur,s,{...options,platePosition:{xMm:108,yMm:77}}).project.layout.subBoards[0];assert.equal(requested.xMm,112.5);assert.equal(requested.yMm,75);
});
test('misaligned original mounting holes survive mount unchanged for explicit reselection',()=>{
 const cur=current(),s=source();cur.layout.board={...cur.layout.board,widthMm:600,heightMm:450,pitchMm:25,mountingHoles:[]};s.layout.board.mountingHoles=[{columnIndex:1,rowIndex:1},{columnIndex:25,rowIndex:1},{columnIndex:1,rowIndex:15},{columnIndex:25,rowIndex:15}];
 const original=clone(s.layout.board.mountingHoles),r=shared.mountOnBoard(cur,s,options),plate=r.project.layout.subBoards[0];assert.deepEqual(plate.board.mountingHoles,original);
 const parent=r.project.layout.board;assert.ok(plate.board.mountingHoles.every(h=>{const x=plate.xMm+plate.board.edgeOffsetMm+h.columnIndex*plate.board.pitchMm;return Math.abs((x-parent.edgeOffsetMm)/parent.pitchMm-Math.round((x-parent.edgeOffsetMm)/parent.pitchMm))>.01}));
 assert.deepEqual(s.layout.board.mountingHoles,original);
});
test('module draft coordinates are neither rejected nor independently snapped during mounting',()=>{
 const cur=current(),s=source();cur.layout.board.mountingHoles=[];s.layout.instances[0].xMm=1.3;s.layout.instances[0].yMm=-4.7;
 const before=clone(s),r=shared.mountOnBoard(cur,s,options),added=r.project.layout.instances.filter(i=>r.insertedIds.includes(i.id));
 assert.equal(added[0].xMm,1.3);assert.equal(added[0].yMm,-4.7);assert.deepEqual(added.map(({id,boardId,...i})=>i),s.layout.instances.map(({id,...i})=>i));assert.deepEqual(s,before);
});
test('existing carrier board ownership and existing small plates survive additional mounts',()=>{
 const first=shared.mountOnBoard(current(),source(),options),before=clone(first.project),second=shared.mountOnBoard(first.project,source(),options);
 assert.deepEqual(first.project,before);assert.deepEqual(second.project.layout.subBoards[0],before.layout.subBoards[0]);
 assert.deepEqual(second.project.layout.instances.slice(0,before.layout.instances.length),before.layout.instances);assert.equal(second.project.layout.subBoards.length,2);assert.notEqual(first.boardId,second.boardId);
 assert.ok(second.project.layout.instances.filter(i=>second.insertedIds.includes(i.id)).every(i=>i.boardId===second.boardId));assert.equal(second.project.layout.instances[0].boardId,undefined);
});
test('unsupported carrier and invalid placement reject atomically before remapping IDs',()=>{
 for(const bad of[{pitchMm:20},{holeType:'plain_through',thread:null,holeDiameterMm:6.4}]){const cur=current();cur.layout.board={...cur.layout.board,...bad,mountingHoles:[]};const before=clone(cur);let calls=0;reject(()=>shared.mountOnBoard(cur,source(),{...options,newId:()=>{calls++;return'id'}}),'unsupported_carrier');assert.deepEqual(cur,before);assert.equal(calls,0)}
 const cur=current(),before=clone(cur);for(const platePosition of[{xMm:NaN,yMm:0},{xMm:0},null,{xMm:0,yMm:0,zMm:0}])reject(()=>shared.mountOnBoard(cur,source(),{...options,platePosition}),'invalid_offset');assert.deepEqual(cur,before);
});
test('mounting retains the existing instance/accessory capacity guards and nesting rejection',()=>{
 const cur=current(),s=source();s.layout.instances=Array.from({length:500},(_,n)=>instance('i'+n,'mirror',62.5,62.5));s.extras=[];s.optical={};s.ui.selectedIds=[];reject(()=>shared.mountOnBoard(cur,s,options),'too_many_instances');
 const nested=shared.mountOnBoard(cur,source(),options).project;reject(()=>shared.mountOnBoard(cur,nested,options),'nested_carrier');
 const many=source();many.extras=Array.from({length:1000},(_,n)=>extra('per-kit-'+n,'mirror',1));let calls=0;reject(()=>shared.mountOnBoard(cur,many,{...options,newId:()=>{calls++;return'id'}}),'too_many_extras');assert.equal(calls,0);
});
test('a table source never becomes a fabricated module board and rejection is atomic',()=>{
 const s=source();s.layout.baseMode='table';const before=clone(s);
 for(const mode of[undefined,'breadboard','table']){const cur=current();if(mode)cur.layout.baseMode=mode;const saved=clone(cur);let calls=0;
  reject(()=>shared.mountOnBoard(cur,s,{...options,newId:()=>{calls++;return'forbidden'}}),'source_without_board');
  assert.deepEqual(cur,saved);assert.deepEqual(s,before);assert.equal(calls,0);
 }
});
test('a real small board can still mount to a table and table source parts can be merged without a board',()=>{
 const cur=current();cur.layout.baseMode='table';cur.layout.board={...cur.layout.board,widthMm:600,heightMm:450,pitchMm:25,mountingHoles:[]};
 const mounted=shared.mountOnBoard(cur,source(),options);assert.equal(mounted.project.layout.baseMode,'table');assert.equal(mounted.project.layout.subBoards.length,1);assert.ok(!('baseMode'in mounted.project.layout.subBoards[0]));
 const s=source();s.layout.baseMode='table';s.layout.board.pitchMm=20;
 const merged=shared.merge(cur,s,options);assert.equal(merged.project.layout.baseMode,'table');assert.equal(merged.insertedIds.length,3);assert.ok(!merged.project.layout.subBoards);
});
test('browser UMD exposes pure functions without a DOM and supports crypto UUIDs',()=>{
 let n=0;const browser={crypto:{randomUUID:()=>`uuid-${++n}`}};vm.createContext(browser);vm.runInContext(fs.readFileSync(__dirname+'/static/project-file.js','utf8'),browser);vm.runInContext(fs.readFileSync(__dirname+'/static/shared-project.js','utf8'),browser);
 browser.catalogJSON=JSON.stringify(catalog);browser.currentJSON=JSON.stringify(current());browser.sharedJSON=JSON.stringify(source());
 const result=vm.runInContext('ZZLabSharedProject.merge(JSON.parse(currentJSON),JSON.parse(sharedJSON),{catalog:JSON.parse(catalogJSON),now:"'+now+'"})',browser);
 assert.equal(result.insertedIds.length,3);assert.ok(result.insertedIds[0].startsWith('shared-instance-uuid-'));assert.ok(!('document'in browser));
});
console.log(`${passed} shared-project subset/merge checks passed.`);
