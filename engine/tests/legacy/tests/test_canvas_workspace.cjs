'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const A=require('../static/canvas-workspace.js'),root=path.resolve(__dirname,'..');
let checks=0;function test(name,fn){fn();checks++;console.log('PASS '+name)}
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} ≈ ${b}`),clone=x=>JSON.parse(JSON.stringify(x));
test('enlarging and restoring a viewport keeps its centre and scale',()=>{
  const original={x:-25,y:-70,w:1000,h:500},small={width:600,height:300},large={width:1400,height:800},next=A.resizeView(original,small,large);
  close(next.x+next.w/2,original.x+original.w/2);close(next.y+next.h/2,original.y+original.h/2);close(next.w/large.width,original.w/small.width);close(next.h/large.height,original.h/small.height);
  const restored=A.resizeView(next,large,small);for(const k of Object.keys(original))close(restored[k],original[k]);
  assert.equal(A.resizeView(original,small,small),original);assert.equal(A.resizeView(original,small,{width:0,height:0}),original);
});
test('initial letterboxing is resolved using the existing visible scale',()=>{
  const view=A.resizeView({x:0,y:0,w:1000,h:500},{width:800,height:300},{width:1200,height:800});close(view.w/1200,500/300);close(view.h/800,500/300);
});
test('panel preferences tolerate unavailable storage and discard unexpected values',()=>{
  assert.deepEqual(A.readPanels({getItem:()=>'{broken'}),{catalog:true,settings:true,inspector:true});
  assert.deepEqual(A.readPanels({getItem:()=>JSON.stringify({catalog:false,settings:'false',inspector:true,anything:false})}),{catalog:false,settings:true,inspector:true});
  assert.deepEqual(A.readPanels({getItem(){throw Error('blocked')}}),{catalog:true,settings:true,inspector:true});
});
function dom(){
  const nodes=new Map(),events={},storage=new Map(),scrolls=[];
  class Node{constructor(){this.dataset={};this.hidden=false;this.events={};this.attributes={};this.classes=new Set();this.count=0;this.children=[];this.style={};this.clientWidth=800;this.clientHeight=600;this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name),add:name=>this.classes.add(name)}}set id(value){this._id=value;nodes.set(value,this)}get id(){return this._id}get offsetWidth(){return this.classes.has('is-collapsed')?182:350}get offsetHeight(){return this.classes.has('is-collapsed')?35:300}get offsetLeft(){return parseFloat(this.style.left)||0}get offsetTop(){return parseFloat(this.style.top)||0}appendChild(node){if(node.parentNode)node.parentNode.children=node.parentNode.children.filter(n=>n!==node);node.parentNode=this;this.children.push(node);return node}addEventListener(type,fn){this.events[type]=fn}setAttribute(k,v){this.attributes[k]=v}click(){this.events.click?.({target:this})}querySelectorAll(){return Array(this.count).fill({})}setPointerCapture(id){this.pointer=id}hasPointerCapture(id){return this.pointer===id}releasePointerCapture(){this.pointer=null}}
  for(const id of['canvas-display-controls','catalog','canvas-parameters','plan-panel','canvas-toggle-catalog','canvas-toggle-settings','canvas-toggle-inspector','canvas-focus-toggle','canvas-cart-link','board-settings','mounting-settings','stack-create','canvas-optical-details-toggle','optical-pending','optical-auto-problems','optical-warnings'])nodes.set(id,new Node());
  const body=new Node(),workspace=new Node(),document={body,getElementById:id=>nodes.get(id),createElement:()=>new Node(),querySelector:()=>workspace,addEventListener:(type,fn)=>events[type]=fn};
  const win={document,scrollX:0,scrollY:325,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},matchMedia:()=>({matches:win.narrow||false}),scrollTo:o=>scrolls.push(o),MutationObserver:class{constructor(callback){win.opticalUpdate=callback}observe(){}}};
  return{win,nodes,storage,scrolls,events,workspace,body,newNode:()=>new Node()};
}
test('focus hides panels, permits reopening them and restores the exact previous arrangement',()=>{
  const d=dom(),c=A.mount(d.win);d.nodes.get('canvas-toggle-inspector').click();const before=c.getState();const saved=[...d.storage.values()][0];
  c.setFocus(true);assert.deepEqual(c.getState(),{focused:true,panels:{catalog:false,settings:false,inspector:false}});assert.equal(d.nodes.get('catalog').hidden,true);assert.equal(d.nodes.get('canvas-focus-toggle').attributes['aria-pressed'],'true');
  d.nodes.get('canvas-toggle-catalog').click();assert.equal(d.nodes.get('catalog').hidden,false);assert.equal([...d.storage.values()][0],saved,'temporary focused arrangement is not persisted');
  c.setFocus(false);assert.deepEqual(c.getState(),before);assert.equal(d.scrolls.at(-1).top,325);assert.equal(d.nodes.get('plan-panel').hidden,true);assert.equal(d.nodes.get('canvas-toggle-inspector').attributes['aria-expanded'],'false');assert.equal(A.mount(d.win),null,'mount is idempotent');
});
test('narrow focus shows one sidebar and restores checkout access before navigation',()=>{
  const d=dom();d.win.narrow=true;const c=A.mount(d.win);c.setFocus(true);d.nodes.get('canvas-toggle-catalog').click();d.nodes.get('canvas-toggle-inspector').click();assert.equal(c.getState().panels.catalog,false);assert.equal(c.getState().panels.inspector,true);
  d.events.click({target:{closest:()=>true}});assert.equal(c.getState().focused,false);
});
test('parameter actions reveal a folded form without clearing unfinished edits',()=>{
  const d=dom(),c=A.mount(d.win),settings=d.nodes.get('board-settings');settings.value='unsaved';c.setFocus(true);settings.open=true;settings.events.toggle();assert.equal(c.getState().panels.settings,true);assert.equal(settings.value,'unsaved');
});
test('focus compacts optical details and keeps a visible, up-to-date notice entry',()=>{
  const d=dom(),c=A.mount(d.win),button=d.nodes.get('canvas-optical-details-toggle'),pending=d.nodes.get('optical-pending'),problems=d.nodes.get('optical-auto-problems');
  assert.equal(button.hidden,false);pending.count=2;problems.count=2;c.setFocus(true);assert.equal(button.hidden,false);assert.equal(button.attributes['aria-expanded'],'false');assert.equal(d.body.classes.has('canvas-optical-compact'),true);assert.match(button.textContent,/2 待确认/);assert.equal(pending.hidden,false,'renderer state is never changed');
  button.click();assert.equal(button.attributes['aria-expanded'],'true');assert.equal(d.body.classes.has('canvas-optical-compact'),false);pending.count=0;problems.count=1;d.win.opticalUpdate();assert.match(button.textContent,/1 项问题/);
  c.setFocus(false);assert.equal(button.hidden,false);assert.equal(pending.hidden,false);assert.equal(problems.count,1);c.setFocus(true);assert.equal(button.attributes['aria-expanded'],'false','a new focus session starts compact');
});
test('readout overlays reuse the renderer nodes and only show active or passive optics once',()=>{
  const d=dom();for(const id of['board-viewport','optical-workbench','measurement-bar','optical-probe','optical-passive-info']){const node=d.newNode();node.id=id;node.hidden=id!=='board-viewport'}
  const measurement=d.nodes.get('measurement-bar'),probe=d.nodes.get('optical-probe'),passive=d.nodes.get('optical-passive-info'),workbench=d.nodes.get('optical-workbench'),viewport=d.nodes.get('board-viewport'),c=A.mount(d.win),r=c.readouts;
  assert.equal(r.panel.parentNode,viewport);assert.equal(workbench.parentNode,viewport);assert.equal(probe.parentNode,d.nodes.get('canvas-optical-active-readout'));assert.equal(measurement.parentNode,d.nodes.get('canvas-readout-body'));assert.equal(r.panel.hidden,true);
  probe.hidden=false;workbench.hidden=false;r.visibility();assert.equal(r.panel.hidden,false);assert.equal(probe.parentNode.hidden,false);assert.equal(passive.hidden,true);
  workbench.hidden=true;passive.hidden=false;r.visibility();assert.equal(probe.parentNode.hidden,true);assert.equal(r.panel.hidden,false);assert.equal(d.nodes.get('optical-probe'),probe);assert.equal(viewport.clientHeight,600);
});
test('dragged or collapsed readouts retain position and state across new probe results and focus changes',()=>{
  const d=dom();for(const id of['board-viewport','optical-workbench','measurement-bar','optical-probe','optical-passive-info']){const node=d.newNode();node.id=id;node.hidden=!['board-viewport','measurement-bar'].includes(id)}
  const c=A.mount(d.win),r=c.readouts,handle=d.nodes.get('canvas-readout-handle'),toggle=d.nodes.get('canvas-readout-toggle'),measurement=d.nodes.get('measurement-bar'),event=(id,x,y)=>({pointerId:id,button:0,clientX:x,clientY:y,preventDefault(){},stopPropagation(){}});
  handle.events.pointerdown(event(1,700,550));handle.events.pointermove(event(1,500,400));handle.events.pointerup(event(1,500,400));const moved=r.getState();assert.ok(moved.x<1);assert.ok(moved.y<1);
  toggle.click();assert.equal(r.getState().collapsed,true);const position=[r.panel.style.left,r.panel.style.top];measurement.innerHTML='new measurement and eight returning beams';r.visibility();assert.deepEqual([r.panel.style.left,r.panel.style.top],position);assert.equal(r.getState().collapsed,true);c.setFocus(true);c.setFocus(false);assert.equal(r.getState().collapsed,true);
  measurement.hidden=true;r.visibility();assert.equal(r.panel.hidden,true);measurement.hidden=false;r.visibility();assert.equal(r.panel.hidden,false);assert.deepEqual(r.getState(),{...moved,collapsed:true});assert.equal(d.nodes.get('measurement-bar'),measurement);assert.equal(d.nodes.get('board-viewport').clientHeight,600);
  assert.ok([...d.storage.keys()].includes('zzlab.canvas-readout.v1'));assert.deepEqual(A.clampPanelPosition({x:-200,y:1000},{width:600,height:400},{width:350,height:300}),{x:8,y:92,xMax:242,yMax:92});
});
const harness={require,__dirname:root,console};vm.createContext(harness);const perf=fs.readFileSync(path.join(root,'test_layout_performance_frontend.cjs'),'utf8');vm.runInContext(perf.slice(0,perf.indexOf('{\n  const f=fixture(),e=f.editor'))+'\nglobalThis.makeEnvironment=environment;',harness);
test('the production editor preserves placement, selection, history and SVG nodes through resizing',()=>{
  const env=harness.makeEnvironment(fs.readFileSync(path.join(root,'static/layout.js'),'utf8')),catalog=require('../catalog.json');A.installViewport(env.Editor);A.installViewport(env.Editor);
  let changes=0;const e=new env.Editor({catalog:clone(catalog),saved:{board:{widthMm:625,heightMm:625,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]},instances:[{id:'p',kitId:'pbs-fixed',xMm:100,yMm:100,rotationDeg:0}]},notify(){},onChange(){changes++}});
  e.select('p');e.zoom(1.3);const original=clone(e.view),layout=clone(e.snapshot()),history=e.history.length,scene=e._scene,node=scene.partNodes.get('p').image,beforeChanges=changes,validations=e.renderStats.validationRuns;
  e.viewport.clientWidth=1400;e.viewport.clientHeight=900;e.renderView();close(e.view.w/1400,original.w/600);close(e.view.x+e.view.w/2,original.x+original.w/2);close(e.view.y+e.view.h/2,original.y+original.h/2);
  e.viewport.clientWidth=0;e.viewport.clientHeight=0;const expanded=clone(e.view);e.renderView();assert.deepEqual(clone(e.view),expanded);
  e.viewport.clientWidth=600;e.viewport.clientHeight=400;e.renderView();for(const k of Object.keys(original))close(e.view[k],original[k]);
  assert.deepEqual(clone(e.snapshot()),layout);assert.deepEqual([...e.selectedIds],['p']);assert.equal(e.history.length,history);assert.equal(e._scene,scene);assert.equal(scene.partNodes.get('p').image,node);assert.equal(changes,beforeChanges);assert.equal(e.renderStats.validationRuns,validations);
  e.viewport.clientWidth=1000;e.viewport.clientHeight=900;e.fit();close(e.view.w/e.view.h,1000/900);const fitted=clone(e.view);e.renderView();assert.deepEqual(clone(e.view),fitted,'explicit fit before the resize observer is not scaled twice');
});
test('a stacked engineering project resizes without switching the edited board or root coordinates',()=>{
  const source=['layout.js','stacked-boards.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n'),env=harness.makeEnvironment(source),catalog=require('../catalog.json'),layout=clone(require('../qa/optical-rendering-stacked.zzoptics.json').layout);
  const proto=env.document.getElementById('board-svg').constructor.prototype;proto.insertBefore=function(node,before){node.parentNode=this;const index=this.children.indexOf(before);this.children.splice(index<0?this.children.length:index,0,node);return node};proto.removeAttribute=function(key){delete this.attributes[key]};
  A.installViewport(env.Editor);const e=new env.Editor({catalog:clone(catalog),saved:layout,notify(){}});e.loadLayout(layout,'qa-small-module');e.setSelection([layout.instances.find(i=>i.boardId==='qa-small-module').id]);
  e.viewport.clientWidth=726;e.viewport.clientHeight=831;e.fit();e.view={x:-25,y:-75,w:1550,h:775};e.renderView();const before=clone(e.snapshot()),selected=[...e.selectedIds],center={x:e.view.x+e.view.w/2,y:e.view.y+e.view.h/2},previousWidth=e.view.w;
  e.viewport.clientWidth=973;e.viewport.clientHeight=790;e.renderView();assert.ok(e.view.w>=previousWidth,'a wider focus viewport cannot zoom in unexpectedly');close(e.view.x+e.view.w/2,center.x);close(e.view.y+e.view.h/2,center.y);assert.equal(e.activeBoardId,'qa-small-module');assert.deepEqual([...e.selectedIds],selected);assert.deepEqual(clone(e.snapshot()),before);
  const expanded=clone(e.view);e.renderView();assert.deepEqual(clone(e.view),expanded,'repeated optical refresh is stable');e.viewport.clientWidth=726;e.viewport.clientHeight=831;e.renderView();close(e.view.x+e.view.w/2,center.x);close(e.view.y+e.view.h/2,center.y);assert.deepEqual(clone(e.snapshot()),before);
});
console.log(`${checks} canvas workspace checks passed`);
