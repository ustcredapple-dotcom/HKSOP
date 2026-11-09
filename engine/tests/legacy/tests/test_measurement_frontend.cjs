'use strict';
// Exercise the shipped editor, renderer and measurement extension together.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const performance=fs.readFileSync(path.join(root,'test_layout_performance_frontend.cjs'),'utf8');
const harness={require,__dirname:root,console};
vm.createContext(harness);
vm.runInContext(performance.slice(0,performance.indexOf('{\n  const f=fixture(),e=f.editor'))+'\nglobalThis.createFixture=fixture;',harness);
const source=['layout.js','stacked-boards.js','measurement.js','optical-hole-probe.js'].map(file=>fs.readFileSync(path.join(root,'static',file),'utf8')).join('\n');
const math=require('../static/measurement.js'),copy=x=>JSON.parse(JSON.stringify(x));
const same=(a,b,message)=>assert.deepEqual(copy(a),copy(b),message);
const centered={xMin:-5,yMin:-5,xMax:5,yMax:5};
const board=(widthMm=600,heightMm=400)=>({widthMm,heightMm,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]});
const part=(id,xMm,yMm,boardId,rotationDeg=0)=>({id,kitId:'kit',xMm,yMm,rotationDeg,...(boardId?{boardId}:{})});
let checks=0;
function test(name,fn){fn();checks++;console.log('PASS '+name)}

function fixture(count=3){
  const f=harness.createFixture(count,source),e=f.editor,E=e.svg.constructor;
  // The existing counted DOM omits these SVG APIs; production uses real nodes.
  Object.defineProperty(E.prototype,'firstChild',{get(){return this.children[0]||null}});
  E.prototype.removeChild=function(child){const n=this.children.indexOf(child);assert.notEqual(n,-1);this.children.splice(n,1);child.parentNode=null;return child};
  E.prototype.replaceChildren=function(...nodes){while(this.firstChild)this.removeChild(this.firstChild);nodes.forEach(child=>this.appendChild(child))};
  E.prototype.insertBefore=function(child,before){if(child.parentNode)child.parentNode.removeChild(child);child.parentNode=this;const n=this.children.indexOf(before);this.children.splice(n<0?this.children.length:n,0,child);return child};
  const originalSetAttribute=E.prototype.setAttribute;
  E.prototype.setAttribute=function(name,value){originalSetAttribute.call(this,name,value);if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=String(value)};
  const originalClosest=E.prototype.closest;
  E.prototype.closest=function(selector){const match=selector.match(/^\[data-([a-z-]+)\]$/);if(match){const key=match[1].replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());return this.dataset[key]!=null?this:this.parentNode?.closest(selector)||null}return originalClosest.call(this,selector)};
  E.prototype.querySelectorAll=function(selector){
    const match=selector.match(/^\[(data-[a-z-]+)\]$/);if(!match)return [];
    const attribute=match[1],key=attribute.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase()),found=[];
    const visit=parent=>{
      for(const child of parent.children){if(child.dataset[key]!=null)found.push(child);visit(child)}
      if(parent._queryMarkup?.text!==parent._html){
        const nodes=(parent._html.match(/<g [^>]+>/g)||[]).map(tag=>{const item=new E('g');item.parentNode=parent;for(const [,name,value]of tag.matchAll(/(data-[a-z-]+)="([^" ]*)"/g))item.setAttribute(name,value);return item});
        parent._queryMarkup={text:parent._html,nodes};
      }
      for(const item of parent._queryMarkup.nodes)if(item.dataset[key]!=null)found.push(item);
    };visit(this);return found;
  };
  const html=Object.getOwnPropertyDescriptor(E.prototype,'innerHTML');
  Object.defineProperty(E.prototype,'innerHTML',{get:html.get,set(value){for(const child of this.children)child.parentNode=null;html.set.call(this,value)}});
  const d=f.document;
  d.getElementById('mounting-count').value='4';d.getElementById('mounting-row-parity').value='any';d.getElementById('mounting-column-parity').value='any';
  e.notify=message=>{e.notice=message};e.sceneWorld=event=>({xMm:event.clientX,yMm:e.snapshot().board.heightMm-event.clientY});return{...f,e};
}
function contextPart(e,id){const node=e.svg.querySelectorAll('[data-instance]').find(n=>n.dataset.instance===id);assert.ok(node,'instance '+id+' is visible in the shared board canvas');return node}
const pointer=(target,extra={})=>({type:'pointerdown',target,button:0,pointerId:1,clientX:25,clientY:375,preventDefault(){this.prevented=true},...extra});
function stackedFixture(){
  const f=fixture(0),e=f.e;
  e.loadLayout({board:board(),subBoards:[
    {id:'a',name:'左模块',board:board(200,150),xMm:200,yMm:100,rotationDeg:90},
    {id:'b',name:'右模块',board:board(200,150),xMm:400,yMm:200,rotationDeg:270}
  ],instances:[part('a1',50,25,'a',90),part('a2',100,75,'a',270),part('b1',50,25,'b'),part('main',275,175)]},'a');
  e.bindStacked();e.render();return f;
}

