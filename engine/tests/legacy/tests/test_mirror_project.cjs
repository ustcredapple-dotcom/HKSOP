'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const codec=require('../static/project-file.js'),shared=require('../static/shared-project.js');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../catalog.json'),'utf8'));
const sample={wavelengthNm:532,incidenceAngleDeg:45,reflectanceP:.96,reflectanceS:.99,phaseDifferenceDeg:173.5};
const optics={elementType:'mirror',inserted:true,configured:true,mirror:{mode:'data',model:'MEASURED-532',samples:[sample]}};
const make=()=>codec.create({metadata:{name:'镜面系数工程'},catalogVersion:catalog.version,layout:{
  board:{widthMm:300,heightMm:225,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]},
  instances:[{id:'mirror',kitId:'fixed-1-90',xMm:75,yMm:75,rotationDeg:0,optics:structuredClone(optics)}]},
  optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],view:null}},{catalog});
test('mirror sample round-trip and shared module copy retain independent bound data',()=>{
  const project=make(),restored=codec.parse(JSON.stringify(project),{catalog}).project;
  assert.deepEqual(restored.layout.instances[0].optics,optics);
  const module=shared.subset(restored,['mirror'],{catalog});
  module.layout.instances[0].optics.mirror.samples[0].reflectanceP=.2;
  assert.equal(restored.layout.instances[0].optics.mirror.samples[0].reflectanceP,.96);
  assert.deepEqual(restored.optical,{},'simulation coefficients never fabricate a purchase');
});
test('unknown reflection phase remains null in portable projects',()=>{
  const project=make();project.layout.instances[0].optics.mirror.samples[0].phaseDifferenceDeg=null;
  assert.equal(codec.parse(JSON.stringify(project),{catalog}).project.layout.instances[0].optics.mirror.samples[0].phaseDifferenceDeg,null);
});
test('project rejects unbounded, ambiguous, malformed or forged-source coefficients',()=>{
  const invalid=[null,{},[],{mode:'data'},{mode:'fake',samples:[]},{mode:'data',samples:[],sourceUrl:'https://invented'},
    {mode:'data',samples:[],model:'x'.repeat(161)},{mode:'data',samples:Array.from({length:257},()=>sample)},
    {mode:'data',samples:[sample,sample]}];
  for(const [key,values]of Object.entries({wavelengthNm:[null,0,1e6+1],incidenceAngleDeg:[null,-1,91],reflectanceP:[-.1,1.1],reflectanceS:[-.1,1.1],phaseDifferenceDeg:[-36001,36001]})){
    for(const value of [...values,true,'0.5',NaN,Infinity])invalid.push({mode:'data',samples:[{...sample,[key]:value}]});
  }
  for(const mirror of invalid){const project=make();project.layout.instances[0].optics.mirror=mirror;assert.throws(()=>codec.parse(project,{catalog}));}
});
