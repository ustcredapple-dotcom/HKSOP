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


const front={id:'objective-front-center',label:'物镜前表面中心',xMm:-80,yMm:0,zMm:62.5,verified:true};
function datums(e,points=[front]){e.kits.get('kit').layout.measurementPointsMm=copy(points);e.render();}
function marker(e,id='p0',pointId=front.id){const found=e.svg.querySelectorAll('[data-measurement-point]').find(n=>n.dataset.measurementInstance===id&&n.dataset.measurementPoint===pointId);assert.ok(found,'registered datum marker is visible');return found}
function clickMarker(e,target){const event=pointer(target,{detail:1});e.svg.handlers.pointerdown(event);assert.equal(event.prevented,true);assert.equal(e.drag,null);e.svg.handlers.pointerup({...event,type:'pointerup'});assert.equal(e.svg.handlers.click(event),true);return event}
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);

test('only verified finite catalog datums render and can be selected',()=>{
  const {e}=fixture(1);datums(e,[front,{...front,id:'unverified',verified:false},{...front,id:'missing-z',zMm:undefined},{...front,id:'not-number',xMm:'-80'},{...front,id:'infinite',yMm:Infinity},{...front,id:'empty-label',label:''}]);
  // JSON cloning turns Infinity into null; both are unavailable geometry.
  e.setMeasurementMode(true);const r=e.measurementResult();assert.equal(r.targets.length,1);assert.equal(e.svg.querySelectorAll('[data-measurement-point]').length,1);
  assert.equal(e.pickMeasurementPoint('p0','unverified'),false);assert.equal(e.pickMeasurementPoint('p0','missing'),false);assert.equal(e.pickMeasurementPoint('missing',front.id),false);same(e.measurement.ids,[]);
  assert.equal(math.registeredPoints({layout:{measurementPointsMm:[front,front,{...front,id:'nan',xMm:NaN},{...front,id:'inf',zMm:Infinity}]}}).length,1);
});
test('bounded front marker single click selects datum while same-component double click remains base centre',()=>{
  const {e,document:d,counts}=fixture(1);datums(e);const before=copy(e.snapshot()),history=copy(e.history),changes=counts().changes;e.setMeasurementMode(true);
  const m=marker(e),hit=m.children.find(n=>n.tagName==='circle'&&n.getAttribute('fill')==='transparent');assert.ok(Number(hit.getAttribute('r'))>0);assert.equal(hit.getAttribute('pointer-events'),'all');assert.equal(m.children.find(n=>n.tagName==='text').getAttribute('pointer-events'),'none');assert.equal(m.closest('[data-instance]'),null,'marker is not confused with a component Enter/double-click target');assert.match(m.getAttribute('aria-label'),/物镜前表面中心/);assert.match(m.children.find(n=>n.tagName==='title').textContent,/单击选作 A \/ B/);
  clickMarker(e,hit);assert.equal(e.measurementResult().points[0].kind,'datum');assert.match(d.getElementById('measurement-points').textContent,/物镜前表面中心/);
  e.measureDoubleClick(pointer(e._scene.partNodes.get('p0').image,{detail:2}));const r=e.measurementResult();assert.equal(r.points.length,2);assert.equal(r.points[1].kind,'center');assert.match(r.points[1].name,/底座安装中心/);assert.equal(r.xMm,80);assert.equal(r.yMm,0);
  same(e.snapshot(),before);same(e.history,history);assert.equal(counts().changes,changes);
});
test('distinct named datum and base endpoints may have identical X/Y coordinates',()=>{
  const {e}=fixture(1);datums(e,[{...front,xMm:0}]);e.setMeasurementMode(true);clickMarker(e,marker(e));e.pickMeasurement('p0');const r=e.measurementResult();assert.equal(r.points.length,2);assert.notEqual(r.points[0].id,r.points[1].id);assert.equal(r.xMm,0);assert.equal(r.yMm,0);
});
test('named datums rotate through both instance and child plate in the common board axes',()=>{
  const axes={0:[1,0],90:[0,1],180:[-1,0],270:[0,-1]};
  for(const ir of [0,90,180,270])for(const pr of [0,90,180,270]){
    const [ic,is]=axes[ir],[pc,ps]=axes[pr],i=part('a',50,25,'child',ir),layout={instances:[i],subBoards:[{id:'child',name:'移动板',xMm:200,yMm:100,rotationDeg:pr}]},kits=new Map([['kit',{name:'物镜',layout:{measurementPointsMm:[front]}}]]);
    const lx=50-80*ic,ly=25-80*is,actual=math.namedPoints(layout,kits)[0];same({xMm:actual.xMm,yMm:actual.yMm},{xMm:200+pc*lx-ps*ly,yMm:100+ps*lx+pc*ly});assert.match(actual.name,/移动板.*物镜前表面中心/);
  }
});
test('front endpoint recomputes for real stage q without double-counting motion or moving the child',()=>{
  const S=require('../static/moving-stages.js'),raw=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/manual-stage-r1.json'))),modules=raw.modules.map(m=>({...m,runtime:{...m.runtime,topBoardId:'board-'+m.id,topBoardRevision:m.revision}})),catalog={stageModules:modules};
  for(const m of modules)for(const ir of [0,90,180,270])for(const pr of [0,90,180,270]){
    const {e}=fixture(0);datums(e);const child=part('child',25,25,'stage',ir),p={id:'stage',name:m.name,board:{...board(100,100),registeredBoardId:m.runtime.topBoardId,registeredBoardRevision:m.revision},...S.topAtFixed({xMm:200,yMm:200,rotationDeg:pr},m,0),stageMotion:{moduleId:m.id,revision:m.revision,qMm:0}},layout={board:board(),subBoards:[p],instances:[child]};
    e.snapshot=()=>copy(layout);e.setMeasurementMode(true);e.pickMeasurementPoint('child',front.id);const zero=e.measurementResult().points[0],stable=copy(child);
    for(const q of [S.limits(m).min,1.125,S.limits(m).max]){
      layout.subBoards[0]=S.withDisplacement(p,q,catalog);e.renderMeasurement();const actual=e.measurementResult().points[0],delta=S.rotate({xMm:m.motion.axis==='x'?q:0,yMm:m.motion.axis==='y'?q:0},pr);near(actual.xMm-zero.xMm,delta.xMm);near(actual.yMm-zero.yMm,delta.yMm);same(child,stable);assert.equal(e.measurementResult().targets.length,1);
    }
  }
});
test('front datum is independent of snapped physical holes and does not invoke optical-path probing',()=>{
  const {e}=fixture(1);datums(e);e.setMeasurementMode(true);e.measurementSnap=()=>{throw Error('marker must not ask a hole or optical-path probe')};clickMarker(e,marker(e));assert.equal(e.measurementResult().points[0].kind,'datum');
  delete e.measurementSnap;e.pickMeasurementAt({x:12.5,y:12.5});assert.equal(e.measurementResult().points[1].kind,'hole');
});
test('reset, catalog point withdrawal and instance deletion prune endpoints and target markers',()=>{
  const {e,document:d}=fixture(2);datums(e);e.setMeasurementMode(true);e.pickMeasurementPoint('p0',front.id);e.pickMeasurement('p1');d.getElementById('measurement-reset').handlers.click();same(e.measurement.ids,[]);assert.equal(e.measurementResult().targets.length,2);
  e.pickMeasurementPoint('p0',front.id);e.pickMeasurement('p1');e.kits.get('kit').layout.measurementPointsMm[0].verified=false;e.renderMeasurement();same(e.measurement.ids,['p1']);assert.equal(e.svg.querySelectorAll('[data-measurement-point]').length,0);assert.equal(d.getElementById('measurement-values').hidden,true);
  datums(e);e.pickMeasurementPoint('p0',front.id);e.removeIds(['p0']);assert.equal(e.measurement.ids.some(id=>id.startsWith('@point:')),false);assert.equal(e.svg.querySelectorAll('[data-measurement-point]').length,1);
  e.setMeasurementMode(false);assert.equal(e._measureLayer.getAttribute('display'),'none');assert.equal(e.pickMeasurementPoint('p1',front.id),false);
});
test('marker Enter/right-click work without changing normal component Enter or properties',()=>{
  const {e,document:d}=fixture(2);datums(e);e.setMeasurementMode(true);const m=marker(e);e.svg.focus();e.handleKeydown({key:'Enter',target:m,preventDefault(){}});assert.equal(e.measurementResult().points[0].kind,'datum');
  const before=copy(e.measurement),context=pointer(marker(e),{button:2});assert.equal(e.measureContextMenu(context),true);assert.equal(e._menuInstanceId,'p0');assert.equal(d.getElementById('component-context-menu').hidden,false);same(e.measurement,before);
  e.handleKeydown({key:'Enter',target:e._scene.partNodes.get('p1').image,preventDefault(){}});assert.equal(e.measurementResult().points[1].kind,'center');
});
test('marker click followed by pan, zoom and plate editing never changes saved project or history',()=>{
  const {e,counts}=stackedFixture();datums(e);e.setMeasurementMode(true);clickMarker(e,marker(e,'a1'));e.pickMeasurement('main');const before=copy(e.snapshot()),history=copy(e.history),changes=counts().changes,coords=copy(e.measurementResult().points);
  for(let n=0;n<8;n++){e.zoom(n%2?1/1.1:1.1);e.view.x+=2;e.renderView()}same(e.measurementResult().points,coords);assert.equal(counts().changes,changes,'measurement and zoom never persist');assert.equal(e.switchBoard('b'),true);same(e.measurementResult().points,coords);const after=e.snapshot();same({...after,instances:after.instances.sort((a,b)=>a.id.localeCompare(b.id))},{...before,instances:before.instances.sort((a,b)=>a.id.localeCompare(b.id))});same(e.history,history);assert.equal(counts().changes,changes+1,'existing board-switch notification is the only update');
});
test('moving a marker click or holding Space preserves ordinary pan and never selects a datum',()=>{
  const {e}=fixture(1);datums(e);e.setMeasurementMode(true);const before=copy(e.snapshot()),event=pointer(marker(e),{detail:1});
  e.svg.handlers.pointerdown(event);assert.equal(e.svg.handlers.click({...event,clientX:event.clientX+8}),false);same(e.measurement.ids,[]);
  e.space=true;e.svg.handlers.pointerdown(event);assert.equal(e.drag.mode,'pan');e.svg.handlers.pointerup({...event,type:'pointerup'});assert.equal(e.svg.handlers.click(event),false);same(e.measurement.ids,[]);same(e.snapshot(),before);
});
console.log(`${checks} named measurement datum checks passed`);
