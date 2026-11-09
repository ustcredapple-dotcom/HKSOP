'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const root = path.resolve(__dirname, '..'), catalog = require('../catalog.json');
const E = require('../static/optical-engine.js'), R = require('../static/optical-renderer.js'), codec = require('../static/project-file.js');
const kits = new Map(catalog.kits.map(k => [k.id, k]));
const copy = x => JSON.parse(JSON.stringify(x));
const near = (a,b,t=1e-7) => assert.ok(Math.abs(a-b)<t, `${a} != ${b}`);
const board = {widthMm:1600,heightMm:900,pitchMm:25,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]};
let checks=0;
const test=(name,f)=>{f();checks++;console.log('PASS '+name);};
const expected = {
  'laser-399nm': {wavelengthNm:398.90264,powerMw:1210,beamQualityM2:1.048},
  'laser-556nm': {wavelengthNm:555.80335,powerMw:1540,beamQualityM2:1.020},
  'laser-935nm': {wavelengthNm:935.18051,powerMw:223.6,beamQualityM2:1.026},
};
for (const [id,values] of Object.entries(expected)) {
  const kit=kits.get(id), pose={id:'test-'+id,kitId:id,xMm:700,yMm:450,rotationDeg:0};
  test(id+' uses its own measured source parameters and preserves explicit user overrides',()=>{
    assert.ok(kit.layout.placementAllowed); const source=R.configFor(pose,kit,{},E,catalog).source;
    for(const [field,value] of Object.entries(values)) assert.equal(source[field],value);
    assert.equal(source.polarizationType,'linear');assert.equal(source.enabled,false);
    const optics={elementType:'source',inserted:true,source:{enabled:false,powerMw:0,wavelengthNm:500,polarizationAngleDeg:31,wavefrontRadiusMm:null}};
    const changed=R.configFor({...pose,optics},kit,{},E,catalog).source;
    assert.equal(changed.powerMw,0);assert.equal(changed.wavelengthNm,500);assert.equal(changed.polarizationAngleDeg,31);assert.equal(changed.wavefrontRadiusMm,null);
    const project=codec.create({metadata:{name:id},catalogVersion:catalog.version,layout:{board,instances:[{...pose,optics}],baseMode:'table'},optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],view:null}},{catalog});
    assert.deepEqual(codec.parse(JSON.stringify(project),{catalog}).project.layout.instances[0].optics,optics);
  });
  if (id!=='laser-399nm') test(id+' emits from the registered window and rotates through all four orientations',()=>{
    for(const angle of [0,90,180,270]){
      const instance={...pose,rotationDeg:angle,optics:{elementType:'source',source:{enabled:true}}};
      const scene=R.sceneFor({board,instances:[instance]},kits,{},[],E,catalog), element=scene.elements[0];
      const port=kit.layout.opticalPortsMm[0], world=R.transform({x:port.xMm,y:port.yMm},instance);
      const session=E.createSession(scene);assert.equal(session.sourceIds.length,1);
      const beam=E.beamAt(session.segments[0],0);near(session.segments[0].from.x,world.x);near(session.segments[0].from.y,world.y);
      assert.equal(beam.powerMw,values.powerMw);assert.equal(beam.wavelengthNm,values.wavelengthNm);
      near(beam.diameterMm,kit.layout.opticalDefaults.source.beamDiameterMm);
      near(element.sourceDirectionDeg,angle+kit.layout.opticalDefaults.source.directionAngleDeg);
    }
  });
}
test('399 pending optical coordinates never produce a falsely calibrated beam, even through explicit emitters',()=>{
  const kit=kits.get('laser-399nm');assert.equal(kit.layout.opticalDatumVerified,false);assert.equal(kit.layout.opticalAxisHeightMm,null);
  const instance={id:'pending-399',kitId:kit.id,xMm:700,yMm:450,rotationDeg:0,optics:{elementType:'source',source:{enabled:true}}};
  const config=R.configFor(instance,kit,{},E,catalog);assert.equal(config.elementType,'source');assert.equal(config.source.enabled,false);
  assert.match(R.sourceReportMarkup(kit),/398.90264/);
  const scene=R.sceneFor({board,instances:[instance]},kits,{},[],E,catalog);
  const trace=E.createSession(scene,[{instanceId:instance.id}]);assert.equal(trace.segments.length,0);
  assert.ok(trace.warnings.some(w=>w.code==='optical_datum_unknown'));
});
test('556/935 derived window q reaches the report-referenced waist rather than treating it as the window',()=>{
  for(const [id,waistDistance,waistDiameter] of [['laser-556nm',156.815,.696],['laser-935nm',76.9886,.861684]]){
    const source=kits.get(id).layout.opticalDefaults.source;
    assert.ok(source.beamDiameterMm>waistDiameter);assert.ok(source.wavefrontRadiusMm<0);
    const lambda=source.wavelengthNm*1e-6,w=source.beamDiameterMm/2;
    const inverseReal=1/source.wavefrontRadiusMm,inverseImag=-source.beamQualityM2*lambda/(Math.PI*w*w);
    const denominator=inverseReal**2+inverseImag**2;
    const qReal=inverseReal/denominator,qImag=-inverseImag/denominator;
    near(-qReal,waistDistance,1e-4);
    near(2*Math.sqrt(source.beamQualityM2*lambda*qImag/Math.PI),waistDiameter,1e-5);
    assert.ok(kits.get(id).layout.sourceReport.applyFields.includes('wavefrontRadiusMm'));
  }
});
test('reported window-model reset fills wavefront only for the new explicitly registered models',()=>{
  const harness={require,__dirname:root,console};vm.createContext(harness);
  const perf=fs.readFileSync(path.join(root,'test_layout_performance_frontend.cjs'),'utf8');
  vm.runInContext(perf.slice(0,perf.indexOf('{\n  const f=fixture(),e=f.editor'))+'\nglobalThis.env=environment;',harness);
  const code=['layout.js','optical-engine.js','optical-hole-probe.js','optical-renderer.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n');
  const env=harness.env(code),node=id=>env.document.getElementById(id);
  for(const id of ['laser-556nm','laser-935nm','laser-308nm','laser-532nm']){
    const kit=kits.get(id), target={kit};node('optics-type').value='source';node('optics-wavefront').value='-600';node('optics-polarization-angle').value='17';node('optics-source-enabled').checked=false;
    env.Editor.prototype.applyReportedSourceParameters.call({_opticalTarget:target});
    assert.equal(node('optics-wavefront').value,['laser-556nm','laser-935nm'].includes(id)?String(kit.layout.opticalDefaults.source.wavefrontRadiusMm):'-600');
    assert.equal(node('optics-polarization-angle').value,'17');assert.equal(node('optics-source-enabled').checked,false);
  }
  const pending=kits.get('laser-399nm'),config=R.configFor({optics:{source:{enabled:true}}},pending,{},E,catalog);
  const markup=env.Editor.prototype.opticalFormMarkup.call({_opticalTarget:{kit:pending,simulationIssue:R.catalogSimulationIssue(pending)}},config);
  assert.match(markup,/optics-source-enabled[^>]*disabled/);assert.match(markup,/398.90264/);
});
console.log(`${checks} new laser library frontend checks passed`);
