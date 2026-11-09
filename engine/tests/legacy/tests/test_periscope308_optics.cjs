'use strict';
// Frozen R2 optical geometry; no writes to catalog, CAD, DB or saved projects.
const fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const E=require('../static/optical-engine.js'),A=require('../static/optical-assembly-engine.js'),R=require('../static/optical-renderer.js'),Side=require('../static/objective-sideview.js'),Project=require('../static/project-file.js');
const baseline=JSON.parse(fs.readFileSync(process.env.PERISCOPE308_CATALOG||path.join(__dirname,'../catalog.json'),'utf8')),fixture=require('./fixtures/periscope308_g58_r2.json'),kit=baseline.kits.find(k=>k.id===fixture.kit.id)||fixture.kit;
const catalog={...baseline,kits:[...baseline.kits.filter(k=>k.id!==kit.id),kit]},kits=new Map(catalog.kits.map(k=>[k.id,k])),clone=x=>JSON.parse(JSON.stringify(x));
let checks=0;const results=[],near=(a,b,t=1e-6)=>assert.ok(Math.abs(a-b)<t,`${a} != ${b}`),test=(name,f)=>{const detail=f();checks++;results.push({name,status:'passed',...(detail||{})});console.log('PASS '+name)};
const ideal={elementType:'mirror',inserted:true,configured:true,coatingFaceIndex:0,mirror:{mode:'ideal',samples:[]}},board={widthMm:700,heightMm:500,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]};
function moduleScene(rotationDeg=0,baseElevationMm=0,reverse=false,optics=ideal){
 const layout={board,instances:[{id:'r2',kitId:kit.id,xMm:400,yMm:350,rotationDeg,elevationMm:baseElevationMm,internalOptics:Object.fromEntries(kit.layout.opticalAssembly.nodes.map(n=>[n.id,clone(optics)]))}]};
 const scene=R.sceneFor(layout,kits,{},[],E,catalog),element=scene.elements[0],place=element.assemblyPlacement;
 const input=reverse?{x:0,y:104.5,z:62.5}:{x:121,y:4.5,z:135},output=reverse?{x:121,y:4.5,z:135}:{x:0,y:104.5,z:62.5},si=A.localToWorldPoint(input,place),so=A.localToWorldPoint(output,place);
 const source={id:'source',name:'Synthetic test source, not a new catalog laser',center:{x:si.x,y:si.y},axisHeightMm:si.z,optics:{elementType:'source',source:{enabled:true,wavelengthNm:308.366,powerMw:10,beamDiameterMm:1.264,beamQualityM2:1.071,polarizationType:'elliptical',polarizationAngleDeg:23,ellipticityDeg:11,directionAngleDeg:rotationDeg+(reverse?-90:180)}}};
 const receiver={id:'receiver',name:'Known-height synthetic receiver',center:{x:so.x,y:so.y},axisHeightMm:so.z,optics:{elementType:'coupler',configured:true,inserted:true,surfaceAngleDeg:rotationDeg+(reverse?90:0),source:{directionAngleDeg:rotationDeg+(reverse?180:-90)}}};
 scene.elements.unshift(source);scene.elements.push(receiver);return{scene,layout,element,source,receiver};
}
const trace=scene=>E.autoAdvance(E.createSession(scene,undefined,{pauseOnHeightErrors:true}),{maxEvents:128,maxMilliseconds:1000});
test('catalog optical geometry is still the reviewed R2 front/back surfaces and pending material data',()=>{
 const a=kit.layout.opticalAssembly;assert.equal(a.verified,true);assert.equal(a.nodes.length,2);
 for(const [i,n]of a.nodes.entries()){near(n.faces[0].centerMm[0],0);near(n.faces[0].centerMm[1],4.5);near(n.faces[0].centerMm[2],i?62.5:135);assert.equal(n.coatingFaceIndex,null);assert.equal(n.clearApertureConfirmed,false);assert.equal(a.internalElements[i].opticalDefaults.configured,false);assert.deepEqual(a.internalElements[i].opticalDefaults.mirror.samples,[]);assert.equal(a.internalElements[i].opticalDefaults.mirror.mode,'data');}
 assert.equal(kit.designRequirements.conditionalGapMm,58);assert.equal(kit.designRequirements.actualSourceMountingDatumVerified,false);assert.equal(kit.designRequirements.actualWindowX??null,null);
});
for(const rotationDeg of[0,90,180,270])for(const baseElevationMm of[0,12.5])for(const reverse of[false,true])test(`actual two-plane geometry at ${rotationDeg} degrees, Z+${baseElevationMm}, reverse=${reverse}`,()=>{
 const f=moduleScene(rotationDeg,baseElevationMm,reverse),inputJSON=JSON.stringify(f.scene),r=trace(f.scene),s=r.session;
 assert.equal(r.done,true);assert.equal(r.blocked,false);assert.equal(JSON.stringify(f.scene),inputJSON);const c=s.completed.find(c=>c.reason==='coupled');assert.ok(c);near(c.pathMm,293.5);near(c.powerMw,10);
 const output=s.segments.find(seg=>seg.hitInstanceId==='receiver');assert.ok(output);near(output.beam.axisHeightMm,(reverse?135:62.5)+baseElevationMm);near(E.beamAt(output,1).q.re,293.5);near(output.beam.wavelengthNm,308.366);assert.ok(s.warnings.some(w=>w.code==='mirror_ideal_approximation'));
 const v=s.assemblyViews.r2;assert.deepEqual(r.events.filter(e=>e.internalId).map(e=>e.internalId),reverse?['lower-mirror','upper-mirror']:['upper-mirror','lower-mirror']);near(v.incoming['upper-mirror'][0].incidenceAngleDeg,45);near(v.incoming['lower-mirror'][0].incidenceAngleDeg,45);const vertical=s.segments.find(seg=>seg.internalAssemblySegment&&Math.abs(seg.from3D.z-seg.to3D.z)>70);assert.ok(vertical);near(vertical.lengthMm,72.5);near(vertical.direction3D.z,reverse?1:-1);assert.ok(!E.probe(s,vertical.from,.00001).some(p=>p.segmentId===vertical.id));
 return{rotationDeg,baseElevationMm,reverse,pathMm:c.pathMm,outputHeightMm:output.beam.axisHeightMm,mode:'explicit-ideal-test-copy-only'};
});
test('current 308 laser port actually reaches the R2 upper face; unknown coating stays blocked',()=>{
 const layout={board,instances:[{id:'laser',kitId:'laser-308nm',xMm:554,yMm:187.5,rotationDeg:0,optics:{elementType:'source',source:{enabled:true}}},{id:'r2',kitId:kit.id,xMm:150,yMm:250,rotationDeg:0}]};
 const scene=R.sceneFor(layout,kits,{},[],E,catalog),source=scene.elements[0];near(source.center.x,271);near(source.center.y,254.5);near(source.axisHeightMm,135);const s=E.createSession(scene),p=s.pending[0];assert.equal(p.internalId,'upper-mirror');near(p.pathMm,121);const issue=E.pendingIssue(s,p);assert.equal(issue.code,'optics_unconfigured');assert.equal(trace(scene).blocked,true);assert.equal(E.advancePending(s,p.id).segments.length,s.segments.length);return{code:issue.code,sourceReferencePoint:[source.center.x,source.center.y,source.axisHeightMm],note:'Reference exterior start, not a newly measured output-window depth'};
});
test('missing selected coated face, missing coefficients and unknown coherent phase remain distinct blocks',()=>{
 const sample={wavelengthNm:308.366,incidenceAngleDeg:45,reflectanceP:.9,reflectanceS:.9,phaseDifferenceDeg:null};
 for(const [change,expected]of [[o=>o.coatingFaceIndex=null,'assembly_coating_face_missing'],[o=>o.mirror={mode:'data',samples:[]},'mirror_sample_mismatch'],[o=>o.mirror={mode:'data',samples:[sample]},'mirror_data_missing']]){
  const f=moduleScene();change(f.element.internalOptics['upper-mirror']);const r=trace(f.scene);assert.equal(r.blocked,true);assert.equal(r.issues[0].code,expected);assert.equal(r.session.completed.length,0);assert.equal(r.events.length,0);
 }
});
test('wrong height and lateral position outside the real aperture escape instead of inventing a central hit',()=>{
 for(const change of [f=>f.source.axisHeightMm=160,f=>f.source.center.y+=30]){
  const f=moduleScene();change(f);const s=trace(f.scene).session;assert.equal(s.pending.length,0);assert.equal(s.completed.length,1);assert.equal(s.completed[0].reason,'escaped');assert.equal(s.assemblyViews.r2.segments.length,0);
 }
});
test('selecting the back physical face changes the real outgoing position, not just a label',()=>{
 const f=moduleScene();f.element.internalOptics['upper-mirror'].coatingFaceIndex=1;f.receiver.optics.clearApertureMm=1;
 const s=trace(f.scene).session,vertical=s.segments.find(seg=>seg.internalAssemblySegment&&Math.abs(seg.from3D.z-seg.to3D.z)>70);
 near(vertical.from3D.x,400-6*Math.SQRT2);near(vertical.from3D.z,135);assert.ok(!s.completed.some(c=>c.reason==='coupled'));assert.ok(s.completed.some(c=>c.reason==='escaped'));
});
test('62.5 mm output cannot silently couple into the still-unmigrated 63.5 mm receiver',()=>{
 const f=moduleScene();f.receiver.axisHeightMm=63.5;const r=trace(f.scene);assert.equal(r.blocked,true);assert.equal(r.issues[0].code,'height_mismatch');assert.equal(r.issues[0].instanceId,'receiver');assert.ok(!r.session.completed.some(c=>c.reason==='coupled'));
});
test('migrated 62.5 mm catalog waveplate accepts the verified lower port',()=>{
 const f=moduleScene(),wave=kits.get('waveplate');assert.equal(wave.layout.opticalAxisHeightMm,62.5);
 const ordinary=R.sceneFor({board,instances:[{id:'existing-waveplate',kitId:wave.id,xMm:400,yMm:454.5,rotationDeg:0,optics:{elementType:'waveplate',configured:true,inserted:false}}]},kits,{},[],E,catalog).elements[0];
 f.scene.elements=f.scene.elements.filter(e=>e.id!=='receiver');f.scene.elements.push(ordinary);const r=trace(f.scene);assert.equal(r.blocked,false);assert.ok(!r.issues.some(i=>i.code==='height_mismatch'));assert.equal(wave.layout.opticalAxisHeightMm,62.5);
});
test('synthetic exact-angle coefficients attenuate twice without claiming physical R2 efficiency',()=>{
 const sample={wavelengthNm:308.366,incidenceAngleDeg:45,reflectanceP:.9,reflectanceS:.9,phaseDifferenceDeg:180},o={...ideal,mirror:{mode:'data',model:'SYNTHETIC-TEST-NOT-A-PRODUCT',samples:[sample]}};
 const f=moduleScene(0,0,false,o),r=trace(f.scene);assert.equal(r.done,true);near(r.session.completed.find(c=>c.reason==='coupled').powerMw,8.1);assert.ok(!r.session.warnings.some(w=>w.code==='mirror_ideal_approximation'));
 return{mode:'synthetic-test-only',inputPowerMw:10,outputPowerMw:8.1,physicalEfficiencyConfirmed:false};
});
test('actual 308 source report reaches the synthetic 62.5 mm receiver in the explicitly ideal test copy',()=>{
 const layout={board,instances:[{id:'laser',kitId:'laser-308nm',xMm:554,yMm:187.5,rotationDeg:0,optics:{elementType:'source',source:{enabled:true}}},{id:'r2',kitId:kit.id,xMm:150,yMm:250,rotationDeg:0,internalOptics:{'upper-mirror':clone(ideal),'lower-mirror':clone(ideal)}}]};
 const scene=R.sceneFor(layout,kits,{},[],E,catalog),source=scene.elements[0];scene.elements.push({id:'receiver',name:'synthetic receiver',center:{x:150,y:354.5},axisHeightMm:62.5,optics:{elementType:'coupler',configured:true,inserted:true,surfaceAngleDeg:0,source:{directionAngleDeg:-90}}});
 const s=trace(scene).session,c=s.completed.find(c=>c.reason==='coupled'),out=s.segments.find(s=>s.hitInstanceId==='receiver');assert.ok(c);near(c.pathMm,293.5);near(c.powerMw,source.optics.source.powerMw);near(out.beam.wavelengthNm,source.optics.source.wavelengthNm);near(out.beam.beamQualityM2,source.optics.source.beamQualityM2);near(out.beam.axisHeightMm,62.5);
 return{inputHeightMm:135,outputHeightMm:62.5,wavelengthNm:source.optics.source.wavelengthNm,powerMw:source.optics.source.powerMw,pathMm:c.pathMm,mode:'explicit-ideal-test-copy-only'};
});
test('both R2 mirrors have separate selectable side-view faces at actual X/Z coordinates',()=>{
 const f=moduleScene(),s=trace(f.scene).session,assembly=kit.layout.opticalAssembly,svg=Side.sideSvg(assembly,s.assemblyViews.r2,R),markers=Side.interactiveElements(assembly);
 assert.deepEqual(markers.map(m=>m.id),['upper-mirror','lower-mirror']);for(const m of markers){assert.match(svg,new RegExp('data-objective-internal="'+m.id+'"'));assert.equal(m.candidateFaces.length,2);for(const face of m.candidateFaces){const real=assembly.nodes.find(n=>n.id===m.id).faces[face.index];near(face.sidePointMm.xMm,real.centerMm[0]-assembly.sideView.xMin);near(face.sidePointMm.yMm,real.centerMm[2]-assembly.sideView.zMin);}}
 assert.match(svg,/复合器件侧视图/);assert.match(svg,/objective-side-depth/);assert.match(svg,/投影长度为零/);
});
test('internal face settings and independent mirror purchases persist through project serialization and shared copy',()=>{
 const layout=moduleScene().layout,optical=Object.fromEntries(kit.opticalSlots.map((slot,i)=>['r2::'+slot.id,{model:'TEST-ONLY-'+i,name:slot.label,inserted:true,quantity:1,wavelength:'308.366',kind:'standard'}]));
 const saved=Project.create({metadata:{name:'R2 optical test — synthetic mirrors'},layout,optical,extras:[],moduleQuantities:[],ui:{selectedIds:['r2'],view:null}},{catalog}),restored=Project.parse(JSON.stringify(saved),{catalog}).project;
 assert.deepEqual(restored.layout.instances[0].internalOptics,layout.instances[0].internalOptics);assert.deepEqual(restored.optical,optical);
 const shared=require('../static/shared-project.js').subset(restored,['r2'],{catalog});shared.layout.instances[0].internalOptics['upper-mirror'].coatingFaceIndex=1;assert.equal(restored.layout.instances[0].internalOptics['upper-mirror'].coatingFaceIndex,0);assert.deepEqual(restored.optical,optical);
});
test('actual properties flow edits one R2 mirror, keeping the other slot and stored face intact',()=>{
 const vm=require('node:vm'),source=fs.readFileSync(require.resolve('./test_optical_properties.cjs'),'utf8'),sandbox={require,console};vm.createContext(sandbox);vm.runInContext(source.slice(0,source.indexOf('const row=(type,model)')).replace('return{e,n:id=>nodes.get(id),make,nodes};','return{e,n:id=>nodes.get(id),make,nodes,context};')+'\nglobalThis.makeForm=formFixture;',sandbox);
 const f=sandbox.makeForm(),e=f.e;vm.runInContext(fs.readFileSync(require.resolve('../static/objective-sideview.js'),'utf8'),f.context);
 for(const id of ['optical-dialog-title','optical-dialog-note','optical-dialog-empty'])f.make(id);
 e.instances=clone(moduleScene().layout.instances);e.kits=kits;e.catalog=catalog;e.snapshot=()=>({instances:clone(e.instances),board});e.rows=kit.opticalSlots.map((slot,i)=>({slotId:slot.id,type:'mirror',label:slot.label,name:slot.label,model:'',inserted:true,quantity:1,kind:'standard'}));e.opticalPurchaseRows=()=>e.rows;e.opticalPurchases=()=>Object.fromEntries(e.rows.map(r=>['r2::'+r.slotId,r]));e.historySnapshot=()=>clone({instances:e.instances,rows:e.rows});e.saveOpticalPurchases=(id,rows)=>{assert.equal(id,'r2');e.rows=clone(rows)};e.commit=()=>{};e.renderOptics=()=>{};
 e.openOpticalProperties('r2::upper-mirror');assert.equal(e._opticalTarget.purchaseRows[0].slotId,'upper-mirror-optic');assert.equal(e._opticalTarget.internalParentId,'r2');assert.match(f.n('optical-dialog-fields').innerHTML,/源模型镜片机械外径：Ø25.4 mm/);f.n('optics-coating-face').value='1';e.saveOpticalForm();assert.equal(e.instances[0].internalOptics['upper-mirror'].coatingFaceIndex,1);assert.equal(e.instances[0].internalOptics['lower-mirror'].coatingFaceIndex,0);assert.equal(e.rows.length,2);assert.equal(e.rows[1].slotId,'lower-mirror-optic');assert.equal(e.instances[0].optics,undefined);
 e.openOpticalProperties('r2::lower-mirror');assert.equal(e._opticalTarget.purchaseRows[0].slotId,'lower-mirror-optic');assert.equal(f.n('optics-coating-face').value,'0');
});
console.log(`${checks} periscope checks passed`);
if(process.env.PERISCOPE308_REPORT)fs.writeFileSync(process.env.PERISCOPE308_REPORT,JSON.stringify({kitId:kit.id,checks,catalogInput:process.env.PERISCOPE308_CATALOG||path.join(__dirname,'../catalog.json'),catalogInputSha256:require('node:crypto').createHash('sha256').update(fs.readFileSync(process.env.PERISCOPE308_CATALOG||path.join(__dirname,'../catalog.json'))).digest('hex'),usesFallbackGeometryFixture:!baseline.kits.some(k=>k.id===kit.id),physicalMirrorEfficiencyConfirmed:false,prototypeGapMm:58,actualSourceMountingDatumVerified:false,limitations:['Geometry tests use explicit ideal mirrors or synthetic coefficients only in in-memory copies; no catalog reflectance or phase is fabricated.','Default catalog settings correctly stop at unknown actual coated face and optical coefficients.','Clear aperture, installed optical product and actual 58 mm laser datum still require physical confirmation.','A ray outside the real optical aperture escapes; successful completion alone is not a successful coupling.','Existing ordinary 63.5 mm kit geometry remains unchanged and fails the 62.5 mm optical-height test.'],results},null,2)+'\n');