test('base datum transforms through asymmetric component and child rotations',()=>{
  const bounds={xMin:-1,yMin:1,xMax:7,yMax:7}; // local centre (3,4), unlike the anchor or image centre
  const layout={subBoards:[{id:'a',xMm:200,yMm:100,rotationDeg:90}]};
  same(math.center(part('i',50,25,'a',90),layout,bounds),{xMm:172,yMm:146});
  same(math.center(part('i',50,25,undefined,90),layout,bounds),{xMm:46,yMm:28});
  same(math.localPoint({xMm:172,yMm:146},layout.subBoards[0]),{xMm:46,yMm:28});
  for(const angle of [0,90,180,270]){
    const plate={id:'a',xMm:-12.5,yMm:237.5,rotationDeg:angle};
    const original={xMm:62.5,yMm:112.5};
    const world=math.center(part('i',original.xMm,original.yMm,'a'),{subBoards:[plate]},centered);
    same(math.localPoint(world,plate),original,'world/local round-trip at '+angle+' degrees');
  }
});
test('root and different child boards use common large-board X and Y axes',()=>{
  const layout={subBoards:[{id:'a',xMm:200,yMm:100,rotationDeg:90},{id:'b',xMm:400,yMm:200,rotationDeg:270}]};
  const a=math.center(part('a',50,25,'a'),layout,centered),b=math.center(part('b',50,25,'b'),layout,centered),rootPoint=math.center(part('r',275,175),layout,centered);
  same(a,{xMm:175,yMm:150});same(b,{xMm:425,yMm:150});
  same(math.distance(a,b),{dxMm:250,dyMm:0,xMm:250,yMm:0});
  same(math.distance(a,rootPoint),{dxMm:100,dyMm:25,xMm:100,yMm:25});
});
test('distance preserves signed directions but reports nonnegative distances including zero',()=>{
  const a={xMm:12.5,yMm:75},b={xMm:12.5,yMm:25};
  same(math.distance(a,b),{dxMm:0,dyMm:-50,xMm:0,yMm:50});
  same(math.distance(b,a),{dxMm:0,dyMm:50,xMm:0,yMm:50});
  same(math.distance(a,a),{dxMm:0,dyMm:0,xMm:0,yMm:0});
  same(math.center(part('no-metadata',25,37.5),{},undefined),{xMm:25,yMm:37.5});
});
test('measurement activation, selection and reset never mutate project or history',()=>{
  const {e,document:d,counts}=fixture(),before=copy(e.snapshot()),history=copy(e.history),changes=counts().changes;
  e.setSelection(['p2']);const selection=[...e.selectedIds];
  d.getElementById('layout-measure').handlers.click();assert.ok(e.measurement);
  e.pickMeasurement('p0');e.pickMeasurement('p1');
  const result=e.measurementResult();assert.equal(result.xMm,25);assert.equal(result.yMm,0);
  assert.equal(d.getElementById('measurement-x').textContent,'25 mm');assert.equal(d.getElementById('measurement-y').textContent,'0 mm');
  d.getElementById('measurement-reset').handlers.click();same(e.measurement.ids,[]);
  d.getElementById('layout-measure').handlers.click();assert.equal(e.measurement,null);
  same(e.snapshot(),before);same(e.history,history);same([...e.selectedIds],selection);assert.equal(counts().changes,changes);
});
test('measurement exposes a single toolbar and overlay on the normal board canvas',()=>{
  const {e,document:d}=fixture();e.setMeasurementMode(true);e.pickMeasurement('p0');
  assert.equal(d.getElementById('stack-measure').handlers.click,undefined);assert.equal(d.getElementById('stack-measurement-reset').handlers.click,undefined);
  assert.equal(e._measureLayer.parentNode,e.svg);assert.equal(e._measureLocalLayer,undefined);assert.equal(e._measureStackLayer,undefined);
});
test('production pointer handlers choose endpoints without initiating component drag',()=>{
  const {e,counts}=fixture(),before=copy(e.snapshot()),history=e.history.length,changes=counts().changes,h=e.svg.handlers;
  e.setMeasurementMode(true);
  for(const id of ['p0','p1']){
    const event=pointer(e._scene.partNodes.get(id).image);
    h.pointerdown(event);assert.equal(event.prevented,true);assert.equal(e.drag,null);
    h.pointermove({...event,type:'pointermove',clientX:200,clientY:200});h.pointerup({...event,type:'pointerup',clientX:200,clientY:200});e.measureDoubleClick(pointer(event.target));
  }
  same(e.measurement.ids,['p0','p1']);same(e.snapshot(),before);assert.equal(e.history.length,history);assert.equal(counts().changes,changes);
});
test('same A cannot become B, unknown IDs are ignored and a third pick starts a new pair',()=>{
  const {e}=fixture();e.setMeasurementMode(true);
  assert.equal(e.pickMeasurement('missing'),false);assert.equal(e.pickMeasurement('p0'),true);
  assert.equal(e.pickMeasurement('p0'),false);same(e.measurement.ids,['p0']);assert.match(e.notice,/另一个/);
  assert.equal(e.pickMeasurement('p1'),true);same(e.measurement.ids,['p0','p1']);
  assert.equal(e.pickMeasurement('p2'),true);same(e.measurement.ids,['p2']);assert.equal(e.measurementResult().xMm,undefined);
});
test('removing endpoints and loading another project prunes stale IDs and values',()=>{
  const {e,document:d}=fixture();e.setMeasurementMode(true);e.pickMeasurement('p0');e.pickMeasurement('p1');
  e.removeIds(['p1']);same(e.measurement.ids,['p0']);assert.equal(d.getElementById('measurement-values').hidden,true);
  e.loadLayout({board:board(),instances:[part('replacement',100,100)]});e.render();
  same(e.measurement.ids,[]);assert.equal(e.measurementResult().points.length,0);assert.equal(d.getElementById('measurement-x').textContent,'—');
});
test('measurement, manual holes and placement are mutually exclusive without modifying saved holes',()=>{
  const {e}=fixture(),before=copy(e.snapshot());e.beginManualMounting();assert.ok(e.manualMounting);
  e.manualMounting.holes=[{columnIndex:0,rowIndex:0}];e.setMeasurementMode(true);assert.equal(e.manualMounting,null);assert.ok(e.measurement);
  e.beginManualMounting();assert.equal(e.measurement,null);assert.ok(e.manualMounting);
  e.setMeasurementMode(true);e.beginPlace('kit');assert.equal(e.measurement,null);assert.equal(e.pendingKitId,'kit');
  e.setMeasurementMode(true);assert.equal(e.pendingKitId,null);same(e.snapshot(),before);
});
test('zoom and blank-canvas pan retain images and leave the measured geometry unchanged',()=>{
  const f=fixture(),{e}=f;e.setMeasurementMode(true);e.pickMeasurement('p0');e.pickMeasurement('p1');
  const before=copy(e.snapshot()),images=e.instances.map(i=>e._scene.partNodes.get(i.id).image),imageCreates=f.metrics.imageCreates,replacements=f.metrics.svgReplacements,runs=e.renderStats.validationRuns;
  for(let n=0;n<20;n++){e.zoom(n%2?1/1.1:1.1);e.view.x+=2;e.renderView()}
  const h=e.svg.handlers;h.pointerdown(pointer(e.svg,{clientX:0,clientY:0}));assert.equal(e.drag.mode,'pan');h.pointermove(pointer(e.svg,{type:'pointermove',clientX:50,clientY:25}));h.pointerup(pointer(e.svg,{type:'pointerup',clientX:50,clientY:25}));
  same(e.snapshot(),before);assert.equal(e.measurementResult().xMm,25);assert.equal(e.measurementResult().yMm,0);
  assert.equal(f.metrics.imageCreates,imageCreates);assert.equal(f.metrics.svgReplacements,replacements);assert.equal(e.renderStats.validationRuns,runs);
  images.forEach((image,n)=>assert.equal(e._scene.partNodes.get(e.instances[n].id).image,image));
});
test('measurement keyboard prevents movement/deletion and Escape restores normal mode',()=>{
  const {e}=fixture();e.setSelection(['p0']);e.svg.focus();e.setMeasurementMode(true);const before=copy(e.snapshot());
  for(const key of ['Delete','Backspace','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','r'])e.handleKeydown({key,target:e.svg,preventDefault(){}});
  same(e.snapshot(),before);e.handleKeydown({key:'Escape',target:e.svg,preventDefault(){}});assert.equal(e.measurement,null);
  e.handleKeydown({key:'ArrowRight',target:e.svg,preventDefault(){}});assert.equal(e.instances[0].xMm,before.instances[0].xMm+e.board.pitchMm);
});
test('rotated-board endpoints render in the shared large-board coordinate system',()=>{
  const {e,document:d}=stackedFixture();e.setMeasurementMode(true);e.pickMeasurement('a1');e.pickMeasurement('a2');
  const r=e.measurementResult();same(r.points.map(p=>({xMm:p.xMm,yMm:p.yMm})),[{xMm:175,yMm:150},{xMm:125,yMm:200}]);assert.equal(r.xMm,50);assert.equal(r.yMm,50);
  const path=e._measureLayer.children.find(n=>n.tagName==='path'&&n.getAttribute('class')==='measurement-lines');
  assert.equal(path.getAttribute('d'),'M175 250L125 250L125 200','measurement overlay shares the large board global axes');
  assert.equal(e._measureLayer.parentNode,e.svg);
  assert.match(d.getElementById('measurement-basis').textContent,/大面包板/);
  assert.match(d.getElementById('measurement-direction').textContent,/向左 50 mm；向上 50 mm/);
});
test('one-canvas pointer selection spans child boards without moving or switching a plate',()=>{
  const f=stackedFixture(),{e}=f;e.setMeasurementMode(true);const before=copy(e.snapshot()),history=e.history.length,active=e.activeBoardId;
  const targets=[e._scene.partNodes.get('a1').image,contextPart(e,'b1')];
  for(const target of targets){
    const event=pointer(target);e.svg.handlers.pointerdown(event);assert.equal(event.prevented,true);assert.equal(e.drag,null);assert.equal(e.stackDrag,undefined);e.measureDoubleClick(event);
  }
  same(e.measurement.ids,['a1','b1']);assert.equal(e.measurementResult().xMm,250);assert.equal(e.measurementResult().yMm,0);
  same(e.snapshot(),before);assert.equal(e.activeBoardId,active);assert.equal(e.history.length,history);
  assert.equal(e._measureLayer.children.filter(n=>n.tagName==='circle').length,2,'both endpoints appear in the only canvas');
  assert.equal(e._measureLayer.parentNode,e.svg);
  e.setMeasurementMode(false);assert.equal(e._measureLayer.getAttribute('display'),'none');
});
test('large-board and child endpoints can be selected in the same canvas',()=>{
  const {e}=stackedFixture();e.setMeasurementMode(true);
  for(const target of [e._scene.partNodes.get('a1').image,contextPart(e,'main')]){e.svg.handlers.pointerdown(pointer(target));e.measureDoubleClick(pointer(target))}
  same(e.measurement.ids,['a1','main']);same({x:e.measurementResult().xMm,y:e.measurementResult().yMm},{x:100,y:25});
  const line=e._measureLayer.children.find(n=>n.getAttribute('class')==='measurement-lines');
  assert.equal(line.getAttribute('d'),'M175 250L275 250L275 225');
});
test('changing editing target retains the shared measurement overlay and global endpoints',()=>{
  const {e}=stackedFixture();e.setMeasurementMode(true);e.pickMeasurement('a1');e.pickMeasurement('b1');
  const layer=e._measureLayer,coordinates=copy(e.measurementResult().points),line=layer.children.find(n=>n.getAttribute('class')==='measurement-lines').getAttribute('d');
  assert.equal(e.switchBoard('b'),true);same(e.measurement.ids,['a1','b1']);assert.equal(e.measurementResult().xMm,250);
  assert.equal(e._measureLayer,layer);assert.equal(layer.parentNode,e.svg);same(e.measurementResult().points,coordinates);
  assert.equal(layer.children.find(n=>n.getAttribute('class')==='measurement-lines').getAttribute('d'),line);
});
test('zoom preserves unified-canvas module images and global measurement distances',()=>{
  const f=stackedFixture(),{e}=f;e.setMeasurementMode(true);e.pickMeasurement('a1');e.pickMeasurement('b1');
  const before=copy(e.snapshot()),image=e._scene.partNodes.get('a1').image,context=contextPart(e,'b1'),creates=f.metrics.imageCreates,replacements=f.metrics.svgReplacements,layer=e._measureLayer;
  for(let n=0;n<10;n++){e.zoom(n%2?1/1.1:1.1);e.view.x+=2;e.renderView()}
  same(e.snapshot(),before);assert.equal(e.measurementResult().xMm,250);assert.equal(e.measurementResult().yMm,0);assert.equal(e._measureLayer,layer);
  assert.equal(e._scene.partNodes.get('a1').image,image);assert.equal(contextPart(e,'b1'),context);assert.equal(f.metrics.imageCreates,creates);assert.equal(f.metrics.svgReplacements,replacements);
});
test('removing a module prunes its endpoint without replacing the shared measurement layer',()=>{
  const {e,document:d}=stackedFixture();e.setMeasurementMode(true);e.pickMeasurement('a1');e.pickMeasurement('b1');
  assert.equal(e.switchBoard('b'),true);const overlay=e._measureLayer;d.getElementById('stack-remove').handlers.click();
  same(e.measurement.ids,['a1']);assert.equal(e.measurementResult().xMm,undefined);assert.equal(e._measureLayer,overlay);assert.equal(overlay.parentNode,e.svg);
  assert.equal(overlay.children.filter(n=>n.tagName==='circle').length,1);assert.equal(d.getElementById('measurement-values').hidden,true);
});
test('keyboard activation measures an inactive-board endpoint without switching the editing target',()=>{
  const {e}=stackedFixture();e.setMeasurementMode(true);e.pickMeasurement('a1');const target=contextPart(e,'b1'),active=e.activeBoardId;
  e.handleKeydown({key:'Enter',target,preventDefault(){this.prevented=true}});
  same(e.measurement.ids,['a1','b1']);assert.equal(e.activeBoardId,active);assert.equal(e.measurementResult().xMm,250);
});


