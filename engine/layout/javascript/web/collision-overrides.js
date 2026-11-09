/* A user exception applies to one exact pair of placed components, never to boards or other validation rules. */
(function(root,factory){'use strict';const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root){root.ZZLabCollisionOverrides=api;if(root.BreadboardEditor&&root.document)api.install(root)}})(typeof window!=='undefined'?window:globalThis,function(){
  'use strict';
  const CAPABILITY='zzlab-collision-overrides-v1',MAX=10000;
  function pairKey(ids){return Array.isArray(ids)&&ids.length===2&&ids.every(id=>typeof id==='string'&&id.length>0)&&ids[0]!==ids[1]?JSON.stringify([...ids].sort()):null}
  function normalize(overrides,instances){const valid=instances==null?null:new Set(Array.from(instances,i=>typeof i==='string'?i:i.id)),pairs=new Map();for(const row of Array.isArray(overrides)?overrides:[]){const key=pairKey(row?.instanceIds);if(!key||valid&&row.instanceIds.some(id=>!valid.has(id)))continue;pairs.set(key,{instanceIds:JSON.parse(key)})}return [...pairs.values()].sort((a,b)=>a.instanceIds[0]<b.instanceIds[0]?-1:a.instanceIds[0]>b.instanceIds[0]?1:a.instanceIds[1]<b.instanceIds[1]?-1:a.instanceIds[1]>b.instanceIds[1]?1:0)}
  function filterIssues(issues,overrides,instances){const keys=new Set(normalize(overrides,instances).map(row=>pairKey(row.instanceIds)));return issues.filter(issue=>issue.code!=='collision'||!keys.has(pairKey(issue.instanceIds)))}
  function remap(overrides,idMap){const map=idMap instanceof Map?idMap:new Map(Array.isArray(idMap)?idMap.map(row=>[row.fromId,row.toId]):Object.entries(idMap||{}));return normalize(normalize(overrides).filter(row=>row.instanceIds.every(id=>map.has(id))).map(row=>({instanceIds:row.instanceIds.map(id=>map.get(id))})))}
  function merge(...lists){return normalize(lists.flatMap(list=>list||[]))}
  function install(root){
    const P=root.BreadboardEditor.prototype;if(P._collisionOverridesInstalled)return;P._collisionOverridesInstalled=true;
    const $=id=>root.document.getElementById(id),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const rawValidation=P.validation;
    P.unfilteredCollisionValidation=function(){return rawValidation.call(this)};
    P.validation=function(){const base=rawValidation.call(this);this._collisionRawValidation=base;const instances=this.snapshot().instances,overrides=normalize(this.collisionOverrides,instances);if(!overrides.length)return base;const key=JSON.stringify(overrides);if(this._overrideValidation?.base===base&&this._overrideValidation.key===key)return this._overrideValidation.value;const issues=filterIssues(base.issues,overrides,instances),value={...base,issues,...(Array.isArray(base.collisions)?{collisions:filterIssues(base.collisions,overrides,instances)}:{}),valid:!issues.length};this._overrideValidation={base,key,value};return value};
    P.collisionPairAvailable=function(ids,validation=null){const key=pairKey(ids),layout=this.snapshot();return Boolean(key&&ids.every(id=>layout.instances.some(i=>i.id===id))&&(validation||this.unfilteredCollisionValidation()).issues.some(issue=>issue.code==='collision'&&pairKey(issue.instanceIds)===key)&&!normalize(this.collisionOverrides).some(row=>pairKey(row.instanceIds)===key))};
    P.allowCollisionPair=function(ids){
      if(this.boardFormDirty||this.manualMounting||this.drag){this.notify('请先完成当前参数、选孔或拖动操作。',true);return false}
      if(!this.collisionPairAvailable(ids)){this.notify('请选择两个当前相互碰撞的器件；板、孔位、光高及机构范围不能人工解除。',true);return false}
      if(normalize(this.collisionOverrides).length>=MAX){this.notify('人工碰撞豁免已达到上限，请先恢复不再需要的条目。',true);return false}
      const before=this.historySnapshot();this.collisionOverrides=merge(this.collisionOverrides,[{instanceIds:ids}]);this.collisionOverridePicking=null;this.commit(before);this.notify('已解除这两个器件之间的碰撞限制；可在“碰撞豁免”中恢复。');return true;
    };
    P.restoreCollisionPair=function(ids){const key=pairKey(ids),before=this.historySnapshot(),next=normalize(this.collisionOverrides).filter(row=>pairKey(row.instanceIds)!==key);if(next.length===normalize(this.collisionOverrides).length)return false;this.collisionOverrides=next;this.commit(before);this.notify('已恢复这两个器件之间的碰撞检查。');return true};
    P.cancelCollisionOverrideSelection=function(render=true){if(!this.collisionOverridePicking)return;this.collisionOverridePicking=null;if(render)this.render()};
    P.beginCollisionOverrideSelection=function(){
      if(this.collisionOverridePicking){this.cancelCollisionOverrideSelection();return false}
      if(this.boardFormDirty||this.drag){this.notify('请先完成当前参数或拖动操作。',true);return false}
      this.cancelManualMounting(false);this.stopOpticalAuto?.();if(this.opticalMode)this.setOpticalMode?.(false);this.measurement=null;this.pendingKitId=null;this.selectedModuleId=null;this.setSelection([]);this.collisionOverridePicking={ids:[]};this.keyboardActive=true;this.render();this.svg.focus({preventScroll:true});return true;
    };
    P.pickCollisionOverride=function(id){
      if(!this.collisionOverridePicking||!this.snapshot().instances.some(i=>i.id===id))return false;
      const ids=this.collisionOverridePicking.ids;
      if(ids[0]===id){this.collisionOverridePicking.ids=[];this.render();return true}
      if(!ids.length){ids.push(id);this.render();return true}
      if(!this.allowCollisionPair([ids[0],id]))this.render();return true;
    };
    P.collisionInstanceLabel=function(id,layout=this.snapshot()){const i=layout.instances.find(row=>row.id===id);if(!i)return id;const owner=layout.subBoards?.find(p=>p.id===i.boardId),peers=layout.instances.filter(row=>(row.boardId||null)===(i.boardId||null));return `${owner?owner.name+' · ':layout.subBoards?'底板 · ':''}${String(peers.findIndex(row=>row.id===id)+1).padStart(2,'0')} ${this.kits.get(i.kitId)?.name||i.kitId}`};
    P.positionCollisionOverrides=function(){const panel=$('collision-overrides-panel'),popover=panel?.querySelector?.('.collision-overrides-popover');if(!panel?.open||!popover)return;const canvas=$('layout-panel').getBoundingClientRect(),anchor=panel.getBoundingClientRect(),width=Math.min(430,Math.max(180,canvas.width-24),root.innerWidth-24),left=Math.max(12,Math.min(canvas.left+12,root.innerWidth-width-12)),top=Math.max(12,Math.min(anchor.bottom+6,root.innerHeight-140));Object.assign(popover.style,{left:left+'px',top:top+'px',width:width+'px',maxHeight:Math.max(100,Math.min(root.innerHeight*.45,root.innerHeight-top-12))+'px'})};
    P.renderCollisionOverrides=function(){
      const layout=this.snapshot(),raw=this._collisionRawValidation||this.unfilteredCollisionValidation(),overrides=normalize(this.collisionOverrides,layout.instances),active=Boolean(this.collisionOverridePicking),button=$('collision-pick'),selected=$('collision-allow-selected'),summary=$('collision-overrides-summary'),list=$('collision-overrides-list');
      if(button){button.setAttribute('aria-pressed',String(active));button.textContent=active?'退出解除碰撞':'点选解除碰撞'}
      if(selected)selected.disabled=!this.collisionPairAvailable(Array.from(this.selectedIds||[]),raw);
      if(summary)summary.textContent=`碰撞豁免 · ${overrides.length}`;
      if(list){const html=overrides.length?overrides.map(row=>`<li><span>${row.instanceIds.map(id=>esc(this.collisionInstanceLabel(id,layout))).join(' ↔ ')}</span><button type="button" data-collision-restore="${esc(pairKey(row.instanceIds))}">恢复检查</button></li>`).join(''):'<li>尚无人工豁免。</li>';if(list._overrideHTML!==html){list.innerHTML=html;list._overrideHTML=html}}
      const candidates=$('collision-candidates');if(candidates){const existing=new Set(overrides.map(row=>pairKey(row.instanceIds))),valid=new Set(layout.instances.map(i=>i.id)),pairs=normalize(raw.issues.filter(issue=>issue.code==='collision'&&pairKey(issue.instanceIds)&&issue.instanceIds.every(id=>valid.has(id))).filter(issue=>!existing.has(pairKey(issue.instanceIds))));const html=pairs.length?pairs.slice(0,50).map(row=>`<li><span>${row.instanceIds.map(id=>esc(this.collisionInstanceLabel(id,layout))).join(' ↔ ')}</span><button type="button" data-collision-allow="${esc(pairKey(row.instanceIds))}">解除此对</button></li>`).join(''):'<li>没有待解除的器件碰撞。</li>';if(candidates._overrideHTML!==html){candidates.innerHTML=html;candidates._overrideHTML=html}}
      this.svg?.classList.toggle('collision-override-mode',active);
      const picked=new Set(this.collisionOverridePicking?.ids||[]),nodes=[...Array.from(this._scene?.partNodes?.values()||[],node=>node.group),...(this._scene?.contextNodes?.parts||[])];for(const node of nodes)node?.classList.toggle('collision-override-picked',picked.has(node.dataset.instance));
      if(active&&$('layout-hint'))$('layout-hint').textContent=picked.size?`已选 ${this.collisionInstanceLabel([...picked][0],layout)}；点击另一个冲突器件解除这对碰撞 · Esc 取消`:'解除碰撞：依次点击两个冲突器件（可跨小板） · 空格拖动平移 · Esc 取消';
    };
    const oldRender=P.render;P.render=function(...args){const result=oldRender.apply(this,args);this.renderCollisionOverrides();return result};
    for(const name of ['beginPlace','beginManualMounting','setMeasurementMode','setOpticalMode','loadLayout']){const old=P[name];if(old)P[name]=function(...args){this.cancelCollisionOverrideSelection(false);return old.apply(this,args)}}
    const oldKey=P.handleKeydown;P.handleKeydown=function(e){if(this.collisionOverridePicking&&e.key==='Escape'&&this.keyboardContext(e)){e.preventDefault();this.cancelCollisionOverrideSelection();return}return oldKey.call(this,e)};
    const oldBind=P.bind;P.bind=function(...args){
      // Register before the other capture listeners so this mode can pick contextual module children.
      this.svg.addEventListener('pointerdown',e=>{if(!this.collisionOverridePicking||this.space||e.button!==0)return;e.preventDefault();e.stopImmediatePropagation();this.keyboardActive=true;this.svg.focus({preventScroll:true});const id=e.target.closest?.('[data-instance]')?.dataset.instance;if(id)this.pickCollisionOverride(id)},true);
      for(const event of ['dblclick','contextmenu'])this.svg.addEventListener(event,e=>{if(this.collisionOverridePicking){e.preventDefault();e.stopImmediatePropagation()}},true);
      oldBind.apply(this,args);
      $('collision-pick')?.addEventListener('click',()=>this.beginCollisionOverrideSelection());
      $('collision-allow-selected')?.addEventListener('click',()=>this.allowCollisionPair(Array.from(this.selectedIds||[])));
      $('collision-overrides-panel')?.addEventListener('toggle',()=>this.positionCollisionOverrides());root.addEventListener?.('resize',()=>this.positionCollisionOverrides());root.addEventListener?.('scroll',()=>this.positionCollisionOverrides(),true);
      $('collision-overrides-panel')?.addEventListener('click',e=>{const restore=e.target.closest?.('[data-collision-restore]')?.dataset.collisionRestore,allow=e.target.closest?.('[data-collision-allow]')?.dataset.collisionAllow;if(restore)this.restoreCollisionPair(JSON.parse(restore));if(allow)this.allowCollisionPair(JSON.parse(allow))});
    };
  }
  return{CAPABILITY,MAX,pairKey,normalize,filterIssues,remap,merge,install};
});
