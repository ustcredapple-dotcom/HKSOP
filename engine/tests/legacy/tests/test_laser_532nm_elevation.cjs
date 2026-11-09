'use strict';
const assert=require('node:assert/strict'),E=require('../static/elevation.js'),real=require('../catalog.json');
// Deliberately synthetic geometry isolates support accounting from the catalog drawing.
const geometry={opticalAxisHeightMm:95.7,opticalPortsMm:[{wavelengthNm:532}],minimumAlignedMountingHoles:2,
  mountingHoleOffsetsMm:[{xMm:0,yMm:0},{xMm:50,yMm:0},{xMm:0,yMm:310},{xMm:50,yMm:310},{xMm:375,yMm:125},{xMm:375,yMm:175}]};
const catalog={...real,kits:[{id:'laser-532nm',name:'532 nm laser',components:[],layout:geometry},
  {id:'ordinary',name:'Ordinary mount',components:[],layout:{...geometry,opticalPortsMm:[],opticalAxisHeightMm:152.4}}]};
const layout=pitch=>({board:{widthMm:1000,heightMm:1000,pitchMm:pitch,edgeOffsetMm:0,thicknessMm:12.7},
  instances:[{id:'green',kitId:'laser-532nm',xMm:400,yMm:400,rotationDeg:0,elevationMm:55.8}]});
let checks=0;function test(name,fn){fn();checks++;console.log('PASS '+name)}
test('source supports match the registered mounting holes and material quantities',()=>{
  for(const [pitch,count] of [[50,2],[25,4],[5,6]])for(const rotationDeg of [0,90,180,270]){
    const l=layout(pitch);l.instances[0].rotationDeg=rotationDeg;const result=E.analyze(l,catalog);
    assert.equal(result.axisHeights[0].effectiveAxisHeightMm,151.5);
    assert.equal(result.axisHeights[0].elevationSupportCount,count);
    assert.equal(result.elevationAccessories[0].supportCount,count);
    assert.deepEqual(result.elevationAccessories[0].materials.map(m=>[m.componentId,m.quantity]),[['lbtek-op1-55b6',count],['elevation-shim-0p8',count]]);
  }
});
test('minimum and explicit support overrides remain consistent',()=>{
  const l=layout(25);l.instances[0].xMm+=1;assert.equal(E.analyze(l,catalog).axisHeights[0].elevationSupportCount,2);
  l.instances[0].elevationSupportCount=3;const r=E.analyze(l,catalog);assert.equal(r.axisHeights[0].elevationSupportCount,3);assert.ok(r.elevationAccessories[0].materials.every(m=>m.quantity===3));
});
test('ordinary optics do not gain source supports and source automatic elevation is exact',()=>{
  const l=layout(25);l.instances.push({id:'optic',kitId:'ordinary',xMm:700,yMm:700,rotationDeg:0});
  assert.equal(E.analyze(l,catalog).axisHeights[1].elevationSupportCount,1);
  assert.equal(E.autoElevation(l,catalog,'instance','green'),56.7);
  l.instances[0].elevationMm=56.7;assert.equal(E.analyze(l,catalog).issues.length,0);
});
console.log(`${checks} mounted source elevation frontend checks passed`);
