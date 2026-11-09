'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),app=fs.readFileSync(path.join(root,'static/app.js'),'utf8');
const harnessSource=fs.readFileSync(path.join(root,'test_project_app.cjs'),'utf8'),harness={require,__dirname:root,console};
vm.createContext(harness);vm.runInContext(harnessSource.slice(0,harnessSource.indexOf('let count=0;'))+'\nglobalThis.makeFixture=fixture;',harness);
const plain=v=>JSON.parse(JSON.stringify(v)),catalog=JSON.parse(fs.readFileSync(path.join(root,'catalog.json'),'utf8'));
const f=harness.makeFixture(),c=f.context,e=f.editor;
c.catalogInput=catalog;
vm.runInContext(`state.catalog=deepCopy(catalogInput);state.kits=new Map(state.catalog.kits.map(k=>[k.id,k]));state.components=new Map(state.catalog.components.map(k=>[k.id,k]));state.optical={};state.extras=[];state.moduleQuantities=new Map();editor.kits=state.kits;editor.instances=[{id:'wave',kitId:'waveplate',xMm:75,yMm:75,rotationDeg:0},{id:'pbs',kitId:'pbs-fixed',xMm:200,yMm:75,rotationDeg:0}];editor.setSelection([]);`,c);
const start=app.indexOf('  function knownOpticalModel('),end=app.indexOf('  function renderOptical(',start);vm.runInContext(app.slice(start,end),c);
const pbs=c.opticalPurchaseRows('pbs');assert.equal(pbs[0].inserted,true);assert.equal(pbs[0].model,'MPBS24-532');assert.equal(pbs[0].kind,'lubang');
e.instances[0].optics={elementType:'waveplate',inserted:true,waveplates:[{inserted:true,retardanceDeg:90},{inserted:false,retardanceDeg:180}]};
e.instances[1].optics={elementType:'pbs',inserted:true};
assert.deepEqual(plain(c.opticalPurchaseRows('wave')).map(r=>r.inserted),[true,false]);
const legacyPayload=plain(c.payload());
assert.equal(legacyPayload.extras.filter(r=>r.instanceId==='wave').length,1);assert.equal(legacyPayload.extras.find(r=>r.instanceId==='wave').inserted,true);assert.equal(legacyPayload.extras.find(r=>r.instanceId==='wave').model,'');
assert.equal(legacyPayload.extras.find(r=>r.instanceId==='pbs').model,'MPBS24-532');
assert.deepEqual(plain(c.state.optical),{},'derived legacy purchases do not rewrite the project');
c.state.optical['wave::wave-1']={inserted:false,model:'EXPLICITLY-REMOVED'};
assert.equal(c.opticalPurchaseRows('wave')[0].inserted,false);
assert.equal(c.payload().extras.find(r=>r.instanceId==='wave').inserted,false);
delete c.state.optical['wave::wave-1'];delete e.instances[0].optics;delete e.instances[1].optics;
const before=e.historySnapshot(),rows=c.opticalPurchaseRows('wave');
rows[0]=Object.assign(rows[0],{inserted:true,name:'实测四分之一波片',model:'CUSTOM-QWP',supplier:'自选供应商',kind:'standard',wavelength:'532',opticalType:'quarter-wave'});
rows[1]=Object.assign(rows[1],{inserted:true,name:'待选半波片',model:'',supplier:'待选供应商',kind:'standard',wavelength:'532',opticalType:'half-wave'});
c.saveOpticalPurchases('wave',rows);
e.instances[0].optics={elementType:'waveplate',inserted:true,configured:true,waveplates:[{inserted:true,fastAxisDeg:45,retardanceDeg:90,designWavelengthNm:532},{inserted:true,fastAxisDeg:0,retardanceDeg:180,designWavelengthNm:532}]};
e.commit(before);
const payload=plain(c.payload());assert.equal(payload.extras.length,2);assert.equal(payload.extras[1].inserted,true);assert.equal(payload.extras[1].model,'');assert.equal(payload.extras[0].supplier,'自选供应商');
e.undo();assert.deepEqual(plain(c.state.optical),{});assert.equal(e.instances[0].optics,undefined);
e.redo();assert.equal(c.state.optical['wave::wave-1'].model,'CUSTOM-QWP');assert.equal(e.instances[0].optics.configured,true);
console.log('PASS atomic optical/purchase undo and redo; explicit blank model survives actual payload as a pending item');

