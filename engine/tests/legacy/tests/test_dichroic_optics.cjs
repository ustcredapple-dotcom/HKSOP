'use strict';
// Independent optical response checks. No DOM, catalog fixture or assembly
// tracer is needed; the complex Jones reference is separate from the engine.
const assert=require('node:assert/strict'),E=require('../static/optical-engine.js');
let count=0;
const near=(a,b,t=1e-8)=>assert.ok(Number.isFinite(a)&&Math.abs(a-b)<t,`${a} != ${b}`);
const test=(name,fn)=>{fn();count++;console.log('PASS '+name)};
const compareStokes=(a,b,t=1e-8)=>{for(const k of ['s1','s2','s3'])near(a[k],b[k],t)};
const point=(more={})=>({wavelengthNm:532,incidenceAngleDeg:45,reflectanceP:.3,reflectanceS:.55,
  transmittanceP:.6,transmittanceS:.25,reflectionPhaseDifferenceDeg:73,transmissionPhaseDifferenceDeg:-28,...more});
const data=(samples=[point()],model='TEST-DICHROIC')=>({mode:'data',model,samples});
const c=(re,im=0)=>({re,im}),abs2=a=>a.re*a.re+a.im*a.im;
const multiply=(a,b)=>c(a.re*b.re-a.im*b.im,a.re*b.im+a.im*b.re);
const scalar=(a,k)=>c(a.re*k,a.im*k);
const jonesStokes=([p,s])=>{
  const power=abs2(p)+abs2(s),cross=multiply(p,c(s.re,-s.im));
  return power>0?{power,s0:1,s1:(abs2(p)-abs2(s))/power,s2:2*cross.re/power,s3:-2*cross.im/power}:{power:0,s0:1,s1:0,s2:0,s3:0};
};
const responseJones=(j,coefficientP,coefficientS,phaseDifferenceDeg)=>{
  const phase=phaseDifferenceDeg*Math.PI/180;
  return [multiply(j[0],c(Math.sqrt(coefficientP)*Math.cos(phase),Math.sqrt(coefficientP)*Math.sin(phase))),scalar(j[1],Math.sqrt(coefficientS))];
};
const beam=(j=[c(1),c(0)],powerMw=12)=>({...E.createBeam({wavelengthNm:532,powerMw}),stokes:jonesStokes(j)});
const resolved=(sample,incident=beam())=>E.dichroicResponseAt(data([sample]),incident,45);
const unknownPhases=(more={})=>point({reflectionPhaseDifferenceDeg:null,transmissionPhaseDifferenceDeg:null,...more});

