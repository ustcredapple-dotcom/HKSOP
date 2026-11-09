'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const E=require('../static/optical-engine.js'),R=require('../static/optical-renderer.js'),catalog=require('../catalog.json');
const copy=x=>JSON.parse(JSON.stringify(x)),near=(a,b,epsilon=1e-6)=>assert.ok(Math.abs(a-b)<=epsilon,`${a} != ${b}`);
let checks=0;function test(name,fn){fn();checks++;console.log('PASS '+name)}
const kits=new Map(catalog.kits.map(k=>[k.id,k])),mirrorKit=kits.get('fixed-1-45'),waveKit=kits.get('waveplate');
const plate=(delta=180)=>({inserted:true,fastAxisDeg:0,retardanceDeg:delta,designWavelengthNm:532});
const pair={...E.defaults('waveplate'),configured:true,inserted:true,waveplates:[plate(),plate(90)]};
const beam=E.createBeam({...E.defaults('source').source,wavelengthNm:532,powerMw:10,polarizationAngleDeg:15});
const mirror={...E.defaults('mirror'),configured:true,inserted:true,surfaceAngleDeg:45,mirror:{mode:'data',model:'BDM1-A',samples:[]}};
const arrival=(overrides={})=>({id:'in-1',ordinal:1,sourceId:'source',branchId:'branch-1',pathMm:100,direction:{x:1,y:0},reverse:false,dependsOnEarlierPass:false,beam:copy(beam),...overrides});

// Small form DOM: IDs, values, checked state and event delegation only. The
// production property methods and numerical engine run unchanged in the VM.
function formFixture(config=pair,arrivals=[arrival()],purchaseRows=[]){
  const nodes=new Map();
  const decode=s=>String(s||'').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
  class Node{
    constructor(id){this.id=id;this._value='';this._html='';this.hidden=false;this.checked=false;this.textContent='';this.dataset={};this.handlers={};this.classes=new Set();this.classList={add:n=>this.classes.add(n),remove:n=>this.classes.delete(n)};}
    set value(v){this._value=String(v)}get value(){return this._value}
    set innerHTML(html){this._html=html;for(const tag of html.matchAll(/<(input|select|div|p|button|fieldset)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){const n=make(tag[3]);n.checked=/\bchecked\b/.test(tag[2]);n.hidden=/\bhidden\b/.test(tag[2]);if(tag[1]==='input')n.value=decode(tag[2].match(/\bvalue="([^"]*)"/)?.[1]||'');if(tag[1]==='select'){const content=html.slice(tag.index+tag[0].length).split('</select>')[0],options=[...content.matchAll(/<option\b([^>]*)>/g)],selected=options.find(o=>/\bselected\b/.test(o[1]))||options[0];n.value=decode(selected?.[1].match(/value="([^"]*)"/)?.[1]||'');}}}
    get innerHTML(){return this._html}addEventListener(event,fn){this.handlers[event]=fn}showModal(){this.open=true}close(){this.open=false}reportValidity(){return true}setAttribute(){}
  }
  function make(id){if(!nodes.has(id))nodes.set(id,new Node(id));return nodes.get(id)}
  const document={getElementById:id=>nodes.get(id)||null,addEventListener(){}};
  class Editor{bind(){}}
  const context={BreadboardEditor:Editor,ZZLabOpticalEngine:E,document,console};context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/optical-renderer.js'),'utf8'),context);
  for(const id of ['optical-dialog-fields','optical-purchase-fields','optical-dialog-error','optical-form','optical-dialog','optical-dialog-save'])make(id);
  const e=new Editor(),element={id:'w',center:{x:100,y:100},rotationDeg:0,optics:copy(config),axisHeightMm:63.5};
  e.svg=make('board-svg');e.catalog=catalog;e.opticalTrace={segments:[]};e.opticalSignature=()=> 'unchanged';e.opticalScene=()=>({elements:[element,{id:'source',name:'出光'}]});e._opticalTarget={id:'w',options:{},kit:config.elementType==='mirror'?mirrorKit:waveKit,element,config:copy(config),purchaseRows:copy(purchaseRows),incoming:copy(arrivals),trace:e.opticalTrace,sceneKey:'unchanged'};
  make('optical-dialog-fields').innerHTML=e.opticalFormMarkup(config);make('optical-purchase-fields').innerHTML=e.opticalPurchaseMarkup(purchaseRows);e.bind();
  return{e,n:id=>nodes.get(id),make,nodes};
}
const row=(type,model)=>({slotId:type==='mirror'?'mirror':'wave-1',type,label:'光学片',inserted:true,name:'光学片',model,supplier:'麓邦',kind:'lubang',quantity:1});