const immutable=JSON.stringify(c.state.optical);const invalid=c.opticalPurchaseRows('wave');invalid[1].quantity=2;
assert.throws(()=>c.saveOpticalPurchases('wave',invalid));assert.equal(JSON.stringify(c.state.optical),immutable);
e.select('wave');e.copySelection();const copy=e.pasteSelection(),id=copy.ids[0];
assert.equal(c.state.optical[`${id}::wave-1`].supplier,'自选供应商');assert.equal(e.instances.find(i=>i.id===id).optics.configured,true);
c.state.optical[`${id}::wave-1`].model='SECOND-QWP';assert.equal(c.state.optical['wave::wave-1'].model,'CUSTOM-QWP');
e.removeIds([id]);assert.ok(!Object.keys(c.state.optical).some(k=>k.startsWith(id+'::')));e.undo();assert.equal(c.state.optical[`${id}::wave-1`].model,'SECOND-QWP');e.undo();
console.log('PASS failed batch is atomic; copied slot/source data follows instance independently and deletion restores via undo');

const removed=c.opticalPurchaseRows('wave');removed.forEach(r=>r.inserted=false);const removalBefore=e.historySnapshot();c.saveOpticalPurchases('wave',removed);e.instances.find(i=>i.id==='wave').optics={elementType:'waveplate',inserted:false,configured:true};e.commit(removalBefore);
const project=c.window.ZZLabProjectFile.create(c.projectData(),c.projectOptions());
const parsed=c.window.ZZLabProjectFile.parse(JSON.stringify(project),c.projectOptions()).project;
assert.equal(parsed.layout.instances.find(i=>i.id==='wave').optics.configured,true);assert.equal(parsed.optical['wave::wave-1'].inserted,false);
const shared=require('../static/shared-project.js'),portable=shared.subset(plain(parsed),['wave'],{catalog,now:'2026-09-29T09:00:00.000Z'});
assert.equal(portable.layout.instances[0].optics.configured,true);assert.equal(portable.optical['wave::wave-2'].inserted,false);
console.log('PASS confirmed empty holder and removed purchases survive real project import and shared subset');

// The ordinary procurement panel edits the same bound data. Removing only one
// waveplate must retain the other plate, and a changed lens SKU needs review.
e.instances[0].optics={elementType:'waveplate',inserted:true,configured:true,waveplates:[{inserted:true,retardanceDeg:90},{inserted:true,retardanceDeg:180}]};
c.state.optical['wave::wave-1'].inserted=true;c.state.optical['wave::wave-2'].inserted=true;
c.storeOpticalInput({dataset:{instance:'wave',slot:'wave-1',opticalField:'inserted'},checked:false});
assert.equal(e.instances[0].optics.inserted,true);assert.equal(e.instances[0].optics.waveplates[0].inserted,false);assert.equal(e.instances[0].optics.waveplates[1].inserted,true);
c.storeOpticalInput({dataset:{instance:'wave',slot:'wave-2',opticalField:'model'},value:'UNVERIFIED-NEW'});
assert.equal(e.instances[0].optics.configured,false);assert.equal(e.instances[0].optics.inserted,false);assert.equal(e.instances[0].optics.waveplates[1].retardanceDeg,180);
console.log('PASS procurement edits preserve sibling waveplates and pause rendering for changed models');

// A measured coating belongs to its exact mirror, never to the replacement SKU.
{
  const previous=plain(e.instances[1]);
  e.instances[1]={id:'coated-mirror',kitId:'fixed-1-90',xMm:200,yMm:75,rotationDeg:0,
    optics:{elementType:'mirror',inserted:true,configured:true,mirror:{mode:'data',model:'BDM1-A',samples:[
      {wavelengthNm:532,incidenceAngleDeg:45,reflectanceP:.97,reflectanceS:.99,phaseDifferenceDeg:175}]}}};
  c.state.optical['coated-mirror::mirror']={model:'BDM1-A',inserted:true};
  c.storeOpticalInput({dataset:{instance:'coated-mirror',slot:'mirror',opticalField:'model'},value:'BDM1-B'});
  assert.deepEqual(plain(e.instances[1].optics.mirror),{mode:'data',model:'BDM1-B',samples:[]});
  assert.equal(e.instances[1].optics.configured,false);
  e.instances[1]=previous;delete c.state.optical['coated-mirror::mirror'];
}
console.log('PASS changing the mirror purchase model clears coefficients tied to the previous coating');

