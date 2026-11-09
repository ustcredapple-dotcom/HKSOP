'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.argv[2],catalog=JSON.parse(fs.readFileSync(path.join(root,'library/catalog.json'),'utf8'));
const projects=JSON.parse(fs.readFileSync(path.join(root,'projects/project-index.json'),'utf8'));
const codec=require(path.join(root,'runtime/releases/editor-web-current/static/project-file.js'));
const vm=require('node:vm'),context=vm.createContext({console});
vm.runInContext('window=globalThis',context);
for(const name of ['registered-boards.js','layout.js','fixed-board-optics.js']){
 vm.runInContext(fs.readFileSync(path.join(root,'runtime/releases/editor-web-current/static',name),'utf8'),context,{filename:name});
}
const boardValidator=Object.create(context.window.BreadboardEditor.prototype);boardValidator.catalog=catalog;
let projectCount=0;const projectResults=[];
for(const p of projects){
 const dir=path.join(root,p.path),record=JSON.parse(fs.readFileSync(path.join(dir,'project.json'),'utf8'));
 for(const item of [record.currentEngineering,...record.modules].filter(Boolean)){
  const raw=fs.readFileSync(path.join(dir,item.path),'utf8'),d=JSON.parse(raw);
  const missing=d.layout.instances.filter(i=>!catalog.kits.some(k=>k.id===i.kitId));assert.deepEqual(missing,[]);
  const mismatches=[d.layout.board,...(d.layout.subBoards||[]).map(x=>x.board)].filter(b=>b.registeredBoardId).flatMap(b=>{
   const current=catalog.registeredBoards.find(r=>r.id===b.registeredBoardId);
   return current?.revision===b.registeredBoardRevision?[]:[{id:b.registeredBoardId,projectRevision:b.registeredBoardRevision,currentRevision:current?.revision??null}];
  });
  let result;
  try{result=codec.parse(raw,{catalog,validateBoard:b=>boardValidator.validBoard(b)});}
  catch(error){
   // Audit delivered JSON without changing it or relaxing the current codec.
   // A domain rejection is a compatibility result, not a successful import.
   if(error.name!=='ProjectFileError'||typeof error.code!=='string')throw error;
   projectResults.push({project:p.name,file:item.path,compatible:false,blockedByCurrentCodec:true,code:error.code,message:error.message,path:error.path,boardMismatches:mismatches});projectCount++;continue;
  }
  assert.deepEqual(mismatches,[]);
  assert.equal(result.project.layout.instances.length,d.layout.instances.length);
  assert.equal((result.project.layout.subBoards||[]).length,d.layout.subBoards?.length||0);
  if(d.opticalRendering!==undefined)assert.deepEqual(result.project.opticalRendering,d.opticalRendering);
  projectResults.push({project:p.name,file:item.path,compatible:true,instances:d.layout.instances.length,warnings:result.warnings});projectCount++;
 }
}
const clone=x=>JSON.parse(JSON.stringify(x)),near=(a,b,t=1e-7)=>assert.ok(Math.abs(a-b)<t,`${a} != ${b}`);
const kit=catalog.kits.find(k=>k.id==='cage-f100-qwp780-r1');assert.ok(kit);
const v4Results=[];
for(const profile of ['web','editor']){
 const dir=path.join(root,'runtime/releases',profile+'-web-current/static');
 const A=require(path.join(dir,'optical-assembly-engine.js')),E=require(path.join(dir,'optical-engine.js'));
 assert.equal(A.normalizeAssembly(kit.layout.opticalAssembly).version,4);
 const bad=clone(kit.layout.opticalAssembly);bad.emissionNodeId='lens';assert.throws(()=>A.normalizeAssembly(bad));
 const missing=clone(kit.layout.opticalAssembly);missing.internalElements=missing.internalElements.filter(x=>x.id!=='lens');assert.throws(()=>A.normalizeAssembly(missing));
 function scene(reverse=false){return{bounds:{xMin:-100,yMin:-150,xMax:100,yMax:150},elements:[
  {id:'source',center:{x:0,y:reverse?100:-100},axisHeightMm:62.5,optics:{elementType:'source',source:{enabled:true,directionAngleDeg:reverse?-90:90,wavelengthNm:780,powerMw:1,beamDiameterMm:1,beamQualityM2:1,polarizationType:'linear',polarizationAngleDeg:0,wavefrontRadiusMm:null}}},
  {id:'cage',center:{x:0,y:0},axisHeightMm:62.5,optics:{elementType:'empty',configured:true,inserted:true},assemblyPlacement:{xMm:0,yMm:0,zMm:0,rotationDeg:0},opticalAssembly:clone(kit.layout.opticalAssembly),internalOptics:{lens:{elementType:'lens',configured:true,inserted:true,focalLengthMm:100,clearApertureMm:22.86},qwp:{elementType:'waveplate',configured:true,inserted:true,clearApertureMm:21.5,waveplates:[{fastAxisDeg:45,retardanceDeg:90,designWavelengthNm:780}]}}}
 ]};}
 let s=E.createSession(scene());assert.equal(s.pending[0].internalId,'lens');assert.equal(E.pendingIssue(s,s.pending[0]),null);
 const q=E.propagateQ(E.lensQ(s.pending[0].beam.q,100),30);s=E.advancePending(s,s.pending[0].id);
 assert.equal(s.pending[0].internalId,'qwp');near(s.pending[0].beam.q.re,q.re);near(s.pending[0].beam.q.im,q.im);
 assert.equal(E.pendingIssue(s,s.pending[0]),null);s=E.advancePending(s,s.pending[0].id);assert.equal(s.pending.length,0);
 let back=E.createSession(scene(true));assert.equal(back.pending[0].internalId,'qwp');back=E.advancePending(back,back.pending[0].id);assert.equal(back.pending[0].internalId,'lens');assert.equal(E.pendingIssue(back,back.pending[0]),null);back=E.advancePending(back,back.pending[0].id);assert.equal(back.pending.length,0);
 const noFocal=scene();delete noFocal.elements[1].internalOptics.lens.focalLengthMm;const paused=E.createSession(noFocal);assert.equal(E.pendingIssue(paused,paused.pending[0]).code,'lens_focal_length_missing');
 const emits=scene();emits.elements[1].optics.source={enabled:true};assert.throws(()=>E.createSession(emits));
 v4Results.push({profile,normalization:true,passiveEmitterRejected:true,missingSettingsRejected:true,forwardAndReverseTrace:true,gaussianLensTransform:true,missingFocalLengthBlocked:true});
}
assert.equal(projectCount,3);assert.ok(projectResults.every(p=>p.compatible),JSON.stringify(projectResults.filter(p=>!p.compatible)));
console.log(JSON.stringify({passed:true,actualEditorBoardValidation:true,projectCount,compatibleProjectFiles:projectResults.filter(p=>p.compatible).length,blockedProjectFiles:projectResults.filter(p=>!p.compatible).length,projectResults,v4Results},null,2));
