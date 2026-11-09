'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const A=require('../static/optical-assembly-engine.js');
let count=0;
const near=(a,b,t=1e-8)=>assert.ok(Math.abs(a-b)<t,`${a} != ${b}`);
const same=(a,b,t=1e-8)=>{a=A.vec3(a);b=A.vec3(b);for(const k of ['x','y','z'])near(a[k],b[k],t)};
const test=(name,fn)=>{fn();count++;console.log('PASS '+name)};
const face=(x,r=10)=>({centerMm:[x,0,0],normal:[1,0,0],radiusMm:r});
const mirror=(more={})=>({id:'m',type:'mirror',centerMm:[10.5,0,0],normal:[1,0,0],radiusMm:10,faces:[face(10),face(11)],...more});
const assembly=(nodes=[mirror()])=>({bounds:{min:[0,-20,-20],max:[30,20,20]},nodes});

test('vec3 rejects incomplete/nonfinite inputs, copies arrays and normalizes true 3-D vectors',()=>{
  const v=[1,2,3];assert.deepEqual(A.vec3(v),{x:1,y:2,z:3});assert.deepEqual(v,[1,2,3]);
  near(A.norm3(A.normalize3([2,3,6])),1);same(A.cross3([1,0,0],[0,1,0]),[0,0,1]);
  for(const bad of [null,[],[1,2],[1,2,3,4],{x:1,y:2},[1,NaN,3],['1',2,3]])assert.throws(()=>A.vec3(bad));
  assert.throws(()=>A.normalize3([0,0,0]));assert.throws(()=>A.normalize3([1.7e308,1.7e308,1.7e308]));
});
test('assembly normalization validates identifiers, real planes, radius and bounds without mutation',()=>{
  const raw=assembly(),before=JSON.stringify(raw),n=A.normalizeAssembly(raw);same(n.nodes[0].faces[0].centerMm,[10,0,0]);assert.equal(n.nodes[0].geometryConfirmed,false);assert.equal(JSON.stringify(raw),before);
  for(const bad of [assembly([mirror(),mirror()]),assembly([mirror({type:'guessed'})]),assembly([mirror({normal:[0,0,0]})]),assembly([mirror({radiusMm:0})]),assembly([mirror({faces:[{centerMm:[1,2,3],normal:[0,0,0]}]})]),{...raw,bounds:{min:[0,0,0],max:[0,20,20]}}])assert.throws(()=>A.normalizeAssembly(bad));
  const explicit=A.normalizeAssembly(assembly([mirror({geometryConfirmed:true})]));assert.equal(explicit.nodes[0].geometryConfirmed,true);
});
test('unknown coating face selects the first actual face, independent of array ordering',()=>{
  const hit=A.rayHit([0,0,0],[4,0,0],mirror({faces:[face(11),face(10)]}));near(hit.distanceMm,10);same(hit.point,[10,0,0]);assert.equal(hit.faceIndex,1);assert.equal(hit.requiresFaceSelection,true);
  const back=A.rayHit([20,0,0],[-1,0,0],mirror());near(back.distanceMm,9);assert.equal(back.faceIndex,1);
});
test('explicit optical face intersects only that face, never a midplane or guessed nearer face',()=>{
  const hit=A.rayHit([0,0,0],[1,0,0],mirror(),1);near(hit.distanceMm,11);assert.equal(hit.requiresFaceSelection,false);
  assert.equal(A.rayHit([0,0,0],[1,0,0],mirror({faces:[] })),null);
  assert.throws(()=>A.rayHit([0,0,0],[1,0,0],mirror(),2));
});
test('circular face apertures use in-plane distance and skip parallel/behind/self hits',()=>{
  near(A.rayHit([0,3,4],[1,0,0],mirror(),0).offsetMm,5);
  assert.equal(A.rayHit([0,10.01,0],[1,0,0],mirror(),0),null);
  assert.equal(A.rayHit([0,0,0],[0,1,0],mirror(),0),null);
  assert.equal(A.rayHit([12,0,0],[1,0,0],mirror(),0),null);
  assert.equal(A.rayHit([10,0,0],[1,0,0],mirror(),0),null);
  assert.equal(A.rayHit([0,3,4],[1,0,0],mirror({faces:[face(10,4)]})),null);
});
test('slanted 3-D planes return physical distance and radial aperture offset',()=>{
  const n=mirror({faces:[{centerMm:[10,10,10],normal:[1,1,1],radiusMm:5}]});
  const hit=A.rayHit([0,0,0],[1,1,1],n,0);near(hit.distanceMm,Math.sqrt(300));near(hit.offsetMm,0);same(hit.point,[10,10,10]);
});
test('placement transforms preserve nonzero height, inverse geometry, and direction norm',()=>{
  const placement={xMm:100,yMm:200,zMm:37,rotationDeg:90};
  same(A.localToWorldPoint([4,7,9],placement),[93,204,46]);same(A.worldToLocalPoint([93,204,46],placement),[4,7,9]);
  same(A.localToWorldDirection([3,4,5],placement),[-4,3,5]);same(A.worldToLocalDirection([-4,3,5],placement),[3,4,5]);
  near(A.norm3(A.localToWorldDirection([3,4,5],placement)),Math.sqrt(50));
});
test('reflection is 3-D, independent of normal sign, and reverses correctly',()=>{
  const s=Math.SQRT1_2,n=[-s,s,0],d=[1,0,0],r=A.reflect3(d,n);same(r,[0,1,0]);same(A.reflect3(d,A.scale3(n,-1)),r);same(A.reflect3(r,n),d);
  same(A.reflect3(r,[0,s,s]),[0,0,-1]);
});
test('incidence frame is orthonormal, right-handed, hemisphere-consistent and measured from the normal',()=>{
  const d=A.normalize3([1,1,2]),n=A.normalize3([1,0,1]),basis=A.incidenceBasis(d,n,[0,0,1]);
  near(A.dot3(basis.s,d),0);near(A.dot3(basis.p,d),0);near(A.dot3(basis.s,basis.p),0);same(A.cross3(basis.p,basis.s),d);assert.ok(A.dot3(basis.s,[0,0,1])>=0);
  near(basis.angleDeg,Math.acos(Math.abs(A.dot3(d,n)))*180/Math.PI);same(A.incidenceBasis(d,A.scale3(n,-1),[0,0,1]).s,basis.s);
  near(A.incidenceBasis([1,0,0],[1,1,0],[0,0,1]).angleDeg,45);
});
test('normal incidence uses the transverse reference, with a finite deterministic fallback',()=>{
  const aligned=A.incidenceBasis([1,0,0],[1,0,0],[0,0,1]);same(aligned.s,[0,0,1]);same(aligned.p,[0,1,0]);near(aligned.angleDeg,0);
  const fallback=A.incidenceBasis([0,0,1],[0,0,-1],[0,0,1]);near(A.dot3(fallback.s,[0,0,1]),0);near(A.norm3(fallback.s),1);near(fallback.angleDeg,0);
});
test('polarization reference rotation changes Q/U with the correct sign and never flips circular handedness',()=>{
  const linear={s0:1,s1:1,s2:0,s3:0},v=A.rotateStokes(linear,[1,0,0],[0,0,1],[0,1,1]);near(v.s1,0);near(v.s2,1);near(v.s3,0);
  const circular={s0:1,s1:0,s2:0,s3:.7};near(A.rotateStokes(circular,[1,0,0],[0,0,1],[0,1,0]).s3,.7);
  const backward=A.rotateStokes(v,[1,0,0],[0,1,1],[0,0,1]);near(backward.s1,1);near(backward.s2,0);assert.deepEqual(linear,{s0:1,s1:1,s2:0,s3:0});
  assert.throws(()=>A.rotateStokes(linear,[1,0,0],[1,0,0],[0,0,1]));
});
test('Stokes basis rotation agrees with independently projected complex electric fields in arbitrary 3-D frames',()=>{
  let seed=971;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/2**32);
  const mul=(a,k)=>[a[0]*k,a[1]*k],add=(a,b)=>[a[0]+b[0],a[1]+b[1]],abs2=a=>a[0]**2+a[1]**2;
  const stokes=(p,s)=>{const power=abs2(p)+abs2(s);return{s0:1,s1:(abs2(p)-abs2(s))/power,s2:2*(p[0]*s[0]+p[1]*s[1])/power,s3:-2*(p[1]*s[0]-p[0]*s[1])/power}};
  for(let i=0;i<40;i++){
    const d=A.normalize3([rand()-.5,rand()-.5,rand()-.5]),from=A.incidenceBasis(d,[rand(),rand(),rand()],[0,0,1]),to=A.incidenceBasis(d,[rand(),rand(),rand()],[0,0,1]);
    const ep=[rand()-.5,rand()-.5],es=[rand()-.5,rand()-.5],field={};for(const k of ['x','y','z'])field[k]=add(mul(ep,from.p[k]),mul(es,from.s[k]));
    const project=axis=>['x','y','z'].reduce((v,k)=>add(v,mul(field[k],axis[k])),[0,0]);
    const expected=stokes(project(to.p),project(to.s)),actual=A.rotateStokes(stokes(ep,es),d,from.s,to.s);
    for(const k of ['s0','s1','s2','s3'])near(actual[k],expected[k]);
  }
});
test('box exit uses all three axes and returns the true positive physical distance',()=>{
  const b={min:[-2,-3,-4],max:[2,3,4]};near(A.boxExit([0,0,0],[0,0,2],b).distanceMm,4);same(A.boxExit([0,0,0],[1,1,1],b).point,[2,2,2]);
  assert.equal(A.boxExit([3,0,0],[0,1,0],b),null);assert.equal(A.boxExit([2,0,0],[1,0,0],b),null);
  near(A.boxExit([-5,0,0],[1,0,0],b).distanceMm,7);assert.equal(A.boxExit([-5,0,0],[-1,0,0],b),null);
});
test('CAD objective fixture remains a three-axis path with real center-to-center length',()=>{
  const first={centerMm:[20.6,-.6,113.06370626],normal:[Math.SQRT1_2,0,Math.SQRT1_2],radiusMm:25.25};
  const second={centerMm:[70.5995205,-.6,113.06370626],normal:[Math.SQRT1_2,-Math.SQRT1_2,0],radiusMm:25.3};
  const h1=A.rayHit([20.6,-.6,197.56370626],[0,0,-1],mirror({faces:[first]}),0);near(h1.distanceMm,84.5);
  const d1=A.reflect3([0,0,-1],first.normal);same(d1,[1,0,0]);
  const h2=A.rayHit(h1.point,d1,mirror({faces:[second]}),0);near(h2.distanceMm,49.9995205);same(A.reflect3(d1,second.normal),[0,1,0]);
  assert.deepEqual(A.sidePoint(h1.point),{x:20.6,y:113.06370626});
});
test('browser UMD export works without the main optical engine',()=>{
  const sandbox={};vm.runInNewContext(fs.readFileSync(require.resolve('../static/optical-assembly-engine.js'),'utf8'),sandbox);assert.equal(typeof sandbox.ZZLabOpticalAssemblyEngine.rayHit,'function');assert.equal(typeof sandbox.ZZLabOpticalEngine,'undefined');
});
console.log(`${count} independent 3-D assembly geometry and polarization basis checks passed`);