let prefs={generated:true,visible:false,autoRestore:true},restoreCalls=[];
e.opticalRenderingPrefs=()=>plain(prefs);
e.restoreOpticalRenderingPrefs=value=>{restoreCalls.push(value?plain(value):undefined);prefs=value?plain(value):{generated:false,visible:true,autoRestore:true};};
e.instances[0].optics={elementType:'coupler',inserted:true,configured:true,source:{enabled:true,directionAngleDeg:-90}};
e.instances[1].optics={elementType:'coupler',inserted:true,configured:true,source:{enabled:false}};
const remembered=c.window.ZZLabProjectFile.create(c.projectData(),c.projectOptions());
assert.deepEqual(plain(remembered.opticalRendering),prefs);
assert.deepEqual(shared.subset(plain(remembered),['wave'],{catalog}).opticalRendering,prefs);
const unopened=plain(remembered);delete unopened.opticalRendering;c.applyProject(unopened);
assert.equal(restoreCalls.at(-1),undefined);assert.equal(prefs.generated,false);
c.applyProject(remembered);assert.deepEqual(prefs,{generated:true,visible:false,autoRestore:true});
assert.equal(e.instances.find(i=>i.id==='wave').optics.source.enabled,true);assert.equal(e.instances.find(i=>i.id==='pbs').optics.source.enabled,false);
e.undo();assert.equal(prefs.generated,false);e.redo();assert.equal(prefs.generated,true);
for(const invalid of [{generated:'true',visible:true,autoRestore:true},{generated:true,visible:true},{generated:true,visible:true,autoRestore:true,segments:[]}]){
  assert.throws(()=>c.window.ZZLabProjectFile.parse({...plain(remembered),opticalRendering:invalid},c.projectOptions()));
}
for(const invalid of [0,'true',null]){const p=plain(remembered);p.layout.instances[0].optics.configured=invalid;assert.throws(()=>c.window.ZZLabProjectFile.parse(p,c.projectOptions()));}
console.log('PASS source/receiver roles and root render preferences restore with projects/history/shared; old projects do not enable rendering');

const out=process.env.ZZLAB_OPTICAL_PURCHASE_PAYLOAD;
if(out)fs.writeFileSync(out,JSON.stringify(payload));
if(process.env.ZZLAB_OPTICAL_LEGACY_PAYLOAD)fs.writeFileSync(process.env.ZZLAB_OPTICAL_LEGACY_PAYLOAD,JSON.stringify(legacyPayload));

