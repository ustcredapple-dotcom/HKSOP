'use strict';
const assert=require('node:assert/strict'),E=require('../static/optical-engine.js'),R=require('../static/optical-renderer.js'),catalog=require('../catalog.json');
const kits=new Map(catalog.kits.map(k=>[k.id,k])),kit=kits.get('objective-final-assembly'),clone=x=>JSON.parse(JSON.stringify(x));
const board={widthMm:900,heightMm:700,pitchMm:25,edgeOffsetMm:12.5,thicknessMm:12.7};
const instance={id:'objective',kitId:kit.id,xMm:100,yMm:80,rotationDeg:90,elevationMm:5};
const source={id:'source',kitId:'laser-308nm',xMm:700,yMm:500,rotationDeg:0,optics:{...E.defaults('source'),source:{...E.defaults('source').source,enabled:true,wavelengthNm:532}}};
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
let count=0;function test(name,fn){fn();console.log('PASS '+name);count++;}
const scene=(i=instance,more={},purchases={},heights=[])=>R.sceneFor({board,instances:[clone(i),clone(source)],...more},kits,purchases,heights,E,catalog);
test('real assembly uses base anchor, composed rotation and mounting height',()=>{
 const e=scene({...instance,boardId:'small'},{subBoards:[{id:'small',xMm:300,yMm:100,rotationDeg:90,elevationMm:20,board:{...board,widthMm:300,heightMm:200,thicknessMm:25}}]}).elements[0];
 near(e.assemblyPlacement.xMm,220);near(e.assemblyPlacement.yMm,200);near(e.assemblyPlacement.zMm,50);near(e.assemblyPlacement.rotationDeg,180);
 near(e.axisHeightMm,kit.layout.opticalAxisHeightMm+50);assert.notEqual(e.assemblyPlacement.zMm,e.axisHeightMm);
 assert.equal(e.opticalAssembly.nodes.length,3);assert.equal(e.opticalAssembly.geometryEvidence,undefined);
});
test('original internal optics stay installed with no replacement purchase',()=>{
 const e=scene(instance,{}, {'objective::lower-mirror-optic':{inserted:false,model:'BDM2-UVA'},'objective::side-dichroic-optic':{inserted:false,model:'DM20-425SP'}}).elements[0];
 for(const id of ['lower-mirror','side-dichroic']){assert.equal(e.internalOptics[id].inserted,true);assert.equal(e.internalOptics[id].coatingFaceIndex,null);}
 assert.equal(e.internalOptics['lower-mirror'].mirror.model,'BDM2-UVA');assert.equal(e.internalOptics['side-dichroic'].dichroic.model,'DM20-425SP');
});
test('physical removal, chosen faces and per-instance coefficients survive scene creation',()=>{
 const i=clone(instance);i.internalOptics={'lower-mirror':{...kit.layout.opticalAssembly.internalElements[0].opticalDefaults,inserted:false,coatingFaceIndex:1}};
 const e=scene(i).elements[0];assert.equal(e.internalOptics['lower-mirror'].inserted,false);assert.equal(e.internalOptics['lower-mirror'].coatingFaceIndex,1);assert.equal(e.internalOptics['side-dichroic'].inserted,true);
});
test('official curves are clipped to active wavelengths without mutating catalog',()=>{
 const before=JSON.stringify(kit),e=scene().elements[0];for(const n of e.opticalAssembly.nodes.filter(n=>n.type!=='objective')){const samples=n[n.type+'Coating'].samples;assert.ok(samples.length>0);assert.ok(samples.every(s=>s.wavelengthNm===532));}
 assert.equal(JSON.stringify(kit),before);assert.ok(kit.layout.opticalAssembly.nodes[1].dichroicCoating.samples.length>256);
});
test('changing model cannot borrow the original coating data',()=>{
 const e=scene(instance,{}, {'objective::lower-mirror-optic':{model:'CUSTOM',inserted:true},'objective::side-dichroic-optic':{model:'OTHER',inserted:true}}).elements[0];
 assert.equal(e.internalOptics['lower-mirror'].mirror.model,'CUSTOM');assert.equal(e.opticalAssembly.nodes[0].mirrorCoating,undefined);assert.equal(e.opticalAssembly.nodes[1].dichroicCoating,undefined);
 assert.deepEqual(e.internalOptics['side-dichroic'].dichroic.samples,[]);
});
test('unresolved supports cannot create a fictitious 3-D mounting datum',()=>{assert.throws(()=>scene(instance,{}, {},[{instanceId:'objective',heightResolved:false,effectiveAxisHeightMm:null}]),/安装高度无法实现/)});
test('actual catalog geometry satisfies the three-dimensional engine contract',()=>{const session=E.createSession(scene());assert.equal(session.scene.elements[0].opticalAssembly.nodes.length,3);assert.ok(session.assemblyViews.objective);});
console.log(`${count} objective scene checks passed`);
