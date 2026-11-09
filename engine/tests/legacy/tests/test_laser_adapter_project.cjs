'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const codec=require('../static/project-file.js'),shared=require('../static/shared-project.js');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../catalog.json'),'utf8'));
let seq=0;const options={catalog,now:'2026-09-28T00:00:00.000Z',newId:()=>`adapter-${++seq}`};
const board={widthMm:1200,heightMm:700,pitchMm:25,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]};
const make=instances=>codec.create({metadata:{name:'激光器垫板工程'},catalogVersion:catalog.version,layout:{board,instances},optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],view:null,mountingSelection:{rowParity:'any',columnParity:'any'}}},options);
const config={enabled:true,thicknessMm:17.4,mountingOriginXMm:83.5,mountingOriginYMm:-125,mountingDatumConfirmed:false};
const source=make([{id:'laser',kitId:'laser-308nm',xMm:395.5,yMm:245.5,rotationDeg:0,laserAdapter:config}]);
assert.deepEqual(codec.parse(JSON.stringify(source),options).project.layout.instances[0].laserAdapter,config);
const merged=shared.merge(make([]),source,options).project;
assert.deepEqual(merged.layout.instances[0].laserAdapter,config);
assert.equal((merged.layout.instances[0].yMm+67-12.5)%25,0);
const mounted=shared.mountOnBoard(make([]),source,options).project;
assert.deepEqual(mounted.layout.instances[0].laserAdapter,config);
const portable=shared.extractBoard(mounted,mounted.layout.subBoards[0].id,options);
assert.deepEqual(portable.layout.instances[0].laserAdapter,config);
for(const delta of [null,{enabled:false},{thicknessMm:8.4},{thicknessMm:50.1},{thicknessMm:17.41},{mountingOriginXMm:'83.5'},{mountingOriginYMm:501},{mountingDatumConfirmed:'true'},{generatedHoles:[]}]){
 const bad=structuredClone(source);bad.layout.instances[0].laserAdapter=delta===null?null:{...config,...delta};
 assert.throws(()=>codec.parse(bad,options));
}
const wrong=structuredClone(source);wrong.layout.instances[0].kitId='waveplate';assert.throws(()=>codec.parse(wrong,options));
console.log('PASS adapter project import/export, component merge, board-module preservation and strict calibration fields');
