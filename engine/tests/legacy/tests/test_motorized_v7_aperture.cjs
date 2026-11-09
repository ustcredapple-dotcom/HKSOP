'use strict';
const assert=require('node:assert/strict'),E=require('../static/optical-engine.js'),R=require('../static/optical-renderer.js');
const make=(diameter,clear)=>({id:'synthetic-aperture',category:'motor',components:[],opticalSlots:[{id:'mirror',type:'mirror',quantity:1,diameterMm:diameter}],layout:{opticalType:'mirror',opticalClearApertureMm:clear,opticalSurfaceAngleDeg:0,opticalDefaults:{elementType:'mirror',inserted:false,configured:false,mirror:{mode:'data',model:'',samples:[]}}}});
for(const [diameter,clear] of [[25.4,23.5],[50.8,48.8]]){
  const kit=make(diameter,clear),before=JSON.stringify(kit),instance={id:'i',kitId:kit.id};
  const fresh=R.configFor(instance,kit,{},E,{});
  assert.equal(fresh.clearApertureMm,clear);assert.equal(fresh.inserted,false);assert.equal(fresh.configured,false);assert.equal(fresh.mirror.mode,'data');
  const selected=R.configFor(instance,kit,{'i::mirror':{inserted:true,model:'USER-SELECTED'}},E,{});
  assert.equal(selected.clearApertureMm,clear);assert.equal(selected.inserted,true);assert.equal(kit.opticalSlots[0].diameterMm,diameter);
  const saved=R.configFor({...instance,optics:{elementType:'mirror',inserted:true,configured:true,clearApertureMm:10,mirror:{mode:'data',samples:[]}}},kit,{},E,{});
  assert.equal(saved.clearApertureMm,10,'explicit saved instance settings must survive catalog initialization');assert.equal(JSON.stringify(kit),before);
}
for(const invalid of [null,0,-1,NaN,Infinity,'23.5',true,10001])assert.throws(()=>R.configFor({id:'i'},make(25.4,invalid),{},E,{}));
const old=make(25.4,23.5);delete old.layout.opticalClearApertureMm;assert.equal(R.configFor({id:'i'},old,{},E,{}).clearApertureMm,25.4);
console.log('PASS: physical aperture separated from optical outside diameter; unknown coating, saved settings and absent-field legacy behavior preserved.');
