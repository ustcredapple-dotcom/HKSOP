'use strict';
const assert=require('node:assert/strict'),E=require('../static/optical-engine.js'),R=require('../static/optical-renderer.js');
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
const catalog={components:[{id:'hwp',model:'HWP25-532A'},{id:'lens',model:'BCX10613-A'}],opticalOptions:[
  {model:'HWP25-532A',opticalType:'half-wave',wavelengthNm:532},
  {model:'BCX10613-A',focalLengthMm:100}
]};
const kit=(id,type,extra={})=>({id,name:id,category:'other',opticalSlots:[],layout:{placementAllowed:true,opticalType:type,opticalCenterMm:{xMm:0,yMm:0},opticalAxisHeightMm:63.5,opticalSurfaceAngleDeg:type==='pbs'?-45:90,...extra}});
const part=(id,more={})=>({id,kitId:id,xMm:100,yMm:100,rotationDeg:0,...more});
const board={widthMm:500,heightMm:400,thicknessMm:12.7};
const emitter=(id='source',y=100)=>({id,name:id,center:{x:0,y},rotationDeg:0,axisHeightMm:63.5,optics:E.normalizeOptics({elementType:'source',inserted:true,source:{enabled:true,directionAngleDeg:0,polarizationAngleDeg:45}})});
function opticalScene(k,instance=part(k.id)){const result=R.sceneFor({board,instances:[instance]},new Map([[k.id,k]]),{},[],E,catalog);result.elements.unshift(emitter());return result}

const wave=kit('single-waveplate','waveplate');wave.opticalSlots=[{id:'wave-1',type:'waveplate',replacesComponentId:'hwp',diameterMm:25.4}];
let config=R.configFor(part(wave.id),wave,{},E,catalog);
assert.equal(config.elementType,'waveplate');assert.equal(config.inserted,true);assert.equal(config.waveplates.length,1);assert.equal(config.waveplates[0].retardanceDeg,180);assert.equal(config.waveplates[0].designWavelengthNm,532);assert.equal(config.surfaceAngleDeg,90);
let trace=E.createSession(opticalScene(wave));assert.equal(trace.pending[0].instanceId,wave.id);trace=E.advancePending(trace,trace.pending[0].id);near(trace.segments[1].beam.stokes.s2,-1);
config=R.configFor(part(wave.id),wave,{'single-waveplate::wave-1':{inserted:false}},E,catalog);assert.equal(config.inserted,false);assert.equal(config.configured,true);
console.log('PASS single waveplate derives verified included HWP, intersects +X beam, and respects explicit removal');

const pbs=kit('half-inch-pbs','pbs');trace=E.createSession(opticalScene(pbs));trace=E.advancePending(trace,trace.pending[0].id);const reflection=trace.segments.find(s=>s.direction.y<-.9);assert.ok(reflection);near(reflection.direction.x,0);near(reflection.direction.y,-1);
console.log('PASS new PBS orientation maps source +X to reflected −Y');

const lens=kit('lens-filter','lens');lens.opticalSlots=[{id:'lens-1',type:'lens',replacesComponentId:'lens',diameterMm:25.4}];
config=R.configFor(part(lens.id),lens,{},E,catalog);assert.equal(config.inserted,true);assert.equal(config.focalLengthMm,100);
trace=E.createSession(opticalScene(lens));trace=E.advancePending(trace,trace.pending[0].id);assert.ok(trace.segments[1].focus);
config=R.configFor(part(lens.id),lens,{'lens-filter::lens-1':{inserted:true,model:'UNKNOWN-REPLACEMENT'}},E,catalog);assert.equal(config.focalLengthMm,null);
trace=E.createSession(opticalScene(lens,{...part(lens.id),optics:config}));assert.equal(E.autoAdvance(trace).issues[0].code,'lens_focal_length_missing');
console.log('PASS included verified lens uses its focal data; a replacement model cannot inherit the old focal length');

for(const [name,datum] of [['PD',false],['iris',false],['beamdump',true],['AOM',false],['isolator',false]]){
  const k=kit(name,'unsupported',{opticalDatumVerified:datum,opticalSimulationNote:datum?'仅布局，尚不支持光学追踪。':'光学功能面基准待确认；仅布局，尚不支持光学追踪。'});
  assert.equal(R.elementType(k),'unsupported');
  for(const override of [undefined,{...E.defaults('empty'),configured:true,inserted:false},{...E.defaults('lens'),inserted:true,focalLengthMm:25},{...E.defaults('source'),inserted:true,source:{enabled:true}}]){
    const scene=opticalScene(k,part(k.id,override?{optics:override}:{}));scene.elements.push(emitter('independent',200));
    const before=E.createSession(scene);assert.equal(before.pending.length,1);assert.equal(before.pending[0].instanceId,name);assert.equal(before.segments.filter(s=>s.sourceId==='source').length,1);
    const result=E.autoAdvance(before);assert.equal(result.blocked,true);assert.equal(result.events.length,0);assert.equal(result.issues[0].code,datum?'optics_unsupported':'optical_datum_unknown');assert.ok(result.session.completed.some(c=>c.sourceId==='independent'&&c.reason==='escaped'));
    const clicked=E.advancePending(before,before.pending[0].id,{elementType:'lens',inserted:true,focalLengthMm:10});assert.equal(clicked.pending.length,1);assert.equal(clicked.segments.length,before.segments.length);assert.equal(clicked.completed.length,before.completed.length);
  }
  const offPath=opticalScene(k,part(k.id,{yMm:300})),clear=E.autoAdvance(E.createSession(offPath));assert.equal(clear.done,true);assert.equal(clear.issues.length,0);
}
console.log('PASS five unsupported kits stop only encountered beams; empty/source/lens overrides cannot bypass catalog restrictions, independent paths still finish');

