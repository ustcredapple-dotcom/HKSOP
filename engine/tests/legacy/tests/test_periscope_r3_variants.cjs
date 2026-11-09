'use strict';
// Synthetic receivers and explicitly ideal mirrors test geometry, never claim coating performance.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const E=require('../static/optical-engine.js'),A=require('../static/optical-assembly-engine.js'),R=require('../static/optical-renderer.js');
const catalog=JSON.parse(fs.readFileSync(process.env.PERISCOPE_R3_CATALOG||path.join(__dirname,'../catalog.json'),'utf8'));
const kits=new Map(catalog.kits.map(k=>[k.id,k]));
const periscopes=catalog.kits.filter(k=>k.mechanicalConfiguration&&['S3','L','M','308'].includes(k.mechanicalConfiguration.family));
assert.equal(periscopes.length,69);
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
const point=v=>({x:v[0],y:v[1],z:v[2]}),add=(a,b,s=1)=>a.map((x,i)=>x+s*b[i]),neg=a=>a.map(x=>-x);
const reflect=(d,n)=>{const dot=d.reduce((sum,x,i)=>sum+x*n[i],0);return d.map((x,i)=>x-2*dot*n[i]);};
let traces=0,blocks=0;
const original=JSON.stringify(catalog);
for(const kit of periscopes){
 const geometry=kit.layout.opticalAssembly,config=kit.mechanicalConfiguration;
 const upper=geometry.nodes.find(n=>n.id==='upper-mirror'),lower=geometry.nodes.find(n=>n.id==='lower-mirror');
 const u=upper.faces[0].centerMm,l=lower.faces[0].centerMm;
 near(u[0],l[0]);near(u[1],l[1]);near(u[2],config.inputHeightMm);near(l[2],config.outputHeightMm);
 assert.deepEqual(geometry.externalAxisHeightsMm,[config.inputHeightMm,config.outputHeightMm]);
 for(const n of [upper,lower]){near(Math.hypot(...n.faces[0].centerMm.map((x,i)=>x-n.faces[1].centerMm[i])),6);assert.equal(n.coatingFaceIndex,null);assert.equal(n.clearApertureConfirmed,false);}
 const incoming=reflect([0,0,-1],upper.faces[0].normal),outgoing=reflect([0,0,-1],lower.faces[0].normal);
 for(const rotationDeg of [0,90,180,270])for(const elevationMm of [0,12.5])for(const reverse of [false,true]){
  const d=reverse?neg(outgoing):incoming,endDirection=reverse?neg(incoming):outgoing;
  const start=add(reverse?l:u,d,-100),finish=add(reverse?u:l,endDirection,100);
  const instance={id:'periscope',kitId:kit.id,xMm:300,yMm:300,rotationDeg,elevationMm,internalOptics:{}};
  const ideal={elementType:'mirror',configured:true,inserted:true,coatingFaceIndex:0,clearApertureMm:18,mirror:{mode:'ideal',samples:[]}};
  for(const n of geometry.nodes)instance.internalOptics[n.id]=JSON.parse(JSON.stringify(ideal));
  const scene=R.sceneFor({board:{widthMm:700,heightMm:700,pitchMm:25,edgeOffsetMm:12.5,thicknessMm:12.5,holeType:'M6_through',mountingHoles:[]},instances:[instance]},kits,{},[],E,catalog);
  const place=scene.elements[0].assemblyPlacement,source=A.localToWorldPoint(point(start),place),target=A.localToWorldPoint(point(finish),place);
  const inAngle=Math.atan2(d[1],d[0])*180/Math.PI+rotationDeg,outAngle=Math.atan2(endDirection[1],endDirection[0])*180/Math.PI+rotationDeg;
  scene.elements.unshift({id:'source',center:{x:source.x,y:source.y},axisHeightMm:source.z,optics:{elementType:'source',source:{enabled:true,wavelengthNm:532,powerMw:10,beamDiameterMm:1,beamQualityM2:1,polarizationType:'linear',polarizationAngleDeg:23,directionAngleDeg:inAngle}}});
  scene.elements.push({id:'receiver',center:{x:target.x,y:target.y},axisHeightMm:target.z,optics:{elementType:'coupler',configured:true,inserted:true,surfaceAngleDeg:outAngle-90,source:{directionAngleDeg:outAngle+180}}});
  const before=JSON.stringify(scene),result=E.autoAdvance(E.createSession(scene),{maxEvents:128,maxMilliseconds:1000});
  assert.equal(result.blocked,false,`${kit.id}: ${JSON.stringify(result.issues)}`);assert.equal(result.done,true);assert.equal(JSON.stringify(scene),before);
  const coupled=result.session.completed.find(c=>c.reason==='coupled');assert.ok(coupled,kit.id);near(coupled.pathMm,200+u[2]-l[2]);near(coupled.powerMw,10);
  const output=result.session.segments.find(s=>s.hitInstanceId==='receiver');near(output.beam.axisHeightMm,(reverse?u[2]:l[2])+elevationMm);
  assert.deepEqual(result.events.filter(e=>e.internalId).map(e=>e.internalId),reverse?['lower-mirror','upper-mirror']:['upper-mirror','lower-mirror']);traces++;
  if(elevationMm===0){
   scene.elements.find(e=>e.id==='periscope').internalOptics={};
   const unknown=E.autoAdvance(E.createSession(scene),{maxEvents:128,maxMilliseconds:1000});
   assert.equal(unknown.blocked,true,kit.id);assert.equal(unknown.issues[0].code,'optics_unconfigured');blocks++;
  }
 }
}
assert.equal(JSON.stringify(catalog),original);
console.log(JSON.stringify({variants:periscopes.length,idealGeometryTraces:traces,unknownCoatingBlocks:blocks,catalogUnchanged:true}));