test('new mirrors require data, old saved optics retain explicit legacy compatibility, replacements discard coefficients',()=>{
  const purchase={'m::mirror':{model:'BDM1-A',inserted:true}},fresh=R.configFor({id:'m'},mirrorKit,purchase,E,catalog);assert.equal(fresh.mirror.mode,'data');assert.deepEqual(fresh.mirror.samples,[]);
  const legacy={...E.defaults('mirror'),inserted:true};assert.equal(R.configFor({id:'m',optics:legacy},mirrorKit,purchase,E,catalog).mirror,undefined);
  const saved={...mirror,mirror:{mode:'data',model:'OLD',samples:[{wavelengthNm:532,incidenceAngleDeg:45,reflectanceP:.9,reflectanceS:.8,phaseDifferenceDeg:100}]}};
  const changed=R.configFor({id:'m',optics:saved},mirrorKit,purchase,E,catalog);assert.equal(changed.mirror.model,'BDM1-A');assert.deepEqual(changed.mirror.samples,[]);
});
test('scene keeps only current source wavelengths, shares small records, and never embeds full spectra per mirror',()=>{
  const board={widthMm:1000,heightMm:500},source={id:'s',kitId:'fiber-coupling',xMm:50,yMm:50,optics:{...E.defaults('coupler'),source:{...E.defaults('source').source,enabled:true,wavelengthNm:532}}};
  const mirrors=Array.from({length:100},(_,n)=>({id:'m'+n,kitId:mirrorKit.id,xMm:200+n,yMm:200,optics:copy(mirror)})),purchases=Object.fromEntries(mirrors.map(i=>[i.id+'::mirror',{model:'BDM1-A'}]));
  const scene=R.sceneFor({board,instances:[source,...mirrors]},kits,purchases,[],E,catalog),records=scene.elements.filter(e=>e.optics.elementType==='mirror').map(e=>e.mirrorCoating),full=R.mirrorOption('BDM1-A',catalog).mirrorCoating;
  assert.ok(full.samples.length>256);assert.ok(records[0].samples.length>0&&records[0].samples.length<=2);assert.ok(records.every(r=>r===records[0]));assert.ok(records[0].samples.every(s=>s.wavelengthNm===532));assert.ok(full.samples.length>256);assert.ok(JSON.stringify(scene).length<200000);
  source.optics.source.enabled=false;assert.deepEqual(R.sceneFor({board,instances:[source,...mirrors]},kits,purchases,[],E,catalog).elements[1].mirrorCoating.samples,[]);
});
test('mirror form defaults to catalog, shows provenance, and preserves unknown signed phase as null',()=>{
  const{e,n}=formFixture(mirror,[arrival()],[row('mirror','BDM1-A')]);assert.equal(n('optics-mirror-mode').value,'catalog');assert.match(n('optical-dialog-fields').innerHTML,/查看原厂资料/);assert.match(n('optical-dialog-fields').innerHTML,/强度反射率/);
  n('optics-mirror-mode').value='custom';e.useMirrorArrival();assert.equal(n('optics-mirror-lambda').value,'532');near(Number(n('optics-mirror-aoi').value),45);assert.equal(n('optics-mirror-phase').value,'');assert.ok(Number(n('optics-mirror-rp').value)>90);
  const saved=e.readMirrorForm();assert.equal(saved.samples.length,1);assert.equal(saved.samples[0].phaseDifferenceDeg,null);near(saved.samples[0].reflectanceP,Number(n('optics-mirror-rp').value)/100);assert.match(n('optics-mirror-preview').innerHTML,/未提供|相位/);
  n('optics-mirror-phase').value='90';const exact=e.readMirrorForm();assert.equal(exact.samples[0].phaseDifferenceDeg,90);n('optics-mirror-mode').value='ideal';assert.equal(e.readMirrorForm().mode,'ideal');n('optics-mirror-mode').value='catalog';assert.equal(e.readMirrorForm().samples.length,0);
});
test('pure P uses known reflectances without pretending unknown phase was measured',()=>{
  const a=arrival({beam:E.createBeam({...E.defaults('source').source,wavelengthNm:532,polarizationAngleDeg:0})}),{e,n}=formFixture(mirror,[a],[row('mirror','BDM1-A')]);e.updateMirrorPreview();assert.match(n('optics-mirror-preview').innerHTML,/本束输出不依赖 P\/S 相位差/);assert.match(n('optics-mirror-preview').innerHTML,/厂家相位仍未知/);
});
test('changing a model clears coefficients, including a model field edited without a change event before Save',()=>{
  const config=copy(mirror);config.mirror.samples=[{wavelengthNm:532,incidenceAngleDeg:45,reflectanceP:.9,reflectanceS:.8,phaseDifferenceDeg:100}];
  const{e,n}=formFixture(config,[arrival()],[row('mirror','BDM1-A')]);assert.equal(n('optics-mirror-mode').value,'custom');n('optics-purchase-0-model').value='BDM1-B';const changed=e.readOpticalForm();assert.equal(changed.mirror.model,'BDM1-B');assert.deepEqual(copy(changed.mirror.samples),[]);assert.equal(n('optics-mirror-mode').value,'catalog');
  e.changeMirrorModel('BDM1-A',{fromPicker:true});assert.equal(n('optics-purchase-0-model').value,'BDM1-A');assert.equal(e.readOpticalPurchases()[0].model,'BDM1-A');
});
test('multi-pass selection is explicit and trace arrivals distinguish true feedback from independent paths',()=>{
  const segments=[{id:'a',sourceId:'s',branchId:'b1',lineageKey:'[]',pathEndMm:20},{id:'b',sourceId:'s',branchId:'b2',lineageKey:'[["pbs","R"]]',pathEndMm:50},{id:'c',sourceId:'other',branchId:'b3',lineageKey:'[]',pathEndMm:60}].map(s=>({...s,hitInstanceId:'w',direction:{x:1,y:0}}));
  const incoming=R.incidentBeams({segments},'w',{},{waveplateReverse:()=>false,beamAt:()=>copy(beam)});assert.deepEqual(incoming.map(a=>a.dependsOnEarlierPass),[false,true,false]);
  const{n}=formFixture(pair,incoming);assert.equal(n('optics-solver-arrival').value,'');assert.match(n('optical-dialog-fields').innerHTML,/不同分支／回程/);
});
test('actual first-arrival solver fills physical slots, reports ellipse, and saves through the existing transaction',()=>{
  const{e,n}=formFixture();n('optics-solver-target').value='elliptical';n('optics-solver-angle').value='25';n('optics-solver-ellipticity').value='18';e.solveOpticalTarget();assert.equal(n('optics-solver-result').classes.has('error'),false,n('optics-solver-result').textContent);assert.match(n('optics-solver-result').textContent,/已填入/);
  const updated=e.readOpticalForm(),output=E.applyWaveplateSequence(beam.stokes,updated.waveplates,false);
  const desired=E.stokesFromSource({polarizationType:'elliptical',polarizationAngleDeg:25,ellipticityDeg:18});for(const key of ['s1','s2','s3'])near(output[key],desired[key]);
  let saved;e.setInstanceOptics=(id,o,p)=>{saved={id,o,p}};e.renderOptics=()=>{};e.saveOpticalForm();assert.equal(saved.id,'w');assert.equal(saved.o.waveplates[0].fastAxisDeg,updated.waveplates[0].fastAxisDeg);assert.equal(n('optical-dialog').open,false);
});
test('reverse first arrival uses physical slot order, while a feedback return is refused without angle changes',()=>{
  const{e,n}=formFixture(pair,[arrival({reverse:true})]);n('optics-solver-target').value='circular-right';e.solveOpticalTarget();assert.equal(n('optics-solver-result').classes.has('error'),false,n('optics-solver-result').textContent);const configured=e.readOpticalForm(),output=E.applyWaveplateSequence(beam.stokes,configured.waveplates,true);near(output.s3,-1);
  const before=configured.waveplates.map(p=>p.fastAxisDeg);e._opticalTarget.incoming[0].dependsOnEarlierPass=true;e.solveOpticalTarget();assert.match(n('optics-solver-result').textContent,/此前已穿过同一双波片/);assert.deepEqual(e.readOpticalForm().waveplates.map(p=>p.fastAxisDeg),before);
});
test('missing incoming, stale trace, missing design wavelength and impossible retarders never overwrite angles',()=>{
  for(const change of [(e,n)=>n('optics-solver-arrival').value='',(e)=>e.opticalTrace={},(e,n)=>n('optics-wave-0-wavelength').value='',(e,n)=>{n('optics-wave-0-retardance').value='0';n('optics-wave-1-retardance').value='0';n('optics-solver-target').value='circular-left';}]){
    const{e,n}=formFixture();change(e,n);e.solveOpticalTarget();assert.equal(n('optics-solver-result').classes.has('error'),true);assert.equal(n('optics-wave-0-axis').value,'0');assert.equal(n('optics-wave-1-axis').value,'0');
  }
});
test('explicit manual input solves independently and editing a target or angle clears previous success',()=>{
  const{e,n}=formFixture(pair,[]);n('optics-solver-arrival').value='manual';n('optics-solver-manual-wavelength').value='532';n('optics-solver-manual-polarization').value='linear';n('optics-solver-target').value='circular-left';e.syncOpticalSolverFields();assert.equal(n('optics-solver-manual').hidden,false);e.solveOpticalTarget();assert.equal(n('optics-solver-result').classes.has('error'),false);
  n('optical-dialog-fields').handlers.input({target:n('optics-wave-0-axis')});assert.equal(n('optics-solver-result').hidden,true);assert.equal(n('optics-solver-result').textContent,'');
});
test('known replacements use explicit manufacturer typical delay; unknown replacements clear old optical parameters',()=>{
  const{e,n}=formFixture(pair,[arrival()],[row('waveplate','custom-old'),{...row('waveplate','QWP13-532A'),slotId:'wave-2'}]);e.changeWaveplateModel(0,'HWP13-532A');near(Number(n('optics-wave-0-retardance').value),182.88);assert.equal(n('optics-wave-0-wavelength').value,'532');assert.match(n('optics-wave-0-data-note').textContent,/原厂目录.*典型.*单件/);
  e.changeWaveplateModel(0,'unverified-new');assert.equal(n('optics-wave-0-retardance').value,'');assert.equal(n('optics-wave-0-wavelength').value,'');
  const fresh=R.configFor({id:'w'},waveKit,{'w::wave-1':{model:'HWP13-532A',wavelength:'633'}},E,catalog);near(fresh.waveplates[0].retardanceDeg,182.88);assert.equal(fresh.waveplates[0].designWavelengthNm,532,'typical retardance remains tied to its measured wavelength');
  const saved={...copy(pair),waveplates:[{...plate(),retardanceDeg:179.5},plate(90)]};const config=R.configFor({id:'w',optics:saved},waveKit,{'w::wave-1':{model:'HWP13-532A'}},E,catalog);near(config.waveplates[0].retardanceDeg,179.5);
});
test('polarization readout exposes signed ellipticity, direction and degree, beyond only P/S powers',()=>{
  const s=E.stokesFromSource({polarizationType:'elliptical',polarizationAngleDeg:25,ellipticityDeg:-18});assert.match(R.polarText({stokes:s}),/椭圆偏振.*ψ 25°.*χ -18°/);assert.match(R.polarText({stokes:{s1:0,s2:0,s3:.5}}),/左旋圆偏振.*DoP 50%/);assert.match(R.polarText({stokes:{s1:0,s2:0,s3:0}}),/非偏振/);
});
test('custom DSL property UI locks semantics, exposes inherited parameters, hides overridden controls and escapes text',()=>{
  const config=E.normalizeOptics({elementType:'unsupported',inserted:true,configured:true}),{e,n}=formFixture(config,[]),program={format:'zzlab-optical-interaction',version:1,model:'planar',onNoMatch:'block',inputs:[{id:'<b>input</b>',steps:[{op:'attenuate',transmission:.8},{op:'lens',focalLengthMm:50},{op:'block',reason:'<img src=x onerror=bad>'}]}]};e._opticalTarget.kit={layout:{opticalInteraction:program}};n('optical-dialog-fields').innerHTML=e.opticalFormMarkup(config);const html=n('optical-dialog-fields').innerHTML;assert.match(html,/由交互协议定义/);assert.match(html,/<select disabled id="optics-type"/);assert.doesNotMatch(html,/仅布局|<img src=x|<b>input/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/id="optics-focal"/);assert.match(html,/id="optics-surface"/);n('optics-type').value='source';assert.equal(e.readOpticalForm().elementType,'unsupported');delete program.inputs[0].steps[1].focalLengthMm;assert.match(e.opticalFormMarkup(config),/id="optics-focal"/);
});
console.log(`${checks} optical properties checks passed`);