const oldKit={id:'legacy-mount',category:'lens',layout:{opticalAxisHeightMm:63.5},opticalSlots:[]},saved={...E.defaults('mirror'),inserted:true,surfaceAngleDeg:45};
assert.deepEqual(R.configFor(part(oldKit.id,{optics:saved}),oldKit,{},E,catalog),E.normalizeOptics(saved));assert.equal(R.elementType(oldKit),'lens');assert.equal(R.catalogSimulationIssue(oldKit),null);
console.log('PASS metadata is opt-in and old project instance optics retain their prior behavior');

// Real catalog integration: these metadata values describe the supplied STEP
// assemblies, rather than a guessed category-to-lens fallback.
const published=require('../catalog.json'),publishedKits=new Map(published.kits.map(k=>[k.id,k]));
const expected=[['new-waveplate-single','waveplate',true],['new-pbs-05','pbs',true],['new-pd','unsupported',false],['new-lens-filter','lens',true],['new-iris','unsupported',false],['new-beam-dump','unsupported',true],['new-aom','unsupported',false],['new-isolator','unsupported',false]];
assert.equal(published.kits.filter(k=>expected.some(([id])=>k.id===id)).length,expected.length,'all original eight additions remain uniquely registered alongside later releases');
function publishedScene(instance){const result=R.sceneFor({board,instances:[instance]},publishedKits,{},[],E,published);result.elements.unshift({...emitter(),axisHeightMm:62.5});return result}
for(const [id,type,datumVerified] of expected){
  const k=publishedKits.get(id);assert.ok(k,id);assert.equal(k.layout.opticalType,type);assert.equal(k.layout.opticalDatumVerified,datumVerified);assert.deepEqual(k.layout.opticalCenterMm,{xMm:id==='new-waveplate-single'?9.6:0,yMm:0});assert.equal(k.layout.opticalAxisHeightMm,62.5);
  config=R.configFor(part(id),k,{},E,published);assert.equal(config.elementType,type);assert.equal(config.inserted,true,`${id} uses its actual included optic`);assert.equal(config.surfaceAngleDeg,type==='pbs'?-45:90);assert.equal(config.source.enabled,false,'none of the new optical devices emit by default');
  if(type==='waveplate'){assert.equal(config.waveplates.length,1);assert.equal(config.waveplates[0].inserted,true);assert.equal(config.waveplates[0].retardanceDeg,182.88,'included HWP uses the manufacturer typical 532 nm retardance');assert.equal(config.waveplates[0].designWavelengthNm,532);}
  if(type==='lens')assert.equal(config.focalLengthMm,100);
  const scene=publishedScene(part(id));trace=E.createSession(scene);assert.equal(trace.pending[0].instanceId,id);near(trace.pending[0].pathMm,100+k.layout.opticalCenterMm.xMm);
  const traced=E.autoAdvance(trace);
  if(type==='unsupported'){
    assert.equal(traced.blocked,true);assert.equal(traced.session.segments.length,1);assert.equal(traced.issues[0].code,datumVerified?'optics_unsupported':'optical_datum_unknown');assert.equal(traced.issues[0].message,k.layout.opticalSimulationNote);assert.ok(traced.issues[0].message.length>10);
    const away=E.autoAdvance(E.createSession(publishedScene(part(id,{yMm:300}))));assert.equal(away.done,true);assert.equal(away.issues.length,0);
    const overridden=publishedScene(part(id,{optics:{...E.defaults('source'),source:{enabled:true},surfaceAngleDeg:0}}));assert.equal(overridden.elements[1].optics.elementType,'unsupported');assert.equal(overridden.elements[1].optics.source.enabled,false);assert.equal(E.autoAdvance(E.createSession(overridden)).blocked,true);
  }else{
    assert.equal(traced.done,true);assert.equal(traced.issues.length,0);
    if(type==='pbs'){assert.equal(traced.session.segments.length,3);assert.ok(traced.session.segments.some(s=>s.direction.y<-.9));}
    if(type==='lens')assert.ok(traced.session.segments.some(s=>s.focus));
  }
}
console.log('PASS all eight published kits use correct datum flags and included optics: 532 nm HWP, PBS −Y reflection, BCX10613-A f=100 mm, five explicit per-hit pauses');

const codec=require('../static/project-file.js'),settings=R.configFor(part('new-pd'),publishedKits.get('new-pd'),{},E,published);
const project=codec.create({metadata:{name:'新器件光学设置往返'},catalogVersion:published.version,layout:{board:{...board,pitchMm:12.5,edgeOffsetMm:12.5,holeType:'M6_through',mountingHoles:[]},instances:[part('new-pd',{optics:settings})]},optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],view:null}},{catalog:published});
const reopened=codec.parse(JSON.stringify(project),{catalog:published}).project;assert.equal(reopened.layout.instances[0].optics.elementType,'unsupported');assert.equal(E.autoAdvance(E.createSession(publishedScene(reopened.layout.instances[0]))).blocked,true);
console.log('PASS actual new detector project round-trip retains optical placeholder and catalog restriction');
