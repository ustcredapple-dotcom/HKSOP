'use strict';
const assert=require('node:assert/strict'),E=require('../static/optical-engine.js');
let count=0;const near=(a,b,t=1e-8)=>assert.ok(Math.abs(a-b)<t,`${a} != ${b}`),test=(name,fn)=>{fn();count++;console.log('PASS '+name)};
const RAD=Math.PI/180,complex=(re,im=0)=>({re,im}),add=(a,b)=>complex(a.re+b.re,a.im+b.im),mul=(a,b)=>complex(a.re*b.re-a.im*b.im,a.im*b.re+a.re*b.im),scale=(a,s)=>complex(a.re*s,a.im*s),abs2=a=>a.re*a.re+a.im*a.im;
// Independent Jones reference, not the engine's Stokes/retarder implementation.
const jonesStokes=([p,s])=>{const power=abs2(p)+abs2(s),cross=mul(p,complex(s.re,-s.im));return{power,s0:1,s1:(abs2(p)-abs2(s))/power,s2:2*cross.re/power,s3:-2*cross.im/power}};
const plateJones=(j,angle,retardance)=>{const a=angle*RAD,c=Math.cos(a),s=Math.sin(a),phase=complex(Math.cos(retardance*RAD),Math.sin(retardance*RAD)),fast=add(scale(j[0],c),scale(j[1],s)),slow=mul(add(scale(j[0],-s),scale(j[1],c)),phase);return[add(scale(fast,c),scale(slow,-s)),add(scale(fast,s),scale(slow,c))]};
const mirrorJones=(j,r)=>[mul(j[0],complex(Math.sqrt(r.reflectanceP)*Math.cos(r.phaseDifferenceDeg*RAD),Math.sqrt(r.reflectanceP)*Math.sin(r.phaseDifferenceDeg*RAD))),scale(j[1],Math.sqrt(r.reflectanceS))];
const compare=(a,b,t=1e-8)=>{for(const k of ['s1','s2','s3'])near(a[k],b[k],t)},beam=j=>({...E.createBeam({wavelengthNm:532,powerMw:10}),stokes:jonesStokes(j)});
const sample=(more={})=>({wavelengthNm:532,incidenceAngleDeg:45,reflectanceP:.8,reflectanceS:.9,phaseDifferenceDeg:150,...more});
const data=(samples=[sample()])=>({mode:'data',model:'TEST-MIRROR',samples});
const source=(id='source',y=0)=>({id,center:{x:0,y},rotationDeg:0,optics:E.normalizeOptics({elementType:'source',inserted:true,source:{enabled:true,directionAngleDeg:0,wavelengthNm:532,powerMw:10,polarizationAngleDeg:45}})});
const mirror=(more={})=>({id:'mirror',center:{x:100,y:0},rotationDeg:0,optics:E.normalizeOptics({elementType:'mirror',inserted:true,surfaceAngleDeg:45,...more})});
const scene=elements=>({bounds:{xMin:-100,yMin:-100,xMax:500,yMax:500},elements});

