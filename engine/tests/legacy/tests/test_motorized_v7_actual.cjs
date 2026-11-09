'use strict';
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const E=require('../static/optical-engine.js'),R=require('../static/optical-renderer.js'),L=require('../static/optical-interaction-language.js');
const root=path.resolve(__dirname,'..');
const catalog=JSON.parse(fs.readFileSync(process.env.ZZLAB_TEST_CATALOG || path.join(root,'catalog.json'),'utf8'));
const kits=catalog.kits.filter(k=>k.id.startsWith('motor-v7-'));
const near=(a,b,t=1e-7)=>assert.ok(Math.abs(a-b)<=t,`${a} != ${b}`);
let checks=0;const rows=[];
for(const kit of kits){
 const i={id:'mirror-instance',kitId:kit.id,xMm:200,yMm:200,rotationDeg:0};
 const defaults=R.configFor(i,kit,{},E,catalog);
 const expected=kit.id.includes('1in')?23.5:48.8;
 near(defaults.clearApertureMm,expected);assert.equal(defaults.configured,false);assert.equal(defaults.inserted,false);assert.equal(defaults.mirror.mode,'data');
 assert.equal(R.catalogSimulationIssue(kit),null);L.normalize(kit.layout.opticalInteraction,E);
 const source={id:'beam',center:{x:200,y:300},axisHeightMm:62.5,optics:E.normalizeOptics({elementType:'source',configured:true,inserted:true,source:{enabled:true,directionAngleDeg:-90,powerMw:10,wavelengthNm:532,beamDiameterMm:2,polarizationAngleDeg:0}})};
 function scene(instance,purchases={}){const s=R.sceneFor({board:{widthMm:500,heightMm:500},instances:[instance]},new Map([[kit.id,kit]]),purchases,[],E,catalog);s.elements.unshift(source);return s;}
 let s=E.createSession(scene(i));assert.equal(s.pending.length,1);assert.ok(E.pendingIssue(s,s.pending[0]));assert.equal(E.autoAdvance(s).blocked,true);
 const selected={[`${i.id}::mirror`]:{inserted:true,model:'Uncharacterized mirror'}};
 s=E.createSession(scene(i,selected));assert.equal(E.autoAdvance(s).blocked,true);
 const explicit={...i,optics:{...defaults,inserted:true,configured:true,mirror:{mode:'ideal',model:'verification fixture only',samples:[]}}};
 s=E.autoAdvance(E.createSession(scene(explicit))).session;assert.equal(s.pending.length,0);assert.ok(s.warnings.some(w=>w.code==='mirror_ideal_approximation'));
 const direction=s.segments[1].direction;
 if(kit.mechanicalConfiguration.orientationDeg===0){near(direction.x,0);near(direction.y,1);}else{near(direction.x,-1);near(direction.y,0);}
 // Actual nominal plane transforms with a placed instance; its axis remains 62.5 mm.
 for(const angle of [0,90,180,270]){
  const placed={...explicit,rotationDeg:angle},sc=scene(placed),e=sc.elements[1];near(e.axisHeightMm,62.5);near(e.center.x,200);near(e.center.y,200);near(e.rotationDeg,angle);
  const a=angle*Math.PI/180,c=Math.cos(a),sn=Math.sin(a);
  sc.elements[0]={...source,center:{x:200-100*sn,y:200+100*c},optics:E.normalizeOptics({...source.optics,source:{...source.optics.source,directionAngleDeg:-90+angle}})};
  const rotated=E.autoAdvance(E.createSession(sc)).session;assert.equal(rotated.pending.length,0);
  near(rotated.segments[1].direction.x,direction.x*c-direction.y*sn);near(rotated.segments[1].direction.y,direction.x*sn+direction.y*c);
 }
 const empty={...i,optics:{...defaults,inserted:false,configured:true}};
 s=E.autoAdvance(E.createSession(scene(empty))).session;assert.equal(s.pending.length,0);near(s.segments[1].direction.x,0);near(s.segments[1].direction.y,-1);
 rows.push({kitId:kit.id,defaultApertureMm:expected,unknownOpticBlocked:true,uncharacterizedMirrorBlocked:true,explicitIdealFixtureReflectionPassed:true,explicitEmptyPassed:true,instanceRotationsPassed:4});checks+=7;
}
assert.equal(kits.length,4);
console.log(JSON.stringify({status:'passed',checks,kits:rows,scope:'Actual catalog static geometries; explicit ideal fixture only tests ray direction and never becomes a shipped mirror default. No DOM or electrical control test.'},null,2));
