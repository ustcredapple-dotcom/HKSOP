(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root){root.ZZLabCanvasWorkspace=api;api.installViewport(root.BreadboardEditor);if(root.document){if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',()=>api.mount(root));else api.mount(root)}}
})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  const STORAGE_KEY='zzlab.canvas-panels.v1';
  const defaults=()=>({catalog:true,settings:true,inspector:true});
  const names={catalog:'套件库',settings:'面包板参数',inspector:'器件属性'};

  // Keep the same world-space centre and millimetres per pixel when panels resize
  // the SVG. Matching the viewport aspect also avoids letterboxing hit-test drift.
  function resizeView(view,before,after){
    if(!view||!before||![before.width,before.height,after?.width,after?.height].every(n=>Number.isFinite(n)&&n>0))return view;
    if(before.width===after.width&&before.height===after.height)return view;
    const scale=Math.max(view.w/before.width,view.h/before.height),w=after.width*scale,h=after.height*scale;
    if(!Number.isFinite(scale)||scale<=0)return view;
    return{x:view.x+(view.w-w)/2,y:view.y+(view.h-h)/2,w,h};
  }
  function installViewport(Editor){
    if(!Editor||Editor.prototype._canvasWorkspaceInstalled)return;
    const P=Editor.prototype,oldFit=P.fit,oldView=P.renderView;
    P._canvasWorkspaceInstalled=true;
    const size=e=>({width:e.viewport?.clientWidth||0,height:e.viewport?.clientHeight||0});
    P.fit=function(...args){this._canvasViewportSize=size(this);return oldFit.apply(this,args)};
    P.renderView=function(...args){
      const next=size(this);
      if(next.width>0&&next.height>0){this.view=resizeView(this.view,this._canvasViewportSize,next);this._canvasViewportSize=next}
      return oldView.apply(this,args);
    };
  }
  function readPanels(storage){
    const panels=defaults();try{const saved=JSON.parse(storage?.getItem(STORAGE_KEY)||'null');for(const key of Object.keys(panels))if(typeof saved?.[key]==='boolean')panels[key]=saved[key]}catch(_){}
    return panels;
  }
  function opticalDetailsLabel({expanded=false,pending=0,problems=0,warnings=0}={}){
    const note=pending?`${pending} 待确认`:problems?`${problems} 项问题`:warnings?'有提示':'';
    return(expanded?'收起光路详情':'展开光路详情')+(note?' · '+note:'');
  }
  function clampPanelPosition(position,viewport,panel){
    const xMax=Math.max(8,viewport.width-panel.width-8),yMax=Math.max(8,viewport.height-panel.height-8);
    return{x:Math.max(8,Math.min(xMax,position.x)),y:Math.max(8,Math.min(yMax,position.y)),xMax,yMax};
  }
  function mountFloatingReadouts(win){
    const doc=win.document,$=id=>doc.getElementById(id),viewport=$('board-viewport'),workbench=$('optical-workbench');
    const measurement=$('measurement-bar'),probe=$('optical-probe'),passive=$('optical-passive-info');
    if(!viewport||!workbench||!measurement||!probe||!passive||$('canvas-readout-panel'))return null;
    const create=(tag,id,className)=>{const n=doc.createElement(tag);if(id)n.id=id;if(className)n.className=className;return n};
    const panel=create('section','canvas-readout-panel','canvas-readout-panel'),header=create('div',null,'canvas-readout-header'),handle=create('span','canvas-readout-handle','canvas-readout-handle'),toggle=create('button','canvas-readout-toggle'),body=create('div','canvas-readout-body','canvas-readout-body'),active=create('div','canvas-optical-active-readout');
    panel.hidden=true;panel.setAttribute('role','region');panel.setAttribute('aria-label','测量与光束读数');handle.textContent='⠿ 测量与光束';handle.tabIndex=0;handle.setAttribute('aria-label','拖动读数面板，或用方向键移动');toggle.type='button';toggle.setAttribute('aria-controls','canvas-readout-body');
    header.appendChild(handle);header.appendChild(toggle);panel.appendChild(header);panel.appendChild(body);body.appendChild(measurement);active.appendChild(probe);body.appendChild(active);body.appendChild(passive);
    // These are the same renderer-owned nodes. Only their presentation parent
    // changes; growing result lists can no longer resize the board viewport.
    viewport.appendChild(workbench);viewport.appendChild(panel);viewport.classList.add('canvas-overlay-ready');
    let state={collapsed:false,x:1,y:1},storage;try{storage=win.localStorage;const saved=JSON.parse(storage?.getItem('zzlab.canvas-readout.v1')||'null');if(typeof saved?.collapsed==='boolean')state.collapsed=saved.collapsed;for(const axis of['x','y'])if(Number.isFinite(saved?.[axis]))state[axis]=Math.max(0,Math.min(1,saved[axis]))}catch(_){}
    const dimensions=()=>({viewport:{width:viewport.clientWidth,height:viewport.clientHeight},panel:{width:panel.offsetWidth,height:panel.offsetHeight}});
    const save=()=>{try{storage?.setItem('zzlab.canvas-readout.v1',JSON.stringify(state))}catch(_){}};
    function position(){if(panel.hidden)return;const d=dimensions(),limits=clampPanelPosition({x:8,y:8},d.viewport,d.panel),p=clampPanelPosition({x:8+(limits.xMax-8)*state.x,y:8+(limits.yMax-8)*state.y},d.viewport,d.panel);panel.style.left=p.x+'px';panel.style.top=p.y+'px';panel.style.right='auto';panel.style.bottom='auto'}
    function move(left,top){const d=dimensions(),p=clampPanelPosition({x:left,y:top},d.viewport,d.panel);state.x=p.xMax>8?(p.x-8)/(p.xMax-8):1;state.y=p.yMax>8?(p.y-8)/(p.yMax-8):1;position()}
    function appearance(){body.hidden=state.collapsed;panel.classList.toggle('is-collapsed',state.collapsed);toggle.setAttribute('aria-expanded',String(!state.collapsed));toggle.textContent=state.collapsed?'展开':'收起';position()}
    function visibility(){active.hidden=workbench.hidden;const visible=!measurement.hidden||!workbench.hidden&&!probe.hidden||!passive.hidden;if(panel.hidden===visible){panel.hidden=!visible;position()}}
    toggle.addEventListener('click',()=>{state.collapsed=!state.collapsed;appearance();save()});
    let drag=null;
    handle.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();event.stopPropagation();drag={id:event.pointerId,x:event.clientX,y:event.clientY,left:panel.offsetLeft,top:panel.offsetTop};handle.setPointerCapture(event.pointerId)});
    handle.addEventListener('pointermove',event=>{if(!drag||event.pointerId!==drag.id)return;event.preventDefault();event.stopPropagation();move(drag.left+event.clientX-drag.x,drag.top+event.clientY-drag.y)});
    const finish=event=>{if(!drag||event.pointerId!==drag.id)return;drag=null;if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);save()};
    handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);
    handle.addEventListener('keydown',event=>{const delta={ArrowLeft:[-10,0],ArrowRight:[10,0],ArrowUp:[0,-10],ArrowDown:[0,10]}[event.key];if(delta){event.preventDefault();move(panel.offsetLeft+delta[0],panel.offsetTop+delta[1]);save()}event.stopPropagation()});
    panel.addEventListener('keydown',event=>event.stopPropagation());
    if(win.ResizeObserver){const observer=new win.ResizeObserver(position);observer.observe(viewport);observer.observe(panel)}
    if(win.MutationObserver){const observer=new win.MutationObserver(visibility);for(const node of[measurement,probe,passive,workbench])observer.observe(node,{attributes:true,attributeFilter:['hidden']})}
    appearance();visibility();return{panel,position,getState:()=>({...state}),visibility};
  }
  function mount(win){
    const doc=win.document,$=id=>doc.getElementById(id),controls=$('canvas-display-controls');
    if(!controls||controls.dataset.ready)return null;
    const workspace=doc.querySelector('.workspace'),body=doc.body,targets={catalog:$('catalog'),settings:$('canvas-parameters'),inspector:$('plan-panel')};
    if(!workspace||Object.values(targets).some(node=>!node))return null;
    controls.dataset.ready='true';let storage;try{storage=win.localStorage}catch(_){}
    const readouts=mountFloatingReadouts(win);
    let panels=readPanels(storage),focused=false,restore=null,opticalExpanded=false;
    function updateOpticalDetails(){
      const button=$('canvas-optical-details-toggle');if(!button)return;
      const count=(id,selector)=>{const el=$(id);return !el||el.hidden?0:el.querySelectorAll(selector).length};
      const pending=count('optical-pending','button'),problems=count('optical-auto-problems','button'),warnings=count('optical-warnings','p');
      button.hidden=false;button.setAttribute('aria-expanded',String(opticalExpanded));
      const label=opticalDetailsLabel({expanded:opticalExpanded,pending,problems,warnings});if(button.textContent!==label)button.textContent=label;
      button.classList.toggle('has-optical-notice',Boolean(pending||problems||warnings));
      body.classList.toggle('canvas-optical-compact',!opticalExpanded);
    }
    function save(){if(!focused)try{storage?.setItem(STORAGE_KEY,JSON.stringify(panels))}catch(_){}}
    function apply(){
      for(const key of Object.keys(targets)){
        const button=$('canvas-toggle-'+key),shown=panels[key];targets[key].hidden=!shown;
        workspace.classList.toggle('canvas-hide-'+key,!shown);button.setAttribute('aria-expanded',String(shown));button.textContent=(shown?'收起':'展开')+names[key];
      }
      body.classList.toggle('canvas-focused',focused);$('canvas-focus-toggle').setAttribute('aria-pressed',String(focused));
      $('canvas-focus-toggle').innerHTML='<span aria-hidden="true">'+(focused?'↙':'⛶')+'</span> '+(focused?'退出专注':'专注画布');
      updateOpticalDetails();
      save();
    }
    function setFocus(next,{restoreScroll=true}={}){
      if(next===focused)return;
      if(next){restore={panels:{...panels},scrollX:win.scrollX,scrollY:win.scrollY};panels={catalog:false,settings:false,inspector:false};focused=true;opticalExpanded=false;apply();win.scrollTo({left:0,top:0,behavior:'instant'})}
      else{focused=false;panels=restore?.panels||defaults();apply();if(restoreScroll&&restore)win.scrollTo({left:restore.scrollX,top:restore.scrollY,behavior:'instant'});restore=null}
    }
    for(const key of Object.keys(targets))$('canvas-toggle-'+key).addEventListener('click',()=>{
      panels[key]=!panels[key];
      // Narrow screens use one temporary side drawer, leaving part of the board
      // visible so a library card can still be dragged onto it.
      if(focused&&panels[key]&&key!=='settings'&&win.matchMedia('(max-width: 1049px)').matches)panels[key==='catalog'?'inspector':'catalog']=false;
      apply();
    });
    $('canvas-focus-toggle').addEventListener('click',()=>setFocus(!focused));
    $('canvas-optical-details-toggle')?.addEventListener('click',()=>{opticalExpanded=!opticalExpanded;updateOpticalDetails()});
    // Read existing renderer notices instead of changing its state. Watching only
    // these three small containers avoids observing the SVG or triggering traces.
    if(win.MutationObserver){const observer=new win.MutationObserver(updateOpticalDetails);for(const id of['optical-pending','optical-auto-problems','optical-warnings']){const node=$(id);if(node)observer.observe(node,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']})}}
    $('canvas-cart-link').addEventListener('click',()=>setFocus(false,{restoreScroll:false}));
    // Show the normal checkout area before the existing cart action navigates to
    // its result. This only changes presentation, never a cart or engineering file.
    doc.addEventListener('click',event=>{if(focused&&event.target.closest?.('#generate,[data-module-generate],a[href="#results"]'))setFocus(false,{restoreScroll:false})},true);
    // New-board and context-menu actions can open a parameter section themselves.
    // Reveal that section instead of leaving its form behind a collapsed panel.
    for(const id of['board-settings','mounting-settings','stack-create'])$(id)?.addEventListener('toggle',()=>{if($(id).open&&!panels.settings){panels.settings=true;apply()}});
    controls.hidden=false;apply();
    return{setFocus,readouts,getState:()=>({focused,panels:{...panels}})};
  }
  return{resizeView,installViewport,readPanels,opticalDetailsLabel,clampPanelPosition,mountFloatingReadouts,mount};
});