test('single clicks over components snap holes while double-click restores the prior pair before taking the centre',()=>{
  const {e}=fixture();e.setMeasurementMode(true);e.pickMeasurement('p1');
  const target=e._scene.partNodes.get('p0').image,event=pointer(target,{clientX:33,clientY:367,detail:1});
  e.measurePointer(event);assert.deepEqual([...e.measurement.ids],['p1']);
  e.completeMeasurementClick(event);let r=e.measurementResult();assert.equal(r.points[1].kind,'hole');assert.equal(r.points[1].xMm,37.5);assert.equal(r.points[1].yMm,37.5);
  e.measurePointer({...event,detail:2});e.completeMeasurementClick({...event,detail:2});e.measureDoubleClick({...event,detail:2});
  same(e.measurement.ids,['p1','p0']);r=e.measurementResult();assert.equal(r.xMm,25);assert.equal(r.yMm,0);
});
test('blank clicks select real holes without a rendered optical path and preserve ordinary pan',()=>{
  const {e,document:d}=fixture();e.setMeasurementMode(true);const before=copy(e.snapshot());
  for(const [x,y]of[[33,367],[80,318]]){const event=pointer(e.svg,{clientX:x,clientY:y,detail:1});e.svg.handlers.pointerdown(event);e.svg.handlers.pointerup({...event,type:'pointerup'});e.completeMeasurementClick(event)}
  const r=e.measurementResult();assert.equal(r.points.length,2);assert.ok(r.points.every(p=>p.kind==='hole'));assert.equal(r.xMm,37.5);assert.equal(r.yMm,50);assert.match(d.getElementById('measurement-points').textContent,/螺孔.*X 37.5/);same(e.snapshot(),before);
  const ids=[...e.measurement.ids],event=pointer(e.svg,{clientX:0,clientY:0});e.svg.handlers.pointerdown(event);e.svg.handlers.pointermove({...event,clientX:60,clientY:30});e.svg.handlers.pointerup({...event,type:'pointerup',clientX:60,clientY:30});e.completeMeasurementClick({...event,clientX:60,clientY:30});same(e.measurement.ids,ids);
});
test('hole endpoints follow rotated modules and disappear when the hole becomes a counterbore',()=>{
  const {e}=stackedFixture();e.setMeasurementMode(true);e.pickMeasurementAt({x:187.5,y:112.5});let r=e.measurementResult();assert.equal(r.points[0].boardId,'a');assert.equal(r.points[0].kind,'hole');
  e.pickMeasurement('main');assert.equal(e.measurementResult().points.length,2);
  const layout=e.snapshot(),plate=layout.subBoards.find(p=>p.id==='a');plate.xMm+=25;e.snapshot=()=>layout;
  r=e.measurementResult();assert.equal(r.points[0].xMm,212.5);plate.board.mountingHoles.push({columnIndex:0,rowIndex:0});r=e.measurementResult();assert.equal(r.points.length,1);assert.equal(r.points[0].id,'main');
});
test('right click opens existing mechanical and optical property menu without changing A/B',()=>{
  const {e,document:d}=fixture();e.setMeasurementMode(true);e.pickMeasurement('p0');const before=copy(e.measurement);
  const event=pointer(e._scene.partNodes.get('p0').image,{button:2,clientX:120,clientY:130});assert.equal(e.measureContextMenu(event),true);
  assert.equal(d.getElementById('component-context-menu').hidden,false);assert.equal(e._menuInstanceId,'p0');same(e.measurement,before);assert.equal(event.prevented,true);
});


test('table A/B measurements distinguish reference grid from physical subboard holes',()=>{
  const {e,document:d}=stackedFixture(),layout=e.snapshot();layout.baseMode='table';layout.board.holeType='plain_through';layout.board.mountingHoles=[{columnIndex:0,rowIndex:0}];e.snapshot=()=>copy(layout);
  e.setMeasurementMode(true);e.pickMeasurementAt({x:12.5,y:12.5});e.pickMeasurementAt({x:187.5,y:112.5});const r=e.measurementResult();
  assert.equal(r.points[0].kind,'reference-grid');assert.match(r.points[0].name,/桌面参考格点/);assert.doesNotMatch(r.points[0].name,/螺孔/);assert.equal(r.points[1].kind,'hole');assert.match(r.points[1].name,/左模块.*螺孔/);assert.equal(r.xMm,175);assert.equal(r.yMm,100);assert.match(d.getElementById('measurement-basis').textContent,/按桌面 X \/ Y 方向/);
  layout.baseMode='breadboard';e.renderMeasurement();assert.equal(e.measurementResult().points.length,1,'plain physical root no longer presents reference points');
});
console.log(`${checks} measurement frontend checks passed`);
