'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const codec=require('../static/project-file.js'),shared=require('../static/shared-project.js');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../catalog.json'),'utf8'));
let seq=0;const options={catalog,now:'2026-09-28T00:00:00.000Z',newId:()=>`height-${++seq}`};
const board=(width=900,height=900,pitch=25)=>({widthMm:width,heightMm:height,pitchMm:pitch,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]});
const make=layout=>codec.create({metadata:{name:'垫高工程'},catalogVersion:catalog.version,layout,optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],view:null,mountingSelection:{rowParity:'any',columnParity:'any'}}},options);
const project=make({board:board(),subBoards:[{id:'plate',name:'已垫高的小板',board:board(200,150,12.5),xMm:0,yMm:0,rotationDeg:0,elevationMm:58.8,elevationSupportCount:4}],instances:[{id:'optic',kitId:'waveplate',boardId:'plate',xMm:75,yMm:75,rotationDeg:0,elevationMm:0.2,elevationSupportCount:2}]});
const decoded=codec.parse(JSON.stringify(project),options).project;
assert.deepEqual(decoded.layout,project.layout);
const moduleProject=shared.extractBoard(decoded,'plate',options);
assert.deepEqual(moduleProject.metadata.moduleElevation,{elevationMm:58.8,elevationSupportCount:4});
assert.equal(moduleProject.layout.instances[0].elevationMm,0.2);
const portable=codec.parse(JSON.stringify(moduleProject),options).project;
const target=make({board:board(),instances:[]});
const mounted=shared.mountOnBoard(target,portable,options).project;
assert.equal(mounted.layout.subBoards[0].elevationMm,58.8);
assert.equal(mounted.layout.subBoards[0].elevationSupportCount,4);
assert.equal(mounted.layout.instances[0].elevationMm,0.2);
assert.equal(mounted.layout.instances[0].elevationSupportCount,2);
for(const value of [-1,0.01,1000.1,'2',null]){
 const bad=structuredClone(project);bad.layout.instances[0].elevationMm=value;
 assert.throws(()=>codec.parse(bad,options),`reject invalid elevation ${value}`);
}
for(const value of [0,1.5,129,'4',null]){
 const bad=structuredClone(project);bad.layout.subBoards[0].elevationSupportCount=value;
 assert.throws(()=>codec.parse(bad,options),`reject invalid support count ${value}`);
}
const forged=structuredClone(portable);forged.metadata.moduleElevation.materials=[{model:'forged'}];assert.throws(()=>codec.parse(forged,options),/不支持/);
console.log('PASS elevation project round-trip, portable module supports and strict fields');
