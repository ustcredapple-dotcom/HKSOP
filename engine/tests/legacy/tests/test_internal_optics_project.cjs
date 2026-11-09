'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const codec=require('../static/project-file.js'),shared=require('../static/shared-project.js');
const catalog={version:'internal-test',kits:[{id:'assembly',name:'整装',opticalSlots:[],layout:{widthMm:35,heightMm:35,anchorXMm:17.5,anchorYMm:17.5,
  mountingHoleOffsetsMm:[{xMm:0,yMm:0}],opticalAssembly:{internalElements:[{id:'lower-mirror',type:'mirror'}]}}}]};
const internal=()=>({'lower-mirror':{elementType:'mirror',inserted:true,configured:true,source:{enabled:false},mirror:{mode:'ideal',samples:[]}}});
const project=()=>codec.create({metadata:{name:'整装内部光路'},catalogVersion:catalog.version,layout:{board:{widthMm:300,heightMm:225},instances:[{id:'a',kitId:'assembly',xMm:100,yMm:75,rotationDeg:0,internalOptics:internal()}]},optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],view:null}},{catalog});
test('internal optics retain catalog IDs through project round-trip and independent shared copy',()=>{
  const source=project(),restored=codec.parse(JSON.stringify(source),{catalog}).project;
  assert.deepEqual(restored.layout.instances[0].internalOptics,internal());
  const module=shared.subset(restored,['a'],{catalog});module.layout.instances[0].internalOptics['lower-mirror'].inserted=false;
  assert.equal(restored.layout.instances[0].internalOptics['lower-mirror'].inserted,true);
  assert.deepEqual(restored.optical,{});assert.deepEqual(restored.extras,[]);
});
test('unknown internal IDs, conflicting types, source injection and recursive settings fail atomically',()=>{
  for(const value of [null,[],{'unknown':internal()['lower-mirror']},{'lower-mirror':{elementType:'pbs',inserted:true}},
    {'lower-mirror':{elementType:'mirror',inserted:true,source:{enabled:true}}},
    {'lower-mirror':{elementType:'mirror',inserted:true,internalOptics:{}}},
    {'lower-mirror':{elementType:'mirror',inserted:true,center:{x:0,y:0}}}]){
    const p=project();p.layout.instances[0].internalOptics=value;assert.throws(()=>codec.parse(p,{catalog}));
  }
  const ordinary=structuredClone(catalog);delete ordinary.kits[0].layout.opticalAssembly;
  assert.throws(()=>codec.parse(project(),{catalog:ordinary}));
});

test('dichroic exact coefficients and coating face persist only on catalog internal surfaces',()=>{
  const c=structuredClone(catalog);c.kits[0].layout.opticalAssembly.internalElements.push({id:'side-dichroic',type:'dichroic'});
  const config={elementType:'dichroic',inserted:true,coatingFaceIndex:null,dichroic:{mode:'data',model:'DM20-425SP',samples:[{wavelengthNm:532,incidenceAngleDeg:45,reflectanceP:.99,reflectanceS:null,transmittanceP:.005,transmittanceS:null,reflectionPhaseDifferenceDeg:null,transmissionPhaseDifferenceDeg:null}]}};
  const p=project();p.layout.instances[0].internalOptics['side-dichroic']=config;
  assert.deepEqual(codec.parse(JSON.stringify(p),{catalog:c}).project.layout.instances[0].internalOptics['side-dichroic'],config);
  for(const face of [true,false,-1,2,'0',.1]){const bad=structuredClone(p);bad.layout.instances[0].internalOptics['side-dichroic'].coatingFaceIndex=face;assert.throws(()=>codec.parse(bad,{catalog:c}));}
  for(const change of [{transmittanceP:.1},{wavelengthNm:null},{reflectanceP:1.1}]){const bad=structuredClone(p);Object.assign(bad.layout.instances[0].internalOptics['side-dichroic'].dichroic.samples[0],change);assert.throws(()=>codec.parse(bad,{catalog:c}));}
  const bad=structuredClone(p);bad.layout.instances[0].optics=config;assert.throws(()=>codec.parse(bad,{catalog:c}));
});
