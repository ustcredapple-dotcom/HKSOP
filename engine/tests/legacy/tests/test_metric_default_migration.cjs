'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const M=require('../static/metric-migration.js'),P=require('../static/project-file.js'),E=require('../static/elevation.js');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../catalog.json'),'utf8'));
const source={format:'zzlab-optics-project',version:1,catalogVersion:'old',metadata:{name:'metric test',notes:'preserved',createdAt:'2026-10-06T00:00:00.000Z',updatedAt:'2026-10-06T00:00:00.000Z'},layout:{baseMode:'table',board:{widthMm:900,heightMm:450,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7},instances:[{id:'i',kitId:'pbs-fixed',xMm:100,yMm:112.5,rotationDeg:90,elevationMm:25.4,universalPostSelection:{'custom-01':'custom-03'}}]},optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:['i'],view:null,mountingSelection:{rowParity:'any',columnParity:'any'}}};
const before=JSON.stringify(source),r=M.migrate(source,catalog);assert.equal(JSON.stringify(source),before);assert.equal(r.project.layout.instances[0].elevationMm,25);assert.equal(r.project.layout.board.thicknessMm,12.5);assert.equal(r.project.layout.instances[0].universalPostSelection['custom-post-metric-25mm-m1'],'custom-post-metric-37p5mm-m1');assert.equal(M.migrate(r.project,catalog).changed,false);
const reopened=P.parse(source,{catalog}).project;assert.equal(E.analyze(reopened.layout,catalog).axisHeights[0].effectiveAxisHeightMm,100);
for(const bad of [null,'x',[1]]){const p=structuredClone(source);p.requires=bad;assert.equal(M.migrate(p,catalog).changed,false);assert.throws(()=>P.parse(p,{catalog}));}
const forged=JSON.parse(before);forged.layout.instances[0].universalPostSelection=JSON.parse('{"__proto__":"custom-03"}');assert.throws(()=>P.parse(forged,{catalog}));assert.equal({}.polluted,undefined);
const conflicting=structuredClone(source);conflicting.layout.instances[0].universalPostSelection['custom-post-metric-25mm-m1']='custom-post-metric-25mm-m1';assert.equal(M.migrate(conflicting,catalog).changed,false);assert.throws(()=>P.parse(conflicting,{catalog}));
console.log('PASS metric equivalents, import, achieved height, idempotence, malformed input and prototype keys');