// Assembly internals stay attached to a single mechanical kit. Changing one
// purchase slot must not keep that slot's old coating or erase its sibling.
{
  const assemblyKit={id:'objective-binding-fixture',name:'物镜总装测试',layout:{opticalAssembly:{internalElements:[{id:'lower-mirror',type:'mirror',slotId:'mirror'},{id:'side-dichroic',type:'dichroic',slotId:'dichroic'}]}},opticalSlots:[{id:'mirror',type:'mirror',label:'下方镜片'},{id:'dichroic',type:'dichroic',label:'侧面双色镜'}]};
  c.state.kits.set(assemblyKit.id,assemblyKit);
  const instance={id:'assembly-binding',kitId:assemblyKit.id,xMm:200,yMm:200,rotationDeg:0,internalOptics:{'lower-mirror':{elementType:'mirror',inserted:true,configured:true,coatingFaceIndex:1,mirror:{mode:'data',model:'MIRROR',samples:[]}},'side-dichroic':{elementType:'dichroic',inserted:true,configured:true,coatingFaceIndex:0,dichroic:{mode:'data',model:'OLD-DICHROIC',samples:[{wavelengthNm:405}]}}}};
  e.instances.push(instance);c.state.optical['assembly-binding::dichroic']={model:'OLD-DICHROIC',inserted:true};
  assert.equal(c.opticalPurchaseRows(instance.id)[0].inserted,true,'legacy internal insertion remains attached to its parent slot');
  c.storeOpticalInput({dataset:{instance:instance.id,slot:'dichroic',opticalField:'model'},value:'NEW-DICHROIC'});
  assert.deepEqual(plain(instance.internalOptics['side-dichroic'].dichroic),{mode:'data',model:'NEW-DICHROIC',samples:[]});assert.equal(instance.internalOptics['side-dichroic'].configured,false);assert.equal(instance.internalOptics['side-dichroic'].coatingFaceIndex,0);assert.equal(instance.internalOptics['lower-mirror'].mirror.model,'MIRROR');
  c.storeOpticalInput({dataset:{instance:instance.id,slot:'mirror',opticalField:'inserted'},checked:false});assert.equal(instance.internalOptics['lower-mirror'].inserted,false);assert.equal(instance.internalOptics['lower-mirror'].configured,true);
  e.instances=e.instances.filter(i=>i.id!==instance.id);c.state.kits.delete(assemblyKit.id);
}
console.log('PASS assembly purchase changes clear only the bound internal coating and preserve physical face and sibling optics');

// Installed source optics are not an implicit order for spare optics.
{
  const sourceKit=c.state.kits.get('objective-final-assembly');assert.ok(sourceKit);
  const instance={id:'original-objective',kitId:sourceKit.id,xMm:300,yMm:300,rotationDeg:0,internalOptics:Object.fromEntries(sourceKit.layout.opticalAssembly.internalElements.map(i=>[i.id,plain(i.opticalDefaults)]))};e.instances.push(instance);
  let rows=c.opticalPurchaseRows(instance.id);assert.deepEqual(plain(rows.map(r=>r.inserted)),[false,false]);assert.deepEqual(plain(rows.map(r=>r.model)),['BDM2-UVA','DM20-425SP']);
  c.saveOpticalPurchases(instance.id,rows);assert.equal(c.payload().extras.filter(x=>x.instanceId===instance.id).length,0,'merely saving optical properties adds no order');
  const slot=sourceKit.opticalSlots[1];c.storeOpticalInput({dataset:{instance:instance.id,slot:slot.id,opticalField:'model'},value:'ANOTHER-DICHROIC'});assert.equal(c.payload().extras.filter(x=>x.instanceId===instance.id).length,0,'editing model without purchase confirmation adds no order');assert.equal(instance.internalOptics['side-dichroic'].inserted,true);
  c.storeOpticalInput({dataset:{instance:instance.id,slot:slot.id,opticalField:'inserted'},checked:true});assert.equal(c.payload().extras.filter(x=>x.instanceId===instance.id).length,1);assert.equal(instance.internalOptics['side-dichroic'].inserted,true);
  c.storeOpticalInput({dataset:{instance:instance.id,slot:slot.id,opticalField:'inserted'},checked:false});assert.equal(c.payload().extras.filter(x=>x.instanceId===instance.id).length,0);assert.equal(instance.internalOptics['side-dichroic'].inserted,true,'cancel order leaves installed source optic in the light path');
  e.instances=e.instances.filter(i=>i.id!==instance.id);
}

vm.runInContext(app.split('\n').find(line=>line.startsWith('  const escape =')),c);
const optStart=app.indexOf('  function opticalKey('),optEnd=app.indexOf('  function storeOpticalInput(',optStart);vm.runInContext(app.slice(optStart,optEnd),c);
const markup=vm.runInContext('renderOptical(state.kits.get("objective-final-assembly"),true,"unconfigured-original")',c);assert.match(markup,/value="BDM2-UVA"/);assert.match(markup,/value="DM20-425SP"/);assert.match(markup,/aria-label="[^"]*另购替换件并加入清单"/);assert.doesNotMatch(markup,/aria-label="[^"]*已安装并加入清单"/);assert.match(markup,/未勾选另购，不加入采购清单/);
console.log('PASS original installed objective optics are never ordered by default or by saving settings; explicit purchase alone enters BOM');
