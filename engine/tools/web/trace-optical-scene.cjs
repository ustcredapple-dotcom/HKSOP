#!/usr/bin/env node
'use strict';
/* Read-only forward trace for an isolated engine scene; no catalog or DB writes. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const ROOT=path.resolve(__dirname,'..'),E=require(path.join(ROOT,'static/optical-engine.js'));
const LIMITS=Object.freeze({maxSteps:256,maxSegments:2048,maxBranches:128,maxPathMm:1e6,minPowerMw:1e-12,heightToleranceMm:.1,pauseOnHeightErrors:true});
const MAX_INPUT_BYTES=8*1024*1024,MAX_ELEMENTS=500,MAX_EVENTS=4096,MAX_MILLISECONDS=5000;
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const copy=value=>JSON.parse(JSON.stringify(value));
function ensureFinite(value){
  const stack=[value];
  while(stack.length){const v=stack.pop();if(typeof v==='number'&&!Number.isFinite(v))throw new Error('Scene contains a non-finite number.');if(v&&typeof v==='object')stack.push(...Object.values(v));}
}
function loadScene(filename){
  const resolved=path.resolve(filename),stat=fs.statSync(resolved);
  if(!stat.isFile()||stat.size>MAX_INPUT_BYTES)throw new Error('Scene must be a regular JSON file no larger than 8 MiB.');
  const bytes=fs.readFileSync(resolved);if(bytes.length>MAX_INPUT_BYTES)throw new Error('Scene exceeds 8 MiB.');
  const scene=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes).replace(/^\uFEFF/,''));
  ensureFinite(scene);
  if(!scene||typeof scene!=='object'||Array.isArray(scene)||Object.keys(scene).some(k=>!['bounds','elements','modules'].includes(k)))throw new Error('Expected an engine scene with bounds/elements/optional modules, not a project or catalog.');
  if(!Array.isArray(scene.elements)||scene.elements.length<1||scene.elements.length>MAX_ELEMENTS)throw new Error('Scene needs 1–500 elements.');
  if(!scene.bounds)throw new Error('Scene requires explicit bounds in mm.');
  return{scene,input:{path:resolved,sha256:hash(bytes),bytes:bytes.length}};
}
function beamSummary(beam){
  if(!beam)return null;
  return Object.fromEntries(['wavelengthNm','powerMw','axisHeightMm','stokes','q','beamQualityM2','diameterMm','waistDiameterMm','wavefrontRadiusMm','focusDistanceMm'].filter(k=>beam[k]!==undefined).map(k=>[k,copy(beam[k])]));
}
function traceScene(scene){
  const start=Date.now();let session=E.createSession(scene,undefined,LIMITS),last,events=0,toolIssue=null;
  do{
    last=E.autoAdvance(session,{maxEvents:Math.min(128,MAX_EVENTS-events),maxMilliseconds:50});
    session=last.session;events+=last.events.length;
    if(last.done||last.blocked||!last.canContinue)break;
    if(events>=MAX_EVENTS||Date.now()-start>=MAX_MILLISECONDS){toolIssue={code:'cli_trace_budget',message:'CLI tracing budget reached; result is incomplete.',blocking:true};break;}
  }while(true);
  const issues=copy(last.issues);
  if(toolIssue)issues.push(toolIssue);
  if(!session.sourceIds.length&&!issues.length)issues.push({code:'no_enabled_source',message:'No valid enabled source emitted a beam.',blocking:true});
  const blocked=issues.some(i=>i.blocking)||!last.done,done=!blocked;
  const segments=session.segments.map(s=>({id:s.id,sourceId:s.sourceId,branchId:s.branchId,from:s.from,to:s.to,direction:s.direction,lengthMm:s.lengthMm,pathStartMm:s.pathStartMm,pathEndMm:s.pathEndMm,hitInstanceId:s.hitInstanceId,hitModuleId:s.hitModuleId,beamAtStart:beamSummary(E.beamAt(s,0)),beamAtEnd:beamSummary(E.beamAt(s,1)),...(s.focus?{focus:s.focus}:{})}));
  const endpoints=session.completed.map(terminal=>{
    const segment=[...session.segments].reverse().find(s=>s.branchId===terminal.branchId&&s.sourceId===terminal.sourceId&&Math.abs(s.pathEndMm-terminal.pathMm)<1e-6&&Math.hypot(s.to.x-terminal.point.x,s.to.y-terminal.point.y)<1e-6);
    const finalBeam=terminal.finalBeam?beamSummary(E.gaussianAt(terminal.finalBeam)):terminal.reason==='escaped'&&segment?beamSummary(E.beamAt(segment,1)):null;
    return{...copy(terminal),finalBeam,beamState:terminal.finalBeam?'verified-post-interaction-terminal':finalBeam?'verified-at-segment-end':'terminal-state-not-exposed-by-engine'};
  });
  return{format:'zzlab-optical-scene-trace',version:1,done,blocked,limits:{...LIMITS,maxEvents:MAX_EVENTS,maxMilliseconds:MAX_MILLISECONDS,maxElements:MAX_ELEMENTS,maxInputBytes:MAX_INPUT_BYTES},counts:{sources:session.sourceIds.length,events,segments:segments.length,branches:session.counters.branches,pending:session.pending.length,completed:endpoints.length},issues,warnings:session.warnings,endpoints,pending:session.pending.map(p=>({id:p.id,instanceId:p.instanceId,moduleId:p.moduleId,sourceId:p.sourceId,branchId:p.branchId,point:p.point,pathMm:p.pathMm,direction:p.direction,beam:beamSummary(E.gaussianAt(p.beam)),issue:E.pendingIssue(session,p)})),focusPoints:segments.filter(s=>s.focus).map(s=>({segmentId:s.id,sourceId:s.sourceId,branchId:s.branchId,...s.focus})),segments,scope:'Synthetic engine scene only. Not a catalog registration, engineering-project import, or certification of a real optic. Terminal power and final Stokes/q are the actual post-interaction state; legacy engines without terminal states retain an explicit null.'};
}
function main(argv=process.argv.slice(2)){
  if(argv.length===1&&['--help','-h'].includes(argv[0])){console.log('Usage: node tools/trace-optical-scene.cjs <scene.json>\nRead-only isolated forward trace. JSON summary on stdout. Exit 0: completed; 1: blocked/incomplete; 2: invalid input.\nScene is an engine fixture, not .zzoptics.json or catalog.json. No output file or network operations.');return 0;}
  try{
    if(argv.length!==1||argv[0].startsWith('-'))throw new Error('Expected one scene JSON path; use --help.');
    const{scene,input}=loadScene(argv[0]),summary=traceScene(scene);
    console.log(JSON.stringify({...summary,input},null,2));return summary.blocked?1:0;
  }catch(error){console.log(JSON.stringify({format:'zzlab-optical-scene-trace',version:1,done:false,blocked:true,issues:[{code:'invalid_scene',message:error.message,blocking:true}]},null,2));return 2;}
}
module.exports={LIMITS,loadScene,traceScene,main};
if(require.main===module)process.exitCode=main();