test('dichroic exports provide explicit data normalization, resolution and two physical output branches',()=>{
  for(const name of ['normalizeDichroic','dichroicResponseAt','applyDichroic'])assert.equal(typeof E[name],'function',name);
  const clean=E.normalizeDichroic(data());assert.deepEqual(clean.samples[0],point());assert.equal(clean.mode,'data');
});
test('nullable measurements survive normalization without inventing phase or optical coefficients',()=>{
  const sample=unknownPhases({reflectanceS:null,transmittanceS:null}),raw=data([sample]),before=JSON.stringify(raw),clean=E.normalizeDichroic(raw);
  assert.deepEqual(clean.samples[0],sample);assert.equal(JSON.stringify(raw),before);
  assert.deepEqual(E.normalizeDichroic(data([])).samples,[]);
  assert.throws(()=>E.normalizeDichroic({...data(),mode:'ideal'}),'A dichroic is not an implicit ideal PBS');
});
test('sample validation rejects missing keys, invalid wavelengths/angles, duplicate points and non-passive sums',()=>{
  for(const bad of [point({wavelengthNm:null}),point({incidenceAngleDeg:NaN}),point({incidenceAngleDeg:91}),point({reflectanceP:-.01}),point({transmittanceS:1.01}),point({reflectionPhaseDifferenceDeg:undefined}),point({transmissionPhaseDifferenceDeg:Infinity}),point({reflectanceP:.7,transmittanceP:.4}),point({reflectanceS:.8,transmittanceS:.3})])assert.throws(()=>E.normalizeDichroic(data([bad])),JSON.stringify(bad));
  const missing=point();delete missing.transmittanceP;assert.throws(()=>E.normalizeDichroic(data([missing])));
  assert.throws(()=>E.normalizeDichroic(data([point(),point()])));
  assert.doesNotThrow(()=>E.normalizeDichroic(data([point({reflectanceP:.7,transmittanceP:.3,reflectanceS:.8,transmittanceS:.2})])));
});
test('spectral and incidence measurements match only the exact operating point, without interpolation',()=>{
  assert.equal(E.dichroicResponseAt(data(),beam(),45).ok,true);
  assert.equal(E.dichroicResponseAt(data(),{...beam(),wavelengthNm:532.01},45).ok,false);
  assert.equal(E.dichroicResponseAt(data(),beam(),45.001).ok,false);
  const bracket=data([point({wavelengthNm:500}),point({wavelengthNm:600})]);assert.equal(E.dichroicResponseAt(bracket,beam(),45).ok,false);
  assert.equal(E.dichroicResponseAt(data([]),beam(),45).ok,false);
});
test('manual/catalog coefficients bind to their model; matching manual measurements have priority',()=>{
  const catalog={model:'TEST-DICHROIC',samples:[point({reflectanceP:.2,transmittanceP:.5})]},match=E.dichroicResponseAt(data([]),beam(),45,catalog);
  assert.equal(match.ok,true);assert.equal(match.origin,'catalog');near(match.response.reflectanceP,.2);
  assert.equal(E.dichroicResponseAt(data([]),beam(),45,{...catalog,model:'OTHER'}).ok,false);
  const manual=E.dichroicResponseAt(data(),beam(),45,catalog);assert.equal(manual.ok,true);assert.equal(manual.origin,'manual');near(manual.response.reflectanceP,.3);
  const trimmed=E.dichroicResponseAt(data([],' test-dichroic '),beam(),45,catalog);assert.equal(trimmed.ok,true);
});
test('invalid official coefficients are rejected instead of silently clamped into passive data',()=>{
  for(const sample of [point({reflectanceP:1.00003,transmittanceP:0}),point({reflectanceP:.7,transmittanceP:.5})]){
    const response=E.dichroicResponseAt(data([]),beam(),45,{model:'TEST-DICHROIC',samples:[sample]});assert.equal(response.ok,false);
  }
});
test('pure P and S powers use intensity R/T coefficients and account for absorption',()=>{
  for(const [j,r,t] of [[[c(1),c(0)],.3,.6],[[c(0),c(1)],.55,.25]]){
    const input=beam(j),original=JSON.stringify(input),out=E.applyDichroic(input,point());
    near(out.reflected.powerMw,12*r);near(out.transmitted.powerMw,12*t);near(out.absorbedPowerMw,12*(1-r-t));
    compareStokes(out.reflected.stokes,input.stokes);compareStokes(out.transmitted.stokes,input.stokes);
    near(out.reflected.powerMw+out.transmitted.powerMw+out.absorbedPowerMw,input.powerMw);assert.equal(JSON.stringify(input),original);
  }
});
test('two separate Jones phase differences apply exactly once, including reflected handedness',()=>{
  const input=beam([c(Math.SQRT1_2),c(Math.SQRT1_2)]),sample=point({reflectanceP:.5,reflectanceS:.5,transmittanceP:.5,transmittanceS:.5,reflectionPhaseDifferenceDeg:90,transmissionPhaseDifferenceDeg:-90});
  const out=E.applyDichroic(input,sample);near(out.reflected.stokes.s3,-1);near(out.transmitted.stokes.s3,1);near(out.reflected.stokes.s2,0);near(out.transmitted.stokes.s2,0);near(out.absorbedPowerMw,0);
  const zero=E.applyDichroic(input,{...sample,reflectionPhaseDifferenceDeg:0,transmissionPhaseDifferenceDeg:0});near(zero.reflected.stokes.s2,1);near(zero.transmitted.stokes.s2,1);
});
test('arbitrary elliptical input and unequal amplitudes agree with independent complex Jones calculations',()=>{
  const j=[c(.6,.2),c(Math.sqrt(.6))],input=beam(j,23),sample=point(),out=E.applyDichroic(input,sample);
  const referenceR=jonesStokes(responseJones(j,sample.reflectanceP,sample.reflectanceS,sample.reflectionPhaseDifferenceDeg));
  const referenceT=jonesStokes(responseJones(j,sample.transmittanceP,sample.transmittanceS,sample.transmissionPhaseDifferenceDeg));
  near(out.reflected.powerMw,23*referenceR.power);near(out.transmitted.powerMw,23*referenceT.power);
  compareStokes(out.reflected.stokes,referenceR);compareStokes(out.transmitted.stokes,referenceT);
  near(out.absorbedPowerMw,23*(1-referenceR.power-referenceT.power));
});
test('partially polarized incoherent P/S mixtures conserve power under diattenuation',()=>{
  for(const s1 of [-1,-.4,0,.2,1]){
    const input={...beam(),stokes:{s0:1,s1,s2:0,s3:0}},sample=point(),out=E.applyDichroic(input,sample);
    for(const [branch,a,b] of [[out.reflected,sample.reflectanceP,sample.reflectanceS],[out.transmitted,sample.transmittanceP,sample.transmittanceS]]){
      const p=a*(1+s1)/2,s=b*(1-s1)/2;near(branch.powerMw,12*(p+s));near(branch.stokes.s1,(p-s)/(p+s));near(branch.stokes.s2,0);near(branch.stokes.s3,0);
    }
    near(out.reflected.powerMw+out.transmitted.powerMw+out.absorbedPowerMw,12);
  }
});
test('missing phase remains null but pure P/S and incoherent mixtures can still be computed',()=>{
  const sample=unknownPhases(),before=JSON.stringify(sample);
  for(const s1 of [-1,-.35,0,.5,1]){
    const input={...beam(),stokes:{s0:1,s1,s2:0,s3:0}},response=resolved(sample,input);assert.equal(response.ok,true);
    assert.equal(response.response.reflectionPhaseDifferenceDeg,null);assert.equal(response.response.transmissionPhaseDifferenceDeg,null);
    const out=E.applyDichroic(input,response.response),known=E.applyDichroic(input,point());compareStokes(out.reflected.stokes,known.reflected.stokes);compareStokes(out.transmitted.stokes,known.transmitted.stokes);
    near(out.reflected.powerMw,known.reflected.powerMw);near(out.transmitted.powerMw,known.transmitted.powerMw);
  }
  assert.equal(JSON.stringify(sample),before);
});
test('coherent input pauses when either needed branch phase is unknown, and direct application cannot bypass it',()=>{
  const coherent=beam([c(Math.SQRT1_2),c(Math.SQRT1_2)]);
  for(const sample of [unknownPhases(),point({reflectionPhaseDifferenceDeg:null}),point({transmissionPhaseDifferenceDeg:null})]){
    assert.equal(resolved(sample,coherent).ok,false);assert.throws(()=>E.applyDichroic(coherent,sample));
  }
});
test('a branch with one zero amplitude is phase independent; an active coherent other branch still needs its phase',()=>{
  const coherent=beam([c(Math.SQRT1_2),c(Math.SQRT1_2)]);
  for(const sample of [unknownPhases({reflectanceP:0,reflectanceS:.7,transmittanceP:.8,transmittanceS:0}),unknownPhases({reflectanceP:.6,reflectanceS:0,transmittanceP:0,transmittanceS:.9})]){
    const response=resolved(sample,coherent);assert.equal(response.ok,true);const out=E.applyDichroic(coherent,response.response);near(out.reflected.powerMw+out.transmitted.powerMw+out.absorbedPowerMw,12);
  }
  const onlyOneSafe=unknownPhases({reflectanceP:0,reflectanceS:.2,transmittanceP:.8,transmittanceS:.7});assert.equal(resolved(onlyOneSafe,coherent).ok,false);
});
test('zero-power output branches remain finite, total absorption and lossless splitting both conserve power',()=>{
  const coherent=beam([c(.6,.2),c(Math.sqrt(.6))]);
  for(const sample of [unknownPhases({reflectanceP:0,reflectanceS:0,transmittanceP:0,transmittanceS:0}),point({reflectanceP:0,reflectanceS:0,transmittanceP:1,transmittanceS:1}),point({reflectanceP:1,reflectanceS:1,transmittanceP:0,transmittanceS:0})]){
    const out=E.applyDichroic(coherent,sample);assert.ok(Object.values(out.reflected.stokes).every(Number.isFinite));assert.ok(Object.values(out.transmitted.stokes).every(Number.isFinite));near(out.reflected.powerMw+out.transmitted.powerMw+out.absorbedPowerMw,12);assert.ok(out.absorbedPowerMw>=-1e-9);
  }
  assert.throws(()=>E.applyDichroic(coherent,point({reflectanceP:.8,transmittanceP:.4})));
});
test('varying passive R/T and signed phases reproduce Jones outputs without power gain',()=>{
  let seed=492;const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/2**32);
  for(let i=0;i<32;i++){
    const angle=random()*Math.PI/2,phase=random()*Math.PI*2,j=[c(Math.cos(angle)),c(Math.sin(angle)*Math.cos(phase),Math.sin(angle)*Math.sin(phase))];
    const rp=random(),rs=random(),sample=point({reflectanceP:rp,reflectanceS:rs,transmittanceP:random()*(1-rp),transmittanceS:random()*(1-rs),reflectionPhaseDifferenceDeg:720*(random()-.5),transmissionPhaseDifferenceDeg:720*(random()-.5)}),input=beam(j,17),out=E.applyDichroic(input,sample);
    const rr=jonesStokes(responseJones(j,sample.reflectanceP,sample.reflectanceS,sample.reflectionPhaseDifferenceDeg)),tt=jonesStokes(responseJones(j,sample.transmittanceP,sample.transmittanceS,sample.transmissionPhaseDifferenceDeg));
    compareStokes(out.reflected.stokes,rr);compareStokes(out.transmitted.stokes,tt);near(out.reflected.powerMw,17*rr.power);near(out.transmitted.powerMw,17*tt.power);near(out.absorbedPowerMw,17*(1-rr.power-tt.power));assert.ok(out.absorbedPowerMw>=-1e-9);
  }
});
console.log(`${count} dichroic Jones, wavelength, data provenance and energy-conservation checks passed`);
