'use strict';
// Production renderer and collision engine, exercised against a counted SVG DOM.
// Counts establish allocation/revalidation behavior; timings are not browser paint measurements.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const engineSource=fs.readFileSync(__dirname+'/static/collision-engine.js','utf8');
const layoutSource=fs.readFileSync(__dirname+'/static/layout.js','utf8');
function environment(source=layoutSource){
  const metrics={creates:0,imageCreates:0,svgReplacements:0,attributeWrites:0,textWrites:0,htmlWrites:0,appends:0,validityEvents:0},elements=new Map(),frames=new Map();let frameSerial=0;
  class Element{
    constructor(tag='div',id=''){this.tagName=tag;this.id=id;this.attributes={};this.children=[];this.parentNode=null;this.handlers={};this.clientWidth=600;this.clientHeight=400;this._text='';this._html='';this.style={};this.value='';this.dataset={};metrics.creates++;if(tag==='image')metrics.imageCreates++;this.classList={toggle:(name,on)=>{const classes=new Set((this.attributes.class||'').split(' ').filter(Boolean));on??=!classes.has(name);on?classes.add(name):classes.delete(name);const next=[...classes].join(' ');if(next!==(this.attributes.class||''))this.setAttribute('class',next)},add:name=>this.classList.toggle(name,true),remove:name=>this.classList.toggle(name,false)};}
    getAttribute(key){return this.attributes[key]??null}
    setAttribute(key,value){this.attributes[key]=String(value);if(key==='data-instance')this.dataset.instance=String(value);metrics.attributeWrites++}
    get textContent(){return this._text}
    set textContent(value){this._text=String(value);this.children=[];metrics.textWrites++}
    get innerHTML(){return this._html}
    set innerHTML(value){this._html=String(value);this.children=[];metrics.htmlWrites++;if(this.tagName==='svg'){metrics.svgReplacements++;metrics.imageCreates+=(this._html.match(/<image\b/g)||[]).length}}
    appendChild(child){if(child.parentNode){const previous=child.parentNode.children;previous.splice(previous.indexOf(child),1)}child.parentNode=this;this.children.push(child);metrics.appends++;return child}
    remove(){if(this.parentNode){const children=this.parentNode.children;children.splice(children.indexOf(this),1);this.parentNode=null}}
    addEventListener(type,fn){this.handlers[type]=fn}
    contains(target){return target===this||this.children.some(child=>child.contains(target))}
    closest(selector){if(selector==='[data-instance]')return this.dataset.instance?this:this.parentNode?.closest(selector)||null;if(selector.includes('#layout-panel')&&['layout-panel','plan-panel'].includes(this.id))return this;if(selector.startsWith('input')&&['input','textarea','select'].includes(this.tagName))return this;return this.parentNode?.closest(selector)||null}
    focus(){document.activeElement=this}
    setPointerCapture(id){this.pointer=id}
    hasPointerCapture(id){return this.pointer===id}
    releasePointerCapture(){this.pointer=null}
    getBoundingClientRect(){return{width:600,height:400}}
    scrollIntoView(){}
  }
  const document={getElementById(id){if(!elements.has(id))elements.set(id,new Element(id==='board-svg'?'svg':'div',id));return elements.get(id)},createElementNS(ns,tag){return new Element(tag)},addEventListener(){},dispatchEvent(e){if(e.type==='layout-validity-change')metrics.validityEvents++}};
  document.body=new Element('body','body');document.activeElement=document.body;
  document.getElementById('layout-panel').appendChild(document.getElementById('board-viewport'));document.getElementById('board-viewport').appendChild(document.getElementById('board-svg'));
  const context={console,document,Set,Map,ResizeObserver:class{observe(){}},CustomEvent:class{constructor(type){this.type=type}},requestAnimationFrame(fn){const id=++frameSerial;frames.set(id,fn);return id},cancelAnimationFrame(id){frames.delete(id)},getSelection:()=>({toString:()=>''})};context.window=context;vm.createContext(context);vm.runInContext(engineSource,context);vm.runInContext(source,context);
  return{Editor:context.BreadboardEditor,document,metrics,frames,flush(){const callbacks=[...frames.values()];frames.clear();callbacks.forEach(fn=>fn())}};
}
const point=(xMm,yMm)=>({xMm,yMm}),kit={id:'kit',name:'Kit',layout:{topViewUrl:'./topviews/kit.svg',widthMm:10,heightMm:10,anchorXMm:5,anchorYMm:5,placementAllowed:true,collisionPolygonsMm:[[point(-5,-5),point(5,-5),point(5,5),point(-5,5)]],collisionBoundsMm:{xMin:-5,yMin:-5,xMax:5,yMax:5},baseBoundsMm:{xMin:-5,yMin:-5,xMax:5,yMax:5},mountingHoleOffsetsMm:[point(0,0)]}};
const clone=x=>JSON.parse(JSON.stringify(x));
function fixture(count=50,source=layoutSource){const env=environment(source),instances=Array.from({length:count},(_,index)=>({id:'p'+index,kitId:'kit',xMm:25+index%20*25,yMm:25+Math.floor(index/20)*25,rotationDeg:index%4*90}));let changes=0,selections=0;const editor=new env.Editor({catalog:{kits:[clone(kit)]},saved:{board:{widthMm:600,heightMm:400,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]},instances},onChange(){changes++},onSelect(){selections++},notify(){}});editor.world=e=>({x:e.clientX,y:e.clientY,xMm:e.clientX,yMm:editor.board.heightMm-e.clientY});return{...env,editor,counts:()=>({changes,selections})}}
const pointer=(type,x,y,target,extra={})=>({type,clientX:x,clientY:y,target,button:0,pointerId:1,preventDefault(){},...extra});
{
  const f=fixture(),e=f.editor,scene=e._scene,image=scene.partNodes.get('p0').image,part=scene.partNodes.get('p0').group,boundary=scene.partNodes.get('p0').boundary,board=scene.board;
  assert.ok(e._collisionEngine,'production editor is actually using the collision engine');
  const start={...f.metrics},validations=e.renderStats.validationRuns,engineStats=e._collisionEngine.getStats();
  for(let i=0;i<100;i++){e.view.x+=1;e.view.y-=.5;e.renderView();e.zoom(i%2?1/1.01:1.01)}
  assert.equal(e.renderStats.validationRuns,validations,'pan/zoom performs no validation');assert.deepEqual(e._collisionEngine.getStats(),engineStats,'pan/zoom does not touch geometry caches');assert.equal(f.metrics.creates,start.creates,'pan/zoom allocates no nodes');assert.equal(f.metrics.htmlWrites,start.htmlWrites,'pan/zoom replaces no markup');assert.equal(f.metrics.validityEvents,start.validityEvents,'pan/zoom does not notify purchase controls');
  e.select('p0');for(let i=0;i<100;i++){e.instances[0].xMm=i%2?25:37.5;e.render();assert.equal(e.validation(),e._validationCache.result,'render and controls reuse the validation result')}
  assert.equal(scene.partNodes.get('p0').image,image);assert.equal(scene.partNodes.get('p0').group,part);assert.equal(scene.partNodes.get('p0').boundary,boundary);assert.equal(scene.board,board);assert.equal(f.metrics.imageCreates,50,'one image per instance, retained through 100 moves');assert.equal(e.renderStats.boardUpdates,1,'board only renders when dimensions/pitch change');assert.equal(f.metrics.svgReplacements,0,'no complete SVG replacement');
  e.board={...e.board,widthMm:650};e.render();assert.equal(scene.board,board);assert.equal(scene.partNodes.get('p0').image,image,'board resize preserves images');assert.equal(e.renderStats.boardUpdates,2);
  e.instances=e.instances.slice(1);e.render();assert.equal(image.parentNode.parentNode,null,'removed instance is detached');assert.equal(scene.partNodes.size,49);e.instances.unshift({id:'new',kitId:'kit',xMm:25,yMm:25,rotationDeg:0});e.render();assert.equal(f.metrics.imageCreates,51);assert.equal(scene.partNodes.get('p1').image.getAttribute('href'),'./topviews/kit.svg');
}
{
  const f=fixture(3),e=f.editor,h=e.svg.handlers;e.select('p0');e.select('p1',{additive:true});const target=e._scene.partNodes.get('p0').group,before=clone(e.instances),history=e.history.length;
  h.pointerdown(pointer('pointerdown',25,375,target));const frames=e.renderStats.pointerFrames||0;
  for(let n=1;n<=100;n++)h.pointermove(pointer('pointermove',25+n/4,375-n/4,target));
  assert.equal(f.frames.size,1,'one scheduled frame for a burst of pointermoves');assert.equal(e.instances[0].xMm,25,'pending frame has not applied geometry prematurely');f.flush();assert.equal(e.renderStats.pointerFrames,frames+1);assert.equal(e.instances[0].xMm,50);assert.equal(e.instances[1].xMm-e.instances[0].xMm,before[1].xMm-before[0].xMm);
  // A new event is pending when pointerup arrives at a still newer position.
  h.pointermove(pointer('pointermove',62.5,337.5,target));h.pointerup(pointer('pointerup',75,325,target));assert.equal(f.frames.size,0);assert.equal(e.instances[0].xMm,75,'pointerup flushes its final coordinates synchronously');assert.equal(e.instances[0].yMm,75);assert.equal(e.history.length,history+1,'one group drag is one history step');f.flush();assert.equal(e.instances[0].xMm,75);e.undo();assert.deepEqual(clone(e.instances),before);e.redo();assert.equal(e.instances[0].xMm,75);
  const moved=clone(e.instances);h.pointerdown(pointer('pointerdown',75,325,target));h.pointermove(pointer('pointermove',100,300,target));h.pointercancel(pointer('pointercancel',100,300,target));f.flush();assert.deepEqual(clone(e.instances),moved,'cancelled queued movement cannot replay later');
}
{
  const f=fixture(10),e=f.editor,h=e.svg.handlers,blank=e.svg;e.select(null);h.pointerdown(pointer('pointerdown',10,390,blank,{shiftKey:true}));h.pointermove(pointer('pointermove',60,350,blank,{shiftKey:true}));f.flush();const notifications=f.counts().selections;h.pointermove(pointer('pointermove',62,348,blank,{shiftKey:true}));f.flush();assert.equal(f.counts().selections,notifications,'unchanged marquee selection does not rebuild the inspector');h.pointerup(pointer('pointerup',110,340,blank,{shiftKey:true}));assert.equal(e.selectedIds.size,4,'marquee includes the final pointerup region');assert.equal(e._scene.marquee.getAttribute('display'),'none');
  const x=e.view.x,y=e.view.y,validationRuns=e.renderStats.validationRuns;h.pointerdown(pointer('pointerdown',0,0,blank));for(let i=1;i<=40;i++)h.pointermove(pointer('pointermove',i,i/2,blank));assert.equal(f.frames.size,1);h.pointerup(pointer('pointerup',50,25,blank));assert.ok(e.view.x<x&&e.view.y<y);assert.equal(e.renderStats.validationRuns,validationRuns,'panning including pointerup does not recalculate geometry');
}
{
  const f=fixture(1),e=f.editor;assert.equal(e.validation().valid,true);const layout=e.kits.get('kit').layout;
  layout.baseBoundsMm.xMin=-30;assert.ok(e.validation().issues.some(x=>x.code==='out_of_bounds'),'in-place base change invalidates memo');layout.baseBoundsMm.xMin=-5;layout.mountingHoleOffsetsMm[0].xMm=1;assert.ok(e.validation().issues.some(x=>x.code==='mounting_mismatch'),'in-place hole metadata change invalidates memo');layout.mountingHoleOffsetsMm[0].xMm=0;layout.placementAllowed=false;assert.ok(e.validation().issues.some(x=>x.code==='placement_unavailable'));layout.placementAllowed=true;layout.topViewUrl='';assert.ok(e.validation().issues.some(x=>x.code==='placement_unavailable'));e.kits=new Map([['kit',clone(kit)]]);assert.equal(e.validation().valid,true,'same-pose replacement catalog cannot reuse stale validation');e.board={...e.board,pitchMm:25};e.instances=[{...e.instances[0],xMm:25}];assert.ok(e.validation().issues.some(x=>x.code==='mounting_mismatch'),'project import replaces board and instances without requiring explicit invalidation');
}
const baselinePath=process.env.ZZLAB_LAYOUT_BASELINE||'/tmp/zz-optics-layout-before-performance.js';
if(fs.existsSync(baselinePath)){
  const beforeSource=fs.readFileSync(baselinePath,'utf8');
  const trace=(f,action)=>{const initial={...f.metrics},v=f.editor.renderStats?.validationRuns||0,boards=f.editor.renderStats?.boardUpdates||0;let calls=0;const validate=f.editor.validation.bind(f.editor);f.editor.validation=()=>{calls++;return validate()};for(let n=0;n<100;n++)action(f.editor,n);return{imageCreations:f.metrics.imageCreates-initial.imageCreates,fullSvgReplacements:f.metrics.svgReplacements-initial.svgReplacements,boardUpdates:f.editor.renderStats?f.editor.renderStats.boardUpdates-boards:100,validationRuns:f.editor.renderStats?f.editor.renderStats.validationRuns-v:calls}};
  const move=(editor,n)=>{editor.instances[0].xMm=n%2?25:37.5;editor.render()},panZoom=(editor,n)=>{editor.view.x+=1;editor.zoom(n%2?1/1.01:1.01)};
  const report={scope:'Production renderer/engine against counted SVG DOM; counts exclude initial render, not browser paint timings.',moves:{scenario:'50 existing instances, 100 actual grid moves',baseline:trace(fixture(50,beforeSource),move),optimized:trace(fixture(50),move)},view:{scenario:'50 existing instances, 100 pan/zoom updates',baseline:trace(fixture(50,beforeSource),panZoom),optimized:trace(fixture(50),panZoom)}};
  assert.equal(report.moves.baseline.imageCreations,5000);assert.equal(report.moves.optimized.imageCreations,0);assert.equal(report.view.optimized.validationRuns,0);console.log(JSON.stringify(report));if(process.env.ZZLAB_PERF_REPORT)fs.writeFileSync(process.env.ZZLAB_PERF_REPORT,JSON.stringify(report,null,2)+'\n');
}
console.log('Incremental SVG: persistent board/image/boundary nodes, view-only pan/zoom, shared validation memo, RAF coalescing, final pointerup flush, atomic group history, marquee no-op, cancellation, and metadata/import invalidation passed.');
