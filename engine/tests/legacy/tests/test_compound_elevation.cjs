const test=require('node:test'),assert=require('node:assert/strict');
const elevation=require('../static/elevation.js');
const catalog={components:[],kits:[{id:'source',components:[],layout:{opticalAxisHeightMm:113.1}},{id:'compound',components:[],layout:{opticalAxisHeightMm:113.06370626,opticalAssembly:{nodes:[]}}}]};
const layout={board:{widthMm:500,heightMm:500,thicknessMm:12.7},instances:[{id:'s',kitId:'source',xMm:100,yMm:100,rotationDeg:0},{id:'c',kitId:'compound',xMm:200,yMm:200,rotationDeg:0}]};
test('compound nominal height does not constrain the global scalar axis, actual 3D metadata is retained',()=>{
 const report=elevation.analyze(layout,catalog);assert.deepEqual(report.issues,[]);assert.equal(report.axisHeightReferenceMm,113.1);assert.equal(report.axisHeights[1].globalHeightComparable,false);
 assert.equal(report.axisHeights[1].opticalAxisHeightMm,113.06370626);assert.throws(()=>elevation.autoElevation(layout,catalog,'instance','c'),/三维/);
 const ordinary=structuredClone(catalog);delete ordinary.kits[1].layout.opticalAssembly;assert.equal(elevation.analyze(layout,ordinary).issues[0].code,'axis_height_mismatch');
 const invalid=structuredClone(layout);invalid.instances[1].elevationSupportCount=0;assert(elevation.analyze(invalid,catalog).issues.some(x=>x.code==='invalid_elevation'));
});