test('pure P/S retain polarization, and their powers follow intensity reflectance (not amplitude)',()=>{
  for(const [j,expected] of [[[complex(1),complex(0)],8],[[complex(0),complex(1)],9]]){const b=beam(j),out=E.applyMirror(b,sample());near(out.powerMw,expected);compare(out.stokes,jonesStokes(j));assert.equal(b.powerMw,10);}
});
test('complex phase acts once: +90 produces right circular, unequal loss produces ellipse, 180 flips U/V',()=>{
  const linear=[complex(Math.SQRT1_2),complex(Math.SQRT1_2)],circular=E.applyMirror(beam(linear),{reflectanceP:1,reflectanceS:1,phaseDifferenceDeg:90});near(circular.stokes.s3,-1);near(circular.stokes.s2,0);
  const input=[complex(.6),complex(.3,Math.sqrt(.55))],b=beam(input),r=sample(),out=E.applyMirror(b,r),expected=jonesStokes(mirrorJones(input,r));near(out.powerMw,10*expected.power);compare(out.stokes,expected);assert.ok(Math.abs(out.stokes.s3)>0);
  const flipped=E.applyMirror(b,{reflectanceP:1,reflectanceS:1,phaseDifferenceDeg:180});near(flipped.stokes.s1,b.stokes.s1);near(flipped.stokes.s2,-b.stokes.s2);near(flipped.stokes.s3,-b.stokes.s3);
  const zeroPhase=E.applyMirror(b,{reflectanceP:1,reflectanceS:1,phaseDifferenceDeg:0});compare(zeroPhase.stokes,b.stokes);
});
test('two mirrors compose Jones amplitudes and power; partial polarization is transformed as a coherency matrix',()=>{
  const input=[complex(.6,.2),complex(Math.sqrt(.6))],first=sample(),second=sample({reflectanceP:.7,reflectanceS:.6,phaseDifferenceDeg:-23}),out=E.applyMirror(E.applyMirror(beam(input),first),second),reference=jonesStokes(mirrorJones(mirrorJones(input,first),second));compare(out.stokes,reference);near(out.powerMw,10*reference.power);
  const mixed={...E.createBeam({powerMw:10}),stokes:{s0:1,s1:0,s2:0,s3:0}},polarized=E.applyMirror(mixed,{reflectanceP:1,reflectanceS:0,phaseDifferenceDeg:32});near(polarized.powerMw,5);near(polarized.stokes.s1,1);
  const absorbed=E.applyMirror(mixed,{reflectanceP:0,reflectanceS:0,phaseDifferenceDeg:180});near(absorbed.powerMw,0);assert.ok(Object.values(absorbed.stokes).every(Number.isFinite));
});
test('AOI is measured from normal for rotations and either face, and only exact spectral/angular points apply',()=>{
  near(E.incidenceAngleDeg({x:1,y:0},90),0);near(E.incidenceAngleDeg({x:1,y:0},45),45);near(E.incidenceAngleDeg({x:-1,y:0},45),45);near(E.incidenceAngleDeg({x:0,y:1},180),0);
  assert.equal(E.resolveMirrorResponse(data(),532,45).ok,true);assert.equal(E.resolveMirrorResponse(data(),533,45).ok,false);assert.equal(E.resolveMirrorResponse(data(),532,45.001).ok,false);
  assert.equal(E.resolveMirrorResponse(data([sample({phaseDifferenceDeg:null})]),532,45).code,'mirror_data_missing');
  assert.equal(E.resolveMirrorResponse(undefined,532,45).legacy,true);assert.equal(E.resolveMirrorResponse({mode:'ideal',samples:[]},532,45).legacy,false);
  assert.throws(()=>E.applyMirror(beam([complex(1),complex(0)]),{reflectanceP:1,reflectanceS:1}));assert.throws(()=>E.normalizeMirror(data([sample(),sample()])));
  for(const bad of [sample({wavelengthNm:null}),sample({incidenceAngleDeg:null}),sample({reflectanceP:undefined}),sample({reflectanceP:1.1})])assert.throws(()=>E.normalizeMirror(data([bad])));
});
test('catalog curves never fabricate phase or bind to another model; a complete manual point takes priority',()=>{
  const official={model:'TEST-MIRROR',samples:[sample({phaseDifferenceDeg:null})]},pending=E.resolveMirrorResponse(data([]),532,45,official);assert.equal(pending.ok,false);assert.equal(pending.origin,'catalog');assert.equal(pending.response.reflectanceP,.8);assert.equal(pending.response.phaseDifferenceDeg,null);
  assert.equal(E.resolveMirrorResponse(data([]),532,45,{...official,model:'OTHER'}).code,'mirror_sample_mismatch');
  const complete=E.resolveMirrorResponse(data([sample({phaseDifferenceDeg:178})]),532,45,official);assert.equal(complete.ok,true);assert.equal(complete.origin,'manual');assert.equal(complete.response.phaseDifferenceDeg,178);
  const invalid=E.resolveMirrorResponse(data([]),532,45,{...official,samples:[sample({reflectanceS:1.00003,phaseDifferenceDeg:null})]});assert.equal(invalid.ok,false);assert.equal(invalid.code,'mirror_catalog_invalid');assert.equal(invalid.response,undefined,'invalid curve point is not silently clamped into valid data');
});
test('manual and automatic tracing pause at incomplete mirrors while independent paths continue; legacy has visible ideal warning',()=>{
  const m=mirror({mirror:data([sample({phaseDifferenceDeg:null})])}),start=E.createSession(scene([source(),m,source('independent',300)])),auto=E.autoAdvance(start);assert.equal(auto.blocked,true);assert.equal(auto.issues[0].code,'mirror_data_missing');assert.ok(auto.session.completed.some(c=>c.sourceId==='independent'));
  const clicked=E.advancePending(start,start.pending[0].id);assert.equal(clicked.pending.length,1);assert.equal(clicked.segments.length,start.segments.length);
  const fixed=E.advancePending(start,start.pending[0].id,{mirror:data()});assert.equal(fixed.pending.length,0);const reflected=fixed.segments.find(s=>Math.abs(s.from.x-100)<1e-8);near(reflected.beam.powerMw,8.5);near(reflected.direction.y,1);
  const legacy=E.autoAdvance(E.createSession(scene([source(),mirror()])));assert.equal(legacy.done,true);assert.ok(legacy.session.warnings.some(w=>w.code==='mirror_ideal_approximation'));
});
test('known amplitudes determine pure P/S and incoherent mixtures without inventing an unknown phase',()=>{
  const m=mirror({mirror:data([sample({phaseDifferenceDeg:null})])}),original=JSON.stringify(m.optics.mirror);
  for(const s1 of [-1,-.3,0,.4,1]){
    const b={...E.createBeam({wavelengthNm:532,powerMw:10}),stokes:{s0:1,s1,s2:0,s3:0}},response=E.mirrorResponseFor(m,b,{x:1,y:0});assert.equal(response.ok,true);assert.equal(response.phaseIndependent,true);assert.equal(response.response.phaseDifferenceDeg,null);
    const out=E.applyMirror(b,response.response),p=.8*(1+s1)/2,s=.9*(1-s1)/2;near(out.powerMw,10*(p+s));near(out.stokes.s1,(p-s)/(p+s));near(out.stokes.s2,0);near(out.stokes.s3,0);
    for(const phaseDifferenceDeg of [-133,0,37,180])compare(out.stokes,E.applyMirror(b,{...response.response,phaseDifferenceDeg}).stokes);
  }
  assert.equal(JSON.stringify(m.optics.mirror),original);
  const pSource=source();pSource.optics.source.polarizationAngleDeg=0;let trace=E.autoAdvance(E.createSession(scene([pSource,m])));assert.equal(trace.done,true);assert.equal(trace.issues.length,0);assert.ok(trace.session.warnings.some(w=>w.code==='mirror_phase_not_required'));assert.ok(trace.session.warnings.every(w=>w.code!=='mirror_ideal_approximation'));
  for(const polarizationType of ['linear','elliptical','circular-left']){const b=E.createBeam({wavelengthNm:532,polarizationType,polarizationAngleDeg:45,ellipticityDeg:17});assert.equal(E.mirrorResponseFor(m,b,{x:1,y:0}).ok,false);assert.throws(()=>E.applyMirror(b,sample({phaseDifferenceDeg:null})));}
});
test('zero reflection in either polarization also removes phase dependence, including total absorption',()=>{
  const b=E.createBeam({wavelengthNm:532,powerMw:10,polarizationType:'elliptical',polarizationAngleDeg:27,ellipticityDeg:16});
  for(const [reflectanceP,reflectanceS] of [[0,.7],[.8,0],[0,0]]){const m=mirror({mirror:data([sample({reflectanceP,reflectanceS,phaseDifferenceDeg:null})])}),response=E.mirrorResponseFor(m,b,{x:1,y:0});assert.equal(response.ok,true);assert.equal(response.phaseIndependent,true);assert.equal(response.response.phaseDifferenceDeg,null);const out=E.applyMirror(b,response.response),known=E.applyMirror(b,{reflectanceP,reflectanceS,phaseDifferenceDeg:123});near(out.powerMw,known.powerMw);compare(out.stokes,known.stokes);}
  const official={model:' TEST-MIRROR ',samples:[sample({phaseDifferenceDeg:null})]};assert.equal(E.resolveMirrorResponse({...data([]),model:'test-mirror'},532,45,official).origin,'catalog');
});
test('retarders agree with independent Jones fast/slow axes in forward and reverse order',()=>{
  const input=[complex(.6,.2),complex(Math.sqrt(.6))],plates=[{inserted:true,fastAxisDeg:23,retardanceDeg:91,designWavelengthNm:532},{inserted:true,fastAxisDeg:67,retardanceDeg:179,designWavelengthNm:532}];
  for(const reverse of [false,true]){let j=input;for(const p of reverse?[...plates].reverse():plates)j=plateJones(j,reverse?-p.fastAxisDeg:p.fastAxisDeg,p.retardanceDeg);compare(E.applyWaveplateSequence(jonesStokes(input),plates,reverse),jonesStokes(j));}
  const element={rotationDeg:0,optics:E.normalizeOptics({elementType:'waveplate',surfaceAngleDeg:90})};assert.equal(E.waveplateReverse(element,{x:1,y:0}),false);assert.equal(E.waveplateReverse(element,{x:-1,y:0}),true);
});
test('QWP ideal-mirror double pass equals Jones round trip and rotates linear input to its orthogonal state',()=>{
  const input=[complex(1),complex(0)],plate={inserted:true,fastAxisDeg:45,retardanceDeg:90,designWavelengthNm:532},reflection={reflectanceP:1,reflectanceS:1,phaseDifferenceDeg:180};
  const forward=E.applyWaveplateSequence(jonesStokes(input),[plate]),back=E.applyWaveplateSequence(E.applyMirror({...beam(input),stokes:forward},reflection).stokes,[plate],true),j=plateJones(mirrorJones(plateJones(input,45,90),reflection),-45,90);compare(back,jonesStokes(j));near(back.s1,-1);
});
const asTarget=s=>({polarizationType:'elliptical',polarizationAngleDeg:Math.atan2(s.s2,s.s1)/(2*RAD),ellipticityDeg:Math.asin(Math.max(-1,Math.min(1,s.s3)))/(2*RAD)});
const plates=(retardances=[180,90])=>retardances.map(retardanceDeg=>({inserted:true,fastAxisDeg:0,retardanceDeg,designWavelengthNm:532}));
test('solver reaches linear, either circular and elliptical targets, verifies returned settings and mutates nothing',()=>{
  const incoming=E.stokesFromSource({polarizationAngleDeg:13}),p=plates(),before=JSON.stringify(p),targets=[{polarizationType:'linear',polarizationAngleDeg:37},{polarizationType:'circular-left'},{polarizationType:'circular-right'},{polarizationType:'elliptical',polarizationAngleDeg:-23,ellipticityDeg:17}];
  for(const target of targets){const solved=E.solveTwoWaveplates({incomingStokes:incoming,plates:p,wavelengthNm:532,target});assert.equal(solved.ok,true,JSON.stringify(solved));assert.ok(solved.error<=1e-6);assert.equal(solved.anglesDeg.length,2);compare(E.applyWaveplateSequence(incoming,p.map((v,i)=>({...v,fastAxisDeg:solved.anglesDeg[i]}))),solved.targetStokes,1e-6);}
  assert.equal(JSON.stringify(p),before);
});
test('reverse-pass solver retains physical slot order and works at measured nonideal retardances',()=>{
  const input=[complex(.6,.2),complex(Math.sqrt(.6))],incoming=jonesStokes(input),p=plates([87,173]),actual=[31,78];let j=input;for(const index of [1,0])j=plateJones(j,-actual[index],p[index].retardanceDeg);const target=asTarget(jonesStokes(j)),solved=E.solveTwoWaveplates({incomingStokes:incoming,plates:p,wavelengthNm:532,reverse:true,target});assert.equal(solved.ok,true,JSON.stringify(solved));
  let verified=input;for(const index of [1,0])verified=plateJones(verified,-solved.anglesDeg[index],p[index].retardanceDeg);compare(jonesStokes(verified),solved.targetStokes,1e-6);
});
test('unreachable targets, missing actual data and wavelength mismatch cannot produce applicable angles',()=>{
  const options={incomingStokes:E.stokesFromSource({}),plates:plates([180,180]),wavelengthNm:532,target:{polarizationType:'circular-left'}},unreachable=E.solveTwoWaveplates(options);assert.equal(unreachable.ok,false);assert.equal(unreachable.reason,'unreachable');assert.equal(unreachable.anglesDeg,undefined);
  for(const extra of [{wavelengthNm:780},{plates:plates().map(p=>({...p,inserted:false}))},{plates:[{inserted:true},{inserted:true}]},{incomingStokes:{s0:1,s1:0,s2:0,s3:0}}]){const failed=E.solveTwoWaveplates({...options,...extra});assert.equal(failed.ok,false);assert.equal(failed.anglesDeg,undefined);}
});
test('solver returned angles independently satisfy varied reachable nonideal Jones targets in both directions',()=>{
  let seed=731;const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/2**32);
  for(let n=0;n<32;n++){
    const theta=random()*Math.PI/2,phase=random()*Math.PI*2,input=[complex(Math.cos(theta)),complex(Math.sin(theta)*Math.cos(phase),Math.sin(theta)*Math.sin(phase))],p=plates([75+random()*30,165+random()*30]),known=[random()*180,random()*180],reverse=n%2===1;
    let j=input;for(const i of reverse?[1,0]:[0,1])j=plateJones(j,reverse?-known[i]:known[i],p[i].retardanceDeg);
    const solved=E.solveTwoWaveplates({incomingStokes:jonesStokes(input),plates:p,wavelengthNm:532,reverse,target:asTarget(jonesStokes(j))});assert.equal(solved.ok,true,`${n}: ${JSON.stringify(solved)}`);
    let check=input;for(const i of reverse?[1,0]:[0,1])check=plateJones(check,reverse?-solved.anglesDeg[i]:solved.anglesDeg[i],p[i].retardanceDeg);compare(jonesStokes(check),jonesStokes(j),1e-6);
  }
});
console.log(`${count} mirror Jones/Stokes and double-waveplate solver checks passed`);
