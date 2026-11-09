/* Transient centre/hole/registered-datum measurements. Never written into the project or undo history. */
(function(root){
  'use strict';
  const NS='http://www.w3.org/2000/svg';
  const axes={0:[1,0],90:[0,1],180:[-1,0],270:[0,-1]};
  const rotate=(p,angle)=>{const [c,s]=axes[angle]||axes[0];return{xMm:c*p.xMm-s*p.yMm,yMm:s*p.xMm+c*p.yMm}};
  function datumWorld(instance,layout,offset){
    const v=rotate(offset,instance.rotationDeg),local={xMm:instance.xMm+v.xMm,yMm:instance.yMm+v.yMm};
    const plate=layout.subBoards?.find(p=>p.id===instance.boardId);
    if(!plate)return local;
    const world=rotate(local,plate.rotationDeg);return{xMm:plate.xMm+world.xMm,yMm:plate.yMm+world.yMm};
  }
  function center(instance,layout,bounds){
    // The registered base centre is the post/installation centre. Image extents
    // include knobs and asymmetric bodies, so their midpoint is not this datum.
    return datumWorld(instance,layout,bounds?{xMm:(bounds.xMin+bounds.xMax)/2,yMm:(bounds.yMin+bounds.yMax)/2}:{xMm:0,yMm:0});
  }
  function registeredPoints(kit){
    const raw=kit?.layout?.measurementPointsMm;if(!Array.isArray(raw))return [];
    const seen=new Set();return raw.filter(p=>{
      if(!p||p.verified!==true||typeof p.id!=='string'||!p.id.trim()||typeof p.label!=='string'||!p.label.trim()||!['xMm','yMm','zMm'].every(key=>Number.isFinite(p[key]))||seen.has(p.id))return false;
      seen.add(p.id);return true;
    });
  }
  const datumId=(instanceId,pointId)=>'@point:'+encodeURIComponent(instanceId)+':'+encodeURIComponent(pointId);
  function namedPoints(layout,kits){
    return layout.instances.flatMap(i=>{
      const kit=kits.get(i.kitId),points=registeredPoints(kit);if(!points.length)return [];
      const plate=layout.subBoards?.find(p=>p.id===i.boardId),peers=layout.instances.filter(p=>(p.boardId||null)===(i.boardId||null)),number=String(peers.findIndex(p=>p.id===i.id)+1).padStart(2,'0');
      const prefix=plate?plate.name+' · ':layout.baseMode==='table'?'桌面 · ':layout.subBoards?'大板 · ':'';
      return points.map(p=>({id:datumId(i.id,p.id),kind:'datum',instanceId:i.id,pointId:p.id,boardId:i.boardId||null,...datumWorld(i,layout,p),name:`${prefix}${number} ${kit?.name||i.kitId} · ${p.label}`,label:p.label}));
    });
  }
  const localPoint=(p,plate)=>plate?rotate({xMm:p.xMm-plate.xMm,yMm:p.yMm-plate.yMm},(360-plate.rotationDeg)%360):p;
  const distance=(a,b)=>({dxMm:b.xMm-a.xMm,dyMm:b.yMm-a.yMm,xMm:Math.abs(b.xMm-a.xMm),yMm:Math.abs(b.yMm-a.yMm)});
  root.ZZLabMeasureMath={center,localPoint,distance,datumWorld,registeredPoints,namedPoints};
  if(typeof module==='object'&&module.exports)module.exports=root.ZZLabMeasureMath;
  if(!root.BreadboardEditor)return;
  const P=root.BreadboardEditor.prototype,$=id=>document.getElementById(id);
  const fmt=n=>String(Number(n.toFixed(3))),write=(el,value)=>{if(el&&el.textContent!==value)el.textContent=value};
  const node=(tag,attributes,parent,text)=>{const el=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attributes))el.setAttribute(k,String(v));if(text!==undefined)el.textContent=text;parent.appendChild(el);return el};

  P.measurementResult=function(){
    if(!this.measurement)return null;
    const layout=this.snapshot(),map=new Map(layout.instances.map(i=>[i.id,i]));
    const helper=root.ZZLabOpticalHoleProbe,holes=this.measurement.holes||{},holeIndex=Object.keys(holes).length&&helper?helper.build(layout,null,{catalog:this.catalog}):null;
    const resolvedHoles=new Map(Object.entries(holes).map(([id,h])=>[id,helper?.holeAt(holeIndex,h)]));
    // Resolve catalog datums afresh: instance, child plate and moving-stage poses may change.
    const targets=namedPoints(layout,this.kits),resolvedDatums=new Map(targets.map(p=>[p.id,p]));
    this.measurement.ids=this.measurement.ids.filter(id=>map.has(id)||resolvedHoles.get(id)||resolvedDatums.has(id));
    const points=this.measurement.ids.map(id=>{const datum=resolvedDatums.get(id);if(datum)return datum;const h=resolvedHoles.get(id);if(h)return{id,kind:h.referenceGrid?'reference-grid':'hole',boardId:h.boardId,xMm:h.x,yMm:h.y,name:`${h.referenceGrid?'桌面参考格点':h.boardName} · ${h.holeId?`孔 ${h.holeId} · ${h.thread||''} 螺纹孔`:`第 ${h.rowIndex+1} 行 / 第 ${h.columnIndex+1} 列${h.referenceGrid?'':'螺孔'}`}`};const i=map.get(id),kit=this.kits.get(i.kitId),plate=layout.subBoards?.find(p=>p.id===i.boardId);
      const peers=layout.instances.filter(p=>(p.boardId||null)===(i.boardId||null)),number=String(peers.findIndex(p=>p.id===id)+1).padStart(2,'0');
      return{id,kind:'center',boardId:i.boardId||null,...center(i,layout,kit?.layout?.baseBoundsMm),name:`${plate?plate.name+' · ':layout.baseMode==='table'?'桌面 · ':layout.subBoards?'大板 · ':''}${number} ${kit?.name||i.kitId} · 底座安装中心`};
    });
    return{layout,points,targets,...(points.length===2?distance(points[0],points[1]):{})};
  };
  P.setMeasurementMode=function(enabled){
    if(enabled){
      if(this.drag||this.stackDrag)return;
      this.cancelManualMounting(false);this.pendingKitId=null;this.measurement={ids:[]};
    }else this.measurement=null;
    this._measurementBlankClick=null;
    this._measurementClickSequence=null;
    this.keyboardActive=true;this.render();
    document.dispatchEvent(new CustomEvent('layout-validity-change'));
  };
  P.pickMeasurement=function(id){
    if(!this.measurement)return false;
    const result=this.measurementResult();if(!result.layout.instances.some(i=>i.id===id))return false;
    return this.pickMeasurementId(id);
  };
  P.pickMeasurementPoint=function(instanceId,pointId){
    if(!this.measurement)return false;
    const point=this.measurementResult().targets.find(p=>p.instanceId===instanceId&&p.pointId===pointId);
    return point?this.pickMeasurementId(point.id):false;
  };
  P.pickMeasurementId=function(id){
    const ids=this.measurement.ids;
    if(ids.length===1&&ids[0]===id){this.notify('请选择另一个位置作为 B 点。');return false}
    this.measurement.ids=ids.length===1?[ids[0],id]:[id];
    this.measurement.holes=Object.fromEntries(Object.entries(this.measurement.holes||{}).filter(([key])=>this.measurement.ids.includes(key)));
    this.renderMeasurement();return true;
  };
  P.measurementSnap=function(point){const helper=root.ZZLabOpticalHoleProbe;return helper?.snap(helper.build(this.snapshot(),null),null,point)};
  P.pickMeasurementAt=function(point){
    if(!this.measurement)return false;
    const result=this.measurementSnap(point);if(!result?.hole)return false;
    this.measurementResult();const id='@hole:'+result.hole.id;
    this.measurement.holes??={};this.measurement.holes[id]=result.hole;
    const picked=this.measurement.ids.length===1&&this.measurement.ids[0]===id?false:this.pickMeasurementId(id);this.onMeasurementSnap?.(result);return picked;
  };
  P.completeMeasurementClick=function(e){
    const pending=this._measurementBlankClick;this._measurementBlankClick=null;
    if(!pending||this.measurement!==pending.measurement||this.space||e.button!==0||
      Math.hypot(e.clientX-pending.clientX,e.clientY-pending.clientY)>4)return false;
    if(e.detail>1)return false;
    this._measurementClickSequence={instanceId:pending.pointId?null:pending.instanceId,before:JSON.parse(JSON.stringify(this.measurement))};
    return pending.pointId?this.pickMeasurementPoint(pending.instanceId,pending.pointId):this.pickMeasurementAt(pending.point);
  };
  P.measureDoubleClick=function(e){
    if(!this.measurement||this.space||e.button!==0)return false;
    const id=e.target.closest('[data-instance]')?.dataset.instance;if(!id)return false;
    e.preventDefault();e.stopImmediatePropagation?.();
    // Native double-click dispatches click first. Roll back that single-point
    // selection before choosing the component centre so A/B remain intentional.
    if(this._measurementClickSequence?.instanceId===id)this.measurement=this._measurementClickSequence.before;
    this._measurementBlankClick=null;this._measurementClickSequence=null;
    return this.pickMeasurement(id);
  };
  P.measureContextMenu=function(e){
    if(!this.measurement)return false;
    const id=e.target.closest('[data-measurement-point]')?.dataset.measurementInstance||e.target.closest('[data-instance]')?.dataset.instance,menu=$('component-context-menu');if(!id||!menu)return false;
    e.preventDefault();e.stopImmediatePropagation?.();this._menuInstanceId=id;
    if($('module-context-menu'))$('module-context-menu').hidden=true;
    menu.hidden=false;menu.style.left=Math.max(4,Math.min(e.clientX,(root.innerWidth||1024)-220))+'px';menu.style.top=Math.max(4,Math.min(e.clientY,(root.innerHeight||768)-100))+'px';
    return true;
  };
  P.measurePointer=function(e){
    this._measurementBlankClick=null;
    if(!this.measurement||e.button!==0||this.space)return false;
    const marker=e.target.closest('[data-measurement-point]'),id=marker?.dataset.measurementInstance||e.target.closest('[data-instance]')?.dataset.instance;
    const p=this.sceneWorld?this.sceneWorld(e):this.world(e);this._measurementBlankClick={instanceId:id,pointId:marker?.dataset.measurementPoint,point:{x:p.xMm,y:p.yMm},clientX:e.clientX,clientY:e.clientY,measurement:this.measurement};
    if(!id)return false;
    e.preventDefault();this.keyboardActive=true;this.svg.focus({preventScroll:true});
    return true;
  };
  P.renderMeasurement=function(){
    const active=Boolean(this.measurement);
    if(!active&&this._measurementVisible===false)return;
    this._measurementVisible=active;
    const button=$('layout-measure');if(button){button.setAttribute('aria-pressed',String(active));write(button,active?'退出测量':'测量模式')}
    this.svg?.classList.toggle('measuring',active);
    if(!active){
      if($('measurement-bar'))$('measurement-bar').hidden=true;
      if(this._measureLayer)this._measureLayer.setAttribute('display','none');
      return;
    }
    const result=this.measurementResult(),points=result.points,paired=points.length===2,table=result.layout.baseMode==='table',pointLabel=table?'格点或螺孔':'螺孔';
    const targetHint=result.targets.length?'或已标注基准点':'',status=paired?'测量完成 · 再选开始下一组':points.length?`已选 A 点 · 单击选${pointLabel}${targetHint}，双击器件选底座中心`:`单击选${pointLabel}${targetHint}，双击器件选底座中心，测量 X / Y 距离`;
    const direction=paired?`B 相对 A：${result.xMm<.0005?'X 相同':(result.dxMm>0?'向右 ':'向左 ')+fmt(result.xMm)+' mm'}；${result.yMm<.0005?'Y 相同':(result.dyMm>0?'向上 ':'向下 ')+fmt(result.yMm)+' mm'}`:'';
    const bar=$('measurement-bar');if(bar){
      bar.hidden=false;
      write($('measurement-status'),status);write($('measurement-points'),points.map((p,n)=>`${n?'B':'A'} · ${p.name}（X ${fmt(p.xMm)} / Y ${fmt(p.yMm)} mm）`).join('　→　'));
      $('measurement-values').hidden=!paired;write($('measurement-x'),paired?fmt(result.xMm)+' mm':'—');write($('measurement-y'),paired?fmt(result.yMm)+' mm':'—');write($('measurement-direction'),direction);
      write($('measurement-basis'),`${table?'桌面使用参考格点；子板螺孔取孔中心；元件取底座安装中心':'元件取底座安装中心，螺孔取孔中心'}${result.targets.length?'；标注基准点取已核验的机械面中心':''} · ${table?'按桌面 X / Y 方向':result.layout.subBoards?'按大面包板 X / Y 方向':'X 向右，Y 向上'} · Esc 退出`);
    }
    write($('layout-hint'),'测量模式：单击螺孔或已标注基准点 · 双击器件选底座中心 A / B · 右键器件看属性 · 空白拖动平移 · Esc 退出');
    this.drawMeasurement(result);
  };
  P.drawMeasurement=function(result){
    const svg=this.svg;let layer=this._measureLayer;
    // All boards share this SVG and the large board's coordinate system.
    if(!layer||layer.parentNode!==svg){layer=node('g',{'class':'measurement-layer','pointer-events':'none'},svg);this._measureLayer=layer}
    if(svg.children[svg.children.length-1]!==layer)svg.appendChild(layer);
    layer.setAttribute('display','inline');
    const height=result.layout.board.heightMm,screen=p=>({x:p.xMm,y:height-p.yMm});
    const points=result.points,both=points.length===2,scale=(this.view?.w||400)/650;
    const signature=JSON.stringify([points,result.targets,result.dxMm,result.dyMm,height,scale]);if(layer._measureKey===signature)return;layer._measureKey=signature;
    while(layer.firstChild)layer.removeChild(layer.firstChild);
    const label=(p,text,extra={})=>node('text',{x:p.x,y:p.y,'font-size':13*scale,...extra},layer,text);
    for(const p of result.targets){
      const at=screen(p),marker=node('g',{'data-measurement-point':p.pointId,'data-measurement-instance':p.instanceId,role:'button',tabindex:0,'aria-label':`选择 ${p.name} 为测量点`,style:'pointer-events:all;cursor:crosshair'},layer);
      node('title',{},marker,`单击选作 A / B：${p.name}`);
      // Only the bounded circle accepts clicks; annotations and the remaining canvas pass through.
      node('circle',{cx:at.x,cy:at.y,r:10*scale,fill:'transparent',stroke:'none','pointer-events':'all'},marker);
      node('circle',{cx:at.x,cy:at.y,r:4*scale,fill:'#e6f7f8',stroke:'#175a72','stroke-width':1.5*scale,'pointer-events':'none'},marker);
      node('path',{d:`M${at.x-6*scale} ${at.y}h${12*scale}M${at.x} ${at.y-6*scale}v${12*scale}`,fill:'none',stroke:'#175a72','stroke-width':scale,'pointer-events':'none'},marker);
      node('text',{x:at.x+8*scale,y:at.y+14*scale,'font-size':10*scale,'pointer-events':'none'},marker,p.label);
    }
    if(both){
      const [a,b]=result.points,elbow={xMm:b.xMm,yMm:a.yMm},sa=screen(a),sb=screen(b),se=screen(elbow);
      node('path',{d:`M${sa.x} ${sa.y}L${se.x} ${se.y}L${sb.x} ${sb.y}`,class:'measurement-lines'},layer);
      label({x:(sa.x+se.x)/2,y:(sa.y+se.y)/2-8*scale},`X ${fmt(result.xMm)} mm`,{'text-anchor':'middle'});
      label({x:(se.x+sb.x)/2+9*scale,y:(se.y+sb.y)/2+4*scale},`Y ${fmt(result.yMm)} mm`);
    }
    for(const p of points){const at=screen(p),letter=result.points[0].id===p.id?'A':'B',r=5*scale;
      node('circle',{cx:at.x,cy:at.y,r,class:'measurement-center measure-'+letter.toLowerCase()},layer);
      node('path',{d:`M${at.x-r*1.6} ${at.y}h${r*3.2}M${at.x} ${at.y-r*1.6}v${r*3.2}`,class:'measurement-cross'},layer);
      label({x:at.x+8*scale,y:at.y-9*scale},letter,{class:'measurement-point-label'});
    }
  };
  const oldBind=P.bind;P.bind=function(){oldBind.call(this);
    this.svg.addEventListener('click',e=>this.completeMeasurementClick(e));
    this.svg.addEventListener('dblclick',e=>this.measureDoubleClick(e),true);
    this.svg.addEventListener('contextmenu',e=>this.measureContextMenu(e),true);
    $('layout-measure')?.addEventListener('click',()=>this.setMeasurementMode(!this.measurement));
    $('measurement-reset')?.addEventListener('click',()=>{if(this.measurement){this.measurement.ids=[];this.measurement.holes={};this.renderMeasurement()}});
  };
  const oldRender=P.render;P.render=function(){oldRender.call(this);this.renderMeasurement()};
  const oldView=P.renderView;P.renderView=function(){oldView.call(this);if(this.measurement)this.renderMeasurement()};
  for(const method of ['beginPlace','beginManualMounting']){const old=P[method];P[method]=function(...args){this.measurement=null;const result=old.apply(this,args);this.renderMeasurement();return result}}
  const oldKey=P.handleKeydown;P.handleKeydown=function(e){
    if(this.measurement&&this.keyboardContext(e)){
      if(e.key==='Escape'){e.preventDefault();this.setMeasurementMode(false)}
      else if(e.key==='Enter'){const marker=e.target.closest('[data-measurement-point]'),id=e.target.closest('[data-instance]')?.dataset.instance;if(marker){e.preventDefault();this.pickMeasurementPoint(marker.dataset.measurementInstance,marker.dataset.measurementPoint)}else if(id){e.preventDefault();this.pickMeasurement(id)}}
      else if(e.key===' '){e.preventDefault();this.space=true;this.renderView()}
      else if(['Delete','Backspace','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))e.preventDefault();
      return;
    }
    return oldKey.call(this,e);
  };
})(typeof globalThis!=='undefined'?globalThis:this);
