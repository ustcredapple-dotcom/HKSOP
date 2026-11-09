'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const R=require('../static/optical-renderer.js'),E=require('../static/optical-engine.js'),catalog=require('../catalog.json');
const kits=catalog.kits.filter(k=>k.id.startsWith('objective-post-')&&k.id.endsWith('-r2'));
assert.equal(kits.length,4);
class Editor {bind(){}}
const ctx={BreadboardEditor:Editor,ZZLabOpticalEngine:E,document:{getElementById(){return null},addEventListener(){}},console};ctx.window=ctx;
vm.createContext(ctx);vm.runInContext(fs.readFileSync(require.resolve('../static/optical-renderer.js'),'utf8'),ctx);
for(const kit of kits){
  const s=kit.objectiveSpecification;
  assert.equal(s.focalLengthMm,10);assert.equal(s.workingDistanceMm,20);assert.equal(s.tubeLensFocalLengthMm,200);
  assert.equal(s.numericalAperture,.4);assert.equal(s.magnification,20);assert.equal(s.physicalOrderNumber,null);
  assert.equal(s.nominalRearThreadEndToFocusMm,s.rearThreadProjectionMm+s.parfocalDistanceMm);
  assert.equal(s.nominalRearThreadEndToFocusMm,s.rearThreadProjectionMm+s.frontFaceFromShoulderMm+s.workingDistanceMm);
  const instance={id:'existing',kitId:kit.id,xMm:125,yMm:250,rotationDeg:90};const before=JSON.stringify(instance);
  const config=R.configFor(instance,kit,{},E,catalog);
  assert.equal(config.elementType,'unsupported');assert.equal(kit.layout.opticalDatumVerified,false);
  assert.equal(JSON.stringify(instance),before);
  const editor=new Editor();editor.catalog=catalog;editor._opticalTarget={kit,config,purchaseRows:[],simulationIssue:R.catalogSimulationIssue(kit)};
  const html=editor.opticalFormMarkup(config);
  assert.match(html,/物镜官方参数/);assert.match(html,/>10 mm</);assert.match(html,/>20 mm</);assert.match(html,/>200 mm</);
  assert.match(html,/查看厂家参数/);assert.doesNotMatch(html,/id="optics-focal"/);
  assert.match(html,/装配通光口径和内部传播模型尚未核实/);
}
for(const kit of catalog.kits.filter(k=>!kits.includes(k)))assert.equal(R.objectiveSpecificationMarkup(kit),'');
const forged={objectiveSpecification:{...kits[0].objectiveSpecification,model:'<img src=x onerror=alert(1)>',sourceUrl:'javascript:alert(1)'}};
const markup=R.objectiveSpecificationMarkup(forged);assert.doesNotMatch(markup,/<img|href="javascript:/);assert.match(markup,/&lt;img/);
console.log('PASS: four official specification cards, 10/20/200 mm distinction, unchanged instances, unknown optics retained, other kits unchanged, escaped display.');
