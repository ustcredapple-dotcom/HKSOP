/* Breadboard coordinates: origin at lower left, millimetres, positive angles counterclockwise. */
(() => {
  'use strict';
  const NS='http://www.w3.org/2000/svg';
  const clone=x=>JSON.parse(JSON.stringify(x));
  let uidSerial=0;
  const uid=()=>`placed-${Date.now().toString(36)}-${(++uidSerial).toString(36)}-${Math.random().toString(36).slice(2,7)}`;
  const frozenClone=value=>{const copied=value==null?null:clone(value);const freeze=x=>{if(x&&typeof x==='object'){Object.values(x).forEach(freeze);Object.freeze(x)}return x};return freeze(copied)};
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const round=x=>Math.round(x*1000)/1000;
  // Keep existing SVG elements alive: unchanged attributes do not touch the DOM.
  const attrs=(node,values)=>{for(const [key,value]of Object.entries(values)){const next=String(value);if(node.getAttribute(key)!==next)node.setAttribute(key,next)}return node};
  const textContent=(node,value)=>{const next=String(value);if(node.textContent!==next)node.textContent=next};
  const htmlContent=(node,value)=>{if(node._layoutHTML!==value){node.innerHTML=value;node._layoutHTML=value}};
  const svgNode=(tag,values={},parent=null,text=null)=>{const node=document.createElementNS(NS,tag);attrs(node,values);if(text!==null)textContent(node,text);if(parent)parent.appendChild(node);return node};
  const EPS=1e-5;
  const rectPoints=b=>[{xMm:b.xMin,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMax},{xMm:b.xMin,yMm:b.yMax}];
  const pointsBounds=points=>({xMin:Math.min(...points.map(p=>p.xMm)),yMin:Math.min(...points.map(p=>p.yMm)),xMax:Math.max(...points.map(p=>p.xMm)),yMax:Math.max(...points.map(p=>p.yMm))});
  const boxesTouch=(a,b)=>a.xMin<=b.xMax+EPS&&a.xMax>=b.xMin-EPS&&a.yMin<=b.yMax+EPS&&a.yMax>=b.yMin-EPS;
  function pointSegmentDistance(p,a,b){const dx=b.xMm-a.xMm,dy=b.yMm-a.yMm,len=dx*dx+dy*dy,t=len?Math.max(0,Math.min(1,((p.xMm-a.xMm)*dx+(p.yMm-a.yMm)*dy)/len)):0;return Math.hypot(p.xMm-a.xMm-t*dx,p.yMm-a.yMm-t*dy)}
  function segmentsTouch(a,b,c,d){
    if(!boxesTouch(pointsBounds([a,b]),pointsBounds([c,d])))return false;
    if(pointSegmentDistance(a,c,d)<=EPS||pointSegmentDistance(b,c,d)<=EPS||pointSegmentDistance(c,a,b)<=EPS||pointSegmentDistance(d,a,b)<=EPS)return true;
    const cross=(p,q,r)=>(q.xMm-p.xMm)*(r.yMm-p.yMm)-(q.yMm-p.yMm)*(r.xMm-p.xMm);
    return (cross(a,b,c)>0)!==(cross(a,b,d)>0)&&(cross(c,d,a)>0)!==(cross(c,d,b)>0);
  }
  function pointInPolygon(p,polygon){let inside=false;for(let j=polygon.length-1,i=0;i<polygon.length;j=i++){
    const a=polygon[j],b=polygon[i];if(pointSegmentDistance(p,a,b)<=EPS)return true;
    if((a.yMm>p.yMm)!==(b.yMm>p.yMm)&&p.xMm<(b.xMm-a.xMm)*(p.yMm-a.yMm)/(b.yMm-a.yMm)+a.xMm)inside=!inside;
  }return inside}
  function polygonsTouch(a,b){if(!boxesTouch(pointsBounds(a),pointsBounds(b)))return false;for(let i=0;i<a.length;i++)for(let j=0;j<b.length;j++)if(segmentsTouch(a[i],a[(i+1)%a.length],b[j],b[(j+1)%b.length]))return true;return pointInPolygon(a[0],b)||pointInPolygon(b[0],a)}
  function circleTouchesPolygon(center,radius,polygon){return pointInPolygon(center,polygon)||polygon.some((a,i)=>pointSegmentDistance(center,a,polygon[(i+1)%polygon.length])<=radius+EPS)}
  class BreadboardEditor {
    constructor({catalog,saved,onChange,onSelect,notify,onCopy,onPaste,onRemove,captureExternalState,restoreExternalState}) {
      this.catalog=catalog;window.ZZLabRegisteredBoards?.configure(catalog);this.kits=new Map(catalog.kits.map(k=>[k.id,k]));this.onChange=onChange;this.onSelect=onSelect;this.notify=notify;this.onCopy=onCopy;this.onPaste=onPaste;this.onRemove=onRemove;this.captureExternalState=captureExternalState;this.restoreExternalState=restoreExternalState;
      this.board={widthMm:350,heightMm:225,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.5,holeType:'M6_through',mountingHoles:[]};this.boardFormDirty=false;this.instances=[];this.selectedId=null;this.selectedIds=new Set();this.clipboard=null;this.pasteCount=0;this.keyboardActive=false;this.history=[];this.future=[];this.view=null;this.pendingKitId=null;this.drag=null;this.space=false;
      this.baseMode=saved?.baseMode==='table'?'table':'breadboard';this.collisionOverrides=clone(saved?.collisionOverrides||[]);
      if(saved?.board)this.board=this.validBoard(saved.board)||this.board;
      if(Array.isArray(saved?.instances))this.instances=saved.instances.filter(i=>this.kits.has(i.kitId)&&Number.isFinite(i.xMm)&&Number.isFinite(i.yMm)).map(i=>({id:String(i.id||uid()),kitId:i.kitId,xMm:i.xMm,yMm:i.yMm,rotationDeg:[0,90,180,270].includes(i.rotationDeg)?i.rotationDeg:0,...('elevationMm'in i?{elevationMm:i.elevationMm}:{}),...('elevationSupportCount'in i?{elevationSupportCount:i.elevationSupportCount}:{}),...('laserAdapter'in i?{laserAdapter:clone(i.laserAdapter)}:{}),...('optics'in i?{optics:clone(i.optics)}:{}),...('internalOptics'in i?{internalOptics:clone(i.internalOptics)}:{}),...('sourcePorts'in i?{sourcePorts:clone(i.sourcePorts)}:{}),...('manualMount'in i?window.ZZLabManualSourceMount.normalize(i,this.kits.get(i.kitId)):{} ),...('universalPostSelection'in i?{universalPostSelection:clone(i.universalPostSelection)}:{})}));
      this.svg=document.getElementById('board-svg');this.viewport=document.getElementById('board-viewport');this.bind();this.syncFields();this.fit();this.render();
      this.resizeObserver=new ResizeObserver(()=>{if(!this.view)this.fit();else this.renderView()});this.resizeObserver.observe(this.viewport);
    }
    normalizeBoard(b){const result={widthMm:Number(b.widthMm),heightMm:Number(b.heightMm),pitchMm:Number(b.pitchMm),edgeOffsetMm:Number(b.edgeOffsetMm),thicknessMm:Number(b.thicknessMm??12.5),holeType:b.holeType||'M6_through'};if(result.holeType==='plain_through')result.holeDiameterMm=Number(b.holeDiameterMm??6);result.mountingHoles=Array.isArray(b.mountingHoles)?b.mountingHoles.map(h=>({columnIndex:h?.columnIndex,rowIndex:h?.rowIndex})):b.mountingHoles===undefined?[]:null;return result}
    boardErrors(b){const errors=[];if(!Array.isArray(b.mountingHoles)||![0,4,8].includes(b.mountingHoles.length)||b.mountingHoles.some(h=>!Number.isInteger(h.columnIndex)||h.columnIndex<0||!Number.isInteger(h.rowIndex)||h.rowIndex<0))errors.push('安装沉孔应为空，或由 4 或 8 个有效的行列位置组成。');if(![b.widthMm,b.heightMm,b.pitchMm,b.edgeOffsetMm,b.thicknessMm].every(Number.isFinite))return ['尺寸请输入有限数字。'];if(b.widthMm<25||b.widthMm>3000||b.heightMm<25||b.heightMm>3000)errors.push('长宽需为 25–3000 mm。');if(b.thicknessMm<3||b.thicknessMm>50)errors.push('板厚需为 3–50 mm。');if(!['M6_through','plain_through'].includes(b.holeType))errors.push('请选择 M6 通螺纹或普通通孔。');const diameter=b.holeType==='M6_through'?6:b.holeDiameterMm;if(!Number.isFinite(diameter)||diameter<1||diameter>20)errors.push('普通孔径需为 1–20 mm。');if(b.pitchMm<diameter+2||b.pitchMm>100)errors.push(`孔距需为 ${diameter+2}–100 mm。`);if(b.edgeOffsetMm<diameter/2+2||b.edgeOffsetMm>b.pitchMm||b.edgeOffsetMm*2>Math.min(b.widthMm,b.heightMm))errors.push(`首孔边距至少 ${diameter/2+2} mm，且不能超过孔距或短边的一半。`);if(!errors.length){const holes=(Math.floor((b.widthMm-b.edgeOffsetMm*2)/b.pitchMm)+1)*(Math.floor((b.heightMm-b.edgeOffsetMm*2)/b.pitchMm)+1);if(holes>2500)errors.push(`当前孔阵有 ${holes} 个孔，最多支持 2500 个；请增大孔距或减小面包板。`);}return errors}
    validBoard(source){const b=this.normalizeBoard(source);return this.boardErrors(b).length?null:b}
    snapshot(){return {...(this.baseMode==='table'?{baseMode:'table'}:{}),board:clone(this.board),instances:clone(this.instances),...(this.collisionOverrides?.length?{collisionOverrides:window.ZZLabCollisionOverrides?.normalize(this.collisionOverrides,this.instances)||clone(this.collisionOverrides)}:{})}}
    historySnapshot(){const state={...this.snapshot(),selection:{ids:Array.from(this.selectedIds||[]),primary:this.selectedId}};if(this.captureExternalState)state.externalState=clone(this.captureExternalState()??null);return state}
    commit(before){const after=this.historySnapshot(),content=s=>({baseMode:s.baseMode||'breadboard',board:s.board,instances:s.instances,subBoards:s.subBoards||null,collisionOverrides:s.collisionOverrides||[],...('externalState'in before?{externalState:s.externalState}:{})});if(JSON.stringify(content(before))===JSON.stringify(content(after)))return false;this.history.push(clone(before));if(this.history.length>80)this.history.shift();this.future=[];this.changed();return true}
    normalizeSelection(){const ids=new Set(this.instances.map(i=>i.id));if(!(this.selectedIds instanceof Set))this.selectedIds=new Set(this.selectedId?[this.selectedId]:[]);this.selectedIds=new Set(Array.from(this.selectedIds).filter(id=>ids.has(id)));if(!this.selectedIds.has(this.selectedId))this.selectedId=Array.from(this.selectedIds).at(-1)||null}
    changed(){if(window.ZZLabCollisionOverrides)this.collisionOverrides=window.ZZLabCollisionOverrides.normalize(this.collisionOverrides,this.snapshot().instances);this.normalizeSelection();this.render();this.onChange?.(this.snapshot());this.onSelect?.(this.selectedId,Array.from(this.selectedIds))}
    selectedInstances(){this.normalizeSelection();return this.instances.filter(i=>this.selectedIds.has(i.id))}
    selected(){const selected=this.selectedInstances();return selected.length===1?selected[0]:undefined}
    setSelection(ids,primary=null){const valid=new Set(this.instances.map(i=>i.id));this.selectedIds=new Set(ids.filter(id=>valid.has(id)));this.selectedId=this.selectedIds.has(primary)?primary:Array.from(this.selectedIds).at(-1)||null}
    select(id,{toggle=false,additive=false}={}){this.normalizeSelection();if(id==null){if(!additive)this.setSelection([])}else if(this.instances.some(i=>i.id===id)){if(toggle){if(this.selectedIds.has(id))this.selectedIds.delete(id);else this.selectedIds.add(id)}else if(additive)this.selectedIds.add(id);else this.selectedIds=new Set([id]);this.selectedId=this.selectedIds.has(id)?id:Array.from(this.selectedIds).at(-1)||null;}this.keyboardActive=true;this.render();this.onSelect?.(this.selectedId,Array.from(this.selectedIds))}
    selectAll(){this.setSelection(this.instances.map(i=>i.id));this.keyboardActive=true;this.render();this.onSelect?.(this.selectedId,Array.from(this.selectedIds))}
    selectInRect(rect,{additive=false,initialIds=[]}={}){const polygon=rectPoints(rect),hits=this.instances.filter(i=>boxesTouch(rect,this.worldBounds(i))&&this.worldPolygons(i).some(p=>polygonsTouch(p,polygon))).map(i=>i.id),next=Array.from(new Set(additive?[...initialIds,...hits]:hits)),unchanged=next.length===this.selectedIds.size&&next.every(id=>this.selectedIds.has(id));if(unchanged)this.renderMarquee();else{this.setSelection(next);this.render();this.onSelect?.(this.selectedId,Array.from(this.selectedIds))}return hits}
    restoreHistory(state){this.baseMode=state.baseMode==='table'?'table':'breadboard';this.board=clone(state.board);this.instances=clone(state.instances);this.collisionOverrides=clone(state.collisionOverrides||[]);this.setSelection(state.selection?.ids||[],state.selection?.primary);if('externalState'in state)this.restoreExternalState?.(clone(state.externalState));this.syncFields()}
    undo(){if(!this.history.length)return;this.future.push(this.historySnapshot());this.restoreHistory(this.history.pop());this.changed()}
    redo(){if(!this.future.length)return;this.history.push(this.historySnapshot());this.restoreHistory(this.future.pop());this.changed()}

    syncFields(){for(const [key,id]of Object.entries({widthMm:'board-width',heightMm:'board-height',pitchMm:'board-pitch',edgeOffsetMm:'board-offset',thicknessMm:'board-thickness',holeType:'board-hole-type'}))document.getElementById(id).value=this.board[key];document.getElementById('board-hole-diameter').value=this.board.holeDiameterMm||6;document.getElementById('board-hole-diameter-field').hidden=this.board.holeType!=='plain_through';document.getElementById('board-draft-note').hidden=true;this.boardFormDirty=false}
    anchorGrid(instance){
      const b=this.board,p=b.pitchMm,o=b.edgeOffsetMm,lastX=o+Math.floor((b.widthMm-o*2)/p)*p,lastY=o+Math.floor((b.heightMm-o*2)/p)*p,layout=this.kits.get(instance?.kitId)?.layout,raw=layout?.mountingHoleOffsetsMm;
      const known=Array.isArray(raw)&&raw.length>0&&raw.every(h=>Number.isFinite(h.xMm)&&Number.isFinite(h.yMm)),angle=(instance?.rotationDeg||0)*Math.PI/180,c=Math.round(Math.cos(angle)),sin=Math.round(Math.sin(angle));
      const source=window.ZZLabManualSourceMount?.reference(layout),sourceOffsets=source?[{xMm:source.xMm,yMm:source.yMm}]:null;const offsets=[];for(const h of sourceOffsets||(known?raw:[{xMm:0,yMm:0}])){const next={xMm:c*h.xMm-sin*h.yMm,yMm:sin*h.xMm+c*h.yMm};if(!offsets.some(v=>Math.abs(v.xMm-next.xMm)<=EPS&&Math.abs(v.yMm-next.yMm)<=EPS))offsets.push(next)}
      const requested=layout?.minimumAlignedMountingHoles,requiredCount=requested==null?offsets.length:Number.isInteger(requested)&&requested>=1&&requested<=128?requested:Infinity;
      const phases=[];for(const h of offsets){const x=o-h.xMm,y=o-h.yMm;let phase=phases.find(g=>this.sameGridPhase(g,{x,y}));if(!phase){phase={x,y,offsets:[]};phases.push(phase)}phase.offsets.push(h)}
      for(const phase of phases)Object.assign(phase,{count:phase.offsets.length,minX:o-Math.min(...phase.offsets.map(h=>h.xMm)),maxX:lastX-Math.max(...phase.offsets.map(h=>h.xMm)),minY:o-Math.min(...phase.offsets.map(h=>h.yMm)),maxY:lastY-Math.max(...phase.offsets.map(h=>h.yMm))});
      phases.sort((a,b)=>b.count-a.count);return{...phases[0],known,compatible:known&&phases[0].count>=requiredCount,fullyCompatible:known&&phases.length===1,offsets,phases,requiredCount,sourceReference:Boolean(source)};
    }
    sameGridPhase(a,b){const p=this.board.pitchMm;return['x','y'].every(axis=>{const n=(a[axis]-b[axis])/p;return Math.abs(n-Math.round(n))<=EPS})}
    isBoardHole(x,y){const b=this.board;return[[x,b.widthMm],[y,b.heightMm]].every(([value,limit])=>{const n=(value-b.edgeOffsetMm)/b.pitchMm;return value>=b.edgeOffsetMm-EPS&&value<=limit-b.edgeOffsetMm+EPS&&Math.abs(n-Math.round(n))<=EPS})}
    alignedGridPositions(grid,x,y){return grid.offsets.map(h=>({xMm:x+h.xMm,yMm:y+h.yMm})).filter(h=>this.isBoardHole(h.xMm,h.yMm)).map(h=>({xMm:Math.round(h.xMm*1e6)/1e6,yMm:Math.round(h.yMm*1e6)/1e6}))}
    isReferenceSurface(){return this._referenceSurface===true||this.baseMode==='table'&&!this.activeBoardId}
    partialMountingMinimum(i){return window.ZZLabRegisteredBoards?.partialMountingMinimum(this.kits.get(i?.kitId)?.layout)||0}
    physicalMountingPositions(i){return window.ZZLabRegisteredBoards?.mountingMatches(this.board,i,this.anchorGrid(i).offsets,this.catalog)||[]}
    allowsPartialBaseOverhang(i){const required=this.partialMountingMinimum(i);return required>0&&!this.isReferenceSurface()&&this.physicalMountingPositions(i).length>=required}
    snapPartialMountedGroup(instances,desired){if(this.isReferenceSurface()||!instances.some(i=>this.partialMountingMinimum(i)))return null;const R=window.ZZLabRegisteredBoards;return R?.snapMountedDelta(this.board,instances,i=>this.anchorGrid(i).offsets,i=>this.anchorGrid(i).requiredCount,desired,this.catalog,delta=>instances.every(i=>{const moved={...i,xMm:i.xMm+delta.xMm,yMm:i.yMm+delta.yMm};return this.allowsPartialBaseOverhang(moved)||!this.outOfBounds(moved)}))||null}
    mountingAlignment(instance){const grid=this.anchorGrid(instance);if(!grid.known)return null;const alignedPositionsMm=this.partialMountingMinimum(instance)&&!this.isReferenceSurface()?this.physicalMountingPositions(instance):this.alignedGridPositions(grid,instance.xMm,instance.yMm),alignedCount=alignedPositionsMm.length,totalCount=grid.offsets.length;return{instanceId:instance.id,kitId:instance.kitId,alignedCount,totalCount,requiredCount:grid.requiredCount,partial:alignedCount>0&&alignedCount<totalCount,alignedPositionsMm}}
    snapAxis(value,phase,min,max){const p=this.board.pitchMm,low=Math.ceil((min-phase-EPS)/p),high=Math.floor((max-phase+EPS)/p),index=Math.round((value-phase)/p);return round(phase+(low<=high?Math.max(low,Math.min(high,index)):index)*p)}
    snap(x,y,instance=null){
      if(instance){const partial=this.snapPartialMountedGroup([{...instance,xMm:0,yMm:0}],{xMm:x,yMm:y});if(partial)return partial}
      const grid=this.anchorGrid(instance);let best=null;for(const phase of grid.phases){const xs=[this.snapAxis(x,phase.x,phase.minX,phase.maxX)],ys=[this.snapAxis(y,phase.y,phase.minY,phase.maxY)];
        // An oversized pattern may only partly fit the board: examine the entering
        // and leaving hole positions, always within this real two-dimensional phase.
        if(phase.minX>phase.maxX||phase.minY>phase.maxY)for(const h of phase.offsets){const b=this.board,p=b.pitchMm,o=b.edgeOffsetMm;if(phase.minX>phase.maxX)xs.push(this.snapAxis(x,phase.x,o-h.xMm,o+Math.floor((b.widthMm-o*2)/p)*p-h.xMm));if(phase.minY>phase.maxY)ys.push(this.snapAxis(y,phase.y,o-h.yMm,o+Math.floor((b.heightMm-o*2)/p)*p-h.yMm))}
        for(const xMm of new Set(xs))for(const yMm of new Set(ys)){const count=this.alignedGridPositions(grid,xMm,yMm).length,distance=(xMm-x)**2+(yMm-y)**2;if(!best||count>best.count||count===best.count&&distance<best.distance-EPS)best={xMm,yMm,count,distance}}
      }return{xMm:best.xMm,yMm:best.yMm};
    }
    freeSpot(instance=null){const b=this.board,p=b.pitchMm,g=this.anchorGrid(instance),first=this.snap(g.minX,g.minY,instance);for(let y=first.yMm;y<=g.maxY+EPS;y+=p)for(let x=first.xMm;x<=g.maxX+EPS;x+=p)if(!this.instances.some(i=>Math.abs(i.xMm-x)<.01&&Math.abs(i.yMm-y)<.01))return{xMm:x,yMm:y};return this.snap(b.widthMm/2,b.heightMm/2,instance)}
    canCreateKit(kitId){const kit=this.kits.get(kitId);return !!kit&&kit.lifecycle?.canCreate!==false&&kit.lifecycle?.state!=='historical'}
    add(kitId,point){if(!this.canCreateKit(kitId)){this.notify('历史器件仅用于已有工程，不能新增。',true);return}if(!this.kits.has(kitId)||this.kits.get(kitId).layout?.placementAllowed===false)return;if((this.allInstances?.()||this.instances).length>=500){this.notify('最多放置 500 个套件。',true);return}const before=this.historySnapshot(),i={id:uid(),kitId,rotationDeg:0};Object.assign(i,point?this.snap(point.xMm,point.yMm,i):this.freeSpot(i));this.instances.push(i);this.setSelection([i.id],i.id);this.pendingKitId=null;this.commit(before);this.keyboardActive=true;this.svg?.focus({preventScroll:true});this.notify(`已放置 ${this.kits.get(kitId).name}`);return i}
    beginPlace(kitId){if(!this.canCreateKit(kitId)){this.notify('历史器件仅用于已有工程，不能新增。',true);return}this.cancelManualMounting(false);this.pendingKitId=kitId;this.render();this.notify('点击面包板上的格点放置；Esc 取消。');this.viewport.scrollIntoView({behavior:'smooth',block:'nearest'});this.svg.focus({preventScroll:true})}
    remove(){const ids=this.selectedInstances().map(i=>i.id);if(!ids.length)return;return this.removeIds(ids)}
    removeIds(ids){const removeSet=new Set(ids),before=this.historySnapshot();this.instances=this.instances.filter(i=>!removeSet.has(i.id));this.setSelection([]);try{this.onRemove?.(ids);this.commit(before)}catch(error){this.restoreHistory(before);this.changed();this.notify('删除未完成，原选择已保留。',true);return null}return ids}
    selectionPacket(){const instances=this.selectedInstances();if(!instances.length)return null;const metadata=this.onCopy?.(instances.map(i=>i.id));return frozenClone({instances,metadata:metadata??null,...(this.collisionOverrides?.length?{collisionOverrides:window.ZZLabCollisionOverrides?.normalize(this.collisionOverrides,instances)||[]}:{})})}
    copySelection(){const packet=this.selectionPacket();if(!packet)return null;this.clipboard=packet;this.pasteCount=0;this.render();this.notify(`已复制 ${packet.instances.length} 个器件及其选配。`);return packet}
    commonDelta(instances,dx,dy,{snapToGrid=true}={}){
      if(!instances.length)return{xMm:0,yMm:0};if(snapToGrid){const partial=this.snapPartialMountedGroup(instances,{xMm:dx,yMm:dy});if(partial)return partial}const grids=instances.map(i=>this.anchorGrid(i)),deltaPhases=grids.map((g,n)=>g.phases.map(phase=>({...phase,x:phase.x-instances[n].xMm,y:phase.y-instances[n].yMm,minX:phase.minX-instances[n].xMm,maxX:phase.maxX-instances[n].xMm,minY:phase.minY-instances[n].yMm,maxY:phase.maxY-instances[n].yMm})));
      if(instances.length===1&&snapToGrid){const point=this.snap(instances[0].xMm+dx,instances[0].yMm+dy,instances[0]);return{xMm:round(point.xMm-instances[0].xMm),yMm:round(point.yMm-instances[0].yMm)}}
      // Intersect joint X/Y phases; independent axis choices can invent a phase
      // that does not align any real screw. Every member receives one rigid delta.
      const common=deltaPhases[0].filter(phase=>deltaPhases.every((choices,n)=>choices.some(choice=>choice.count>=grids[n].requiredCount&&this.sameGridPhase(phase,choice))));
      const candidates=common.length?common:[...deltaPhases[0],{x:0,y:0}];let best=null;
      for(const phase of candidates){const matches=deltaPhases.map(choices=>choices.find(choice=>this.sameGridPhase(phase,choice))||choices[0]),minX=Math.max(...matches.map(g=>g.minX)),maxX=Math.min(...matches.map(g=>g.maxX)),minY=Math.max(...matches.map(g=>g.minY)),maxY=Math.min(...matches.map(g=>g.maxY));
        const xMm=snapToGrid?this.snapAxis(dx,phase.x,minX,maxX):round(minX<=maxX?Math.max(minX,Math.min(maxX,dx)):dx),yMm=snapToGrid?this.snapAxis(dy,phase.y,minY,maxY):round(minY<=maxY?Math.max(minY,Math.min(maxY,dy)):dy),counts=grids.map((grid,n)=>this.alignedGridPositions(grid,instances[n].xMm+xMm,instances[n].yMm+yMm).length),valid=counts.filter((count,n)=>count>=grids[n].requiredCount).length,count=counts.reduce((a,b)=>a+b,0),distance=(xMm-dx)**2+(yMm-dy)**2;
        if(!best||valid>best.valid||valid===best.valid&&(count>best.count||count===best.count&&distance<best.distance-EPS))best={xMm,yMm,valid,count,distance};
      }return{xMm:best.xMm,yMm:best.yMm};
    }
    applyGroupDelta(originals,dx,dy){const delta=this.commonDelta(originals,dx,dy),byId=new Map(originals.map(i=>[i.id,i]));for(const instance of this.instances){const original=byId.get(instance.id);if(original){instance.xMm=round(original.xMm+delta.xMm);instance.yMm=round(original.yMm+delta.yMm)}}return delta}
    pastePacket(packet,offsetNumber=1){if(!packet?.instances?.length)return null;if((this.allInstances?.()||this.instances).length+packet.instances.length>500){this.notify(`最多放置 500 个套件；本次 ${packet.instances.length} 个未粘贴。`,true);return null}if(packet.instances.some(i=>!this.canCreateKit(i.kitId)||this.kits.get(i.kitId).layout?.placementAllowed===false)){this.notify('复制的套件不适用于当前套件库，未粘贴。',true);return null}const before=this.historySnapshot(),delta=this.commonDelta(packet.instances,this.board.pitchMm*offsetNumber,this.board.pitchMm*offsetNumber),used=new Set(this.instances.map(i=>i.id)),mapping=[],copies=packet.instances.map(original=>{let id;do{id=uid()}while(used.has(id));used.add(id);mapping.push({fromId:original.id,toId:id});return{...clone(original),id,xMm:round(original.xMm+delta.xMm),yMm:round(original.yMm+delta.yMm)}});const overrides=window.ZZLabCollisionOverrides?.merge(this.collisionOverrides,window.ZZLabCollisionOverrides.remap(packet.collisionOverrides,mapping));if(overrides&&overrides.length>window.ZZLabCollisionOverrides.MAX){this.notify('本次粘贴会超过 10000 对人工碰撞豁免，未粘贴。',true);return null}this.instances.push(...copies);this.setSelection(copies.map(i=>i.id),copies.at(-1).id);try{this.onPaste?.(clone(mapping),clone(packet.metadata));if(overrides)this.collisionOverrides=overrides;this.commit(before)}catch(error){this.restoreHistory(before);this.changed();this.notify('粘贴未完成，原方案已保留。',true);return null}this.notify(`已粘贴 ${copies.length} 个器件，可拖动所选组调整位置。`);return{mapping,ids:copies.map(i=>i.id)}}
    pasteSelection(){const result=this.pastePacket(this.clipboard,(this.pasteCount||0)+1);if(result)this.pasteCount=(this.pasteCount||0)+1;return result}
    duplicate(){const packet=this.selectionPacket();return packet?this.pastePacket(packet):null}
    rotate(){const i=this.selected();if(!i)return;const before=this.historySnapshot();i.rotationDeg=(i.rotationDeg+90)%360;Object.assign(i,this.snap(i.xMm,i.yMm,i));this.commit(before)}
    move(dx,dy){const originals=clone(this.selectedInstances());if(!originals.length)return;const before=this.historySnapshot();this.applyGroupDelta(originals,dx,dy);this.commit(before)}
    position(x,y,rotation){const i=this.selected();if(!i)return;const before=this.historySnapshot();if([0,90,180,270].includes(rotation))i.rotationDeg=rotation;Object.assign(i,this.snap(x,y,i));this.commit(before)}
    clear(){if(!this.instances.length)return;return this.removeIds(this.instances.map(i=>i.id))}

    kitLayout(i){const l=this.kits.get(i.kitId)?.layout||{};const actual=typeof l.topViewUrl==='string'&&l.topViewUrl.trim().length>0&&Number(l.widthMm)>0&&Number(l.heightMm)>0;return {actual,width:Number(l.widthMm)||25,height:Number(l.heightMm)||25,ax:Number.isFinite(Number(l.anchorXMm))?Number(l.anchorXMm):(Number(l.widthMm)||25)/2,ay:Number.isFinite(Number(l.anchorYMm))?Number(l.anchorYMm):(Number(l.heightMm)||25)/2,url:actual?l.topViewUrl:null,status:l.status||'pending',note:l.note||l.notes||''}}
    localBounds(i,kind){const raw=this.kits.get(i.kitId)?.layout?.[kind+'BoundsMm'];if(raw&&['xMin','yMin','xMax','yMax'].every(k=>Number.isFinite(raw[k]))&&raw.xMax>raw.xMin&&raw.yMax>raw.yMin)return raw;const l=this.kitLayout(i);return{xMin:-l.ax,yMin:l.ay-l.height,xMax:l.width-l.ax,yMax:l.ay}}
    localPolygons(i){const polygons=this.kits.get(i.kitId)?.layout?.collisionPolygonsMm;if(Array.isArray(polygons)&&polygons.length&&polygons.every(p=>Array.isArray(p)&&p.length>=3&&p.every(v=>Number.isFinite(v.xMm)&&Number.isFinite(v.yMm))))return polygons;return[rectPoints(this.localBounds(i,'collision'))]}
    worldPoint(i,p){const a=i.rotationDeg*Math.PI/180,c=Math.round(Math.cos(a)),s=Math.round(Math.sin(a));return{xMm:i.xMm+p.xMm*c-p.yMm*s,yMm:i.yMm+p.xMm*s+p.yMm*c}}
    collisionEngine(){const Engine=window.ZZLabCollisionEngine?.Engine;if(!Engine)return null;if(!this._collisionEngine)this._collisionEngine=new Engine({kits:this.kits});else if(this._collisionKits!==this.kits){this._collisionEngine.setKits(this.kits);this._validationCache=null}this._collisionKits=this.kits;return this._collisionEngine}
    worldPolygons(i){return this.collisionEngine()?.world(i).polygons||this.localPolygons(i).map(p=>p.map(v=>this.worldPoint(i,v)))}
    worldBounds(i,kind='collision'){if(kind==='collision'){const cached=this.collisionEngine()?.world(i);if(cached)return cached.bounds}return pointsBounds(kind==='collision'?this.worldPolygons(i).flat():rectPoints(this.localBounds(i,kind)).map(p=>this.worldPoint(i,p)))}
    outOfBounds(i){if(this.allowsPartialBaseOverhang(i))return false;const b=this.worldBounds(i,'base');return b.xMin<-EPS||b.yMin<-EPS||b.xMax>this.board.widthMm+EPS||b.yMax>this.board.heightMm+EPS}
    mountingPositions(){return(this.board.mountingHoles||[]).map((h,index)=>({...h,id:`H${index+1}`,xMm:round(this.board.edgeOffsetMm+h.columnIndex*this.board.pitchMm),yMm:round(this.board.edgeOffsetMm+h.rowIndex*this.board.pitchMm)}))}
    mountingObstructions(hole){const circleBox={xMin:hole.xMm-5.5,yMin:hole.yMm-5.5,xMax:hole.xMm+5.5,yMax:hole.yMm+5.5};return this.instances.filter(i=>{
      const polygons=this.worldPolygons(i);return polygons.length&&boxesTouch(circleBox,pointsBounds(polygons.flat()))&&polygons.some(p=>circleTouchesPolygon(hole,5.5,p));
    })}
    mountingHoleClearanceError(hole,chosen=[]){
      const b=this.board,p=b.pitchMm,o=b.edgeOffsetMm,columns=Math.floor((b.widthMm-o*2)/p+EPS)+1,rows=Math.floor((b.heightMm-o*2)/p+EPS)+1,nominal=b.holeType==='M6_through'?6:b.holeDiameterMm,selected=new Set([...chosen,hole].map(h=>`${h.columnIndex},${h.rowIndex}`));
      for(let row=0;row<rows;row++)for(let column=0;column<columns;column++){
        if(column===hole.columnIndex&&row===hole.rowIndex)continue;
        const counterbore=selected.has(`${column},${row}`),minimum=counterbore?11:5.5+nominal/2+2;
        if(Math.hypot(column-hole.columnIndex,row-hole.rowIndex)*p<minimum-EPS)return counterbore?'两个沉孔的实际孔径重叠，请调整孔位。':'沉孔与相邻普通孔之间不足 2 mm 净距，请增大孔距。';
      }
      return '';
    }
    mountingIssues(){const holes=this.mountingPositions(),issues=[];if(!holes.length)return issues;
      if(![4,8].includes(holes.length)||new Set(holes.map(h=>`${h.columnIndex},${h.rowIndex}`)).size!==holes.length)issues.push({code:'board_mounting_invalid',instanceIds:[],message:'安装沉孔必须是 4 或 8 个不同的孔位，请重新自动选孔。'});
      if(this.board.thicknessMm<8.5)issues.push({code:'board_mounting_invalid',instanceIds:[],message:'安装沉孔需要板厚至少 8.5 mm，请加厚面包板或清除安装沉孔。'});
      const columns=Math.floor((this.board.widthMm-this.board.edgeOffsetMm*2)/this.board.pitchMm)+1,rows=Math.floor((this.board.heightMm-this.board.edgeOffsetMm*2)/this.board.pitchMm)+1;
      for(const h of holes){if(h.columnIndex<0||h.columnIndex>=columns||h.rowIndex<0||h.rowIndex>=rows||Math.min(h.xMm,h.yMm,this.board.widthMm-h.xMm,this.board.heightMm-h.yMm)<7.5-EPS)issues.push({code:'board_mounting_invalid',instanceIds:[],holeIds:[h.id],message:`${h.id} 安装沉孔距离板边不足 7.5 mm 或已越出孔阵，请重新自动选孔。`});const clearance=this.mountingHoleClearanceError(h,holes);if(clearance)issues.push({code:'board_mounting_invalid',instanceIds:[],holeIds:[h.id],message:`${h.id}：${clearance}`});const blockers=this.mountingObstructions(h);if(blockers.length&&!this.mountingSpareMode?.())issues.push({code:'mounting_hole_obstructed',instanceIds:blockers.map(i=>i.id),holeIds:[h.id],message:`${h.id} 安装沉孔被器件 ${blockers.map(i=>this.label(i)).join('、')} 遮挡，请移开器件或重新自动选孔。`});}
      for(let i=0;i<holes.length;i++)for(let j=i+1;j<holes.length;j++)if((holes.length!==8||(holes[i].columnIndex%2===holes[j].columnIndex%2&&holes[i].rowIndex%2===holes[j].rowIndex%2))&&['xMm','yMm'].some(axis=>{const n=(holes[i][axis]-holes[j][axis])/25;return Math.abs(n-Math.round(n))>EPS})){issues.push({code:'board_mounting_invalid',instanceIds:[],message:(holes.length===8?'每组':'')+'四个安装沉孔的横纵坐标差必须是 25 mm 的整数倍，请重新自动选孔。'});return issues;}return issues;
    }
    setMountingHoles(holes){this.cancelManualMounting(false);const before=this.historySnapshot();this.board.mountingHoles=holes.map(h=>({columnIndex:h.columnIndex,rowIndex:h.rowIndex}));this.commit(before);this.render()}
    manualMountingParity(){return {row:document.getElementById('mounting-row-parity')?.value||'any',column:document.getElementById('mounting-column-parity')?.value||'any'}}
    manualMountingError(hole,chosen=[]){
      const b=this.board,p=b.pitchMm,o=b.edgeOffsetMm,columns=Math.floor((b.widthMm-o*2)/p+EPS)+1,rows=Math.floor((b.heightMm-o*2)/p+EPS)+1;
      if(!Number.isInteger(hole.columnIndex)||!Number.isInteger(hole.rowIndex)||hole.columnIndex<0||hole.rowIndex<0||hole.columnIndex>=columns||hole.rowIndex>=rows)return '请点击面包板内的实际孔位。';
      if(b.thicknessMm<8.5)return 'M6 安装沉孔需要板厚至少 8.5 mm。';
      const x=o+hole.columnIndex*p,y=o+hole.rowIndex*p;
      if(Math.min(x,y,b.widthMm-x,b.heightMm-y)<7.5-EPS)return '沉孔中心距板边至少需要 7.5 mm，请选择更靠内的孔。';
      const parity=this.manualMounting?.parity||this.manualMountingParity();
      for(const [index,rule,label]of [[hole.rowIndex,parity.row,'行'],[hole.columnIndex,parity.column,'列']])if((this.manualMounting?.count||4)!==8&&rule!=='any'&&((index+1)%2===1)!==(rule==='odd'))return `当前只使用${rule==='odd'?'奇数':'偶数'}${label}，请按所选条件点孔。`;
      for(const previous of chosen){
        if(previous.columnIndex===hole.columnIndex&&previous.rowIndex===hole.rowIndex)continue;
        if(this.manualMounting?.count===8&&(previous.columnIndex%2!==hole.columnIndex%2||previous.rowIndex%2!==hole.rowIndex%2))continue;
        if([hole.columnIndex-previous.columnIndex,hole.rowIndex-previous.rowIndex].some(delta=>Math.abs(delta*p/25-Math.round(delta*p/25))>EPS))return '与已选孔的水平、竖直间距必须都是 25 mm 的整数倍。';
      }
      // Counterbores may have zero extra wall; ordinary holes retain the 2 mm web.
      const clearance=this.mountingHoleClearanceError(hole,chosen);if(clearance)return clearance;
      const blockers=this.mountingObstructions({xMm:x,yMm:y});
      if(blockers.length&&!this.mountingSpareMode?.())return `这个孔被器件 ${blockers.map(i=>this.label(i)).join('、')} 遮挡，请换一个孔。`;
      return '';
    }
    beginManualMounting(){
      if(this.boardFormDirty){this.notify('请先更新面包板参数，再手动选孔。',true);return}
      if(this.board.thicknessMm<8.5){this.notify('M6 安装沉孔需要板厚至少 8.5 mm。',true);return}
      if(this.manualMounting){this.cancelManualMounting();return}
      this.pendingKitId=null;this.manualMounting={holes:clone(this.board.mountingHoles||[]),parity:this.manualMountingParity(),count:Number(document.getElementById('mounting-count')?.value||4),source:JSON.stringify(this.snapshot())};
      this.keyboardActive=true;document.getElementById('mounting-settings').open=false;this.render();
      this.viewport.scrollIntoView({behavior:'smooth',block:'nearest'});this.svg.focus({preventScroll:true});
      document.dispatchEvent(new CustomEvent('layout-validity-change'));
    }
    cancelManualMounting(render=true){
      if(!this.manualMounting)return;this.manualMounting=null;
      if(render){this.render();document.dispatchEvent(new CustomEvent('layout-validity-change'))}
    }
    pickManualMounting(point){
      const draft=this.manualMounting;if(!draft)return false;
      if(this.boardFormDirty||draft.source!==JSON.stringify(this.snapshot())){this.cancelManualMounting();this.notify('画布已改变，请重新开启手动选孔。',true);return false}
      const b=this.board,columnIndex=Math.round((point.xMm-b.edgeOffsetMm)/b.pitchMm),rowIndex=Math.round((point.yMm-b.edgeOffsetMm)/b.pitchMm),hole={columnIndex,rowIndex};
      const x=b.edgeOffsetMm+columnIndex*b.pitchMm,y=b.edgeOffsetMm+rowIndex*b.pitchMm;
      if(Math.hypot(point.xMm-x,point.yMm-y)>Math.min(b.pitchMm*.42,6)){this.notify('请点在孔位附近；可以先放大画布。',true);return false}
      const index=draft.holes.findIndex(h=>h.columnIndex===columnIndex&&h.rowIndex===rowIndex);
      if(index>=0)draft.holes.splice(index,1);
      else{
        if(draft.holes.length>=(draft.count||4)){this.notify('已达到所选孔数；先点击一个已选孔取消，再选择新孔。',true);return false}
        const error=this.manualMountingError(hole,draft.holes);if(error){this.notify(error,true);return false}
        draft.holes.push(hole);
      }
      this.render();return true;
    }
    applyManualMounting(){
      const draft=this.manualMounting;if(!draft)return false;
      if(this.boardFormDirty||draft.source!==JSON.stringify(this.snapshot())){this.cancelManualMounting();this.notify('画布已改变，请重新开启手动选孔。',true);return false}
      if(draft.holes.length!==(draft.count||4)||new Set(draft.holes.map(h=>`${h.columnIndex},${h.rowIndex}`)).size!==(draft.count||4)){this.notify('请先选满当前模式要求的不同孔位。',true);return false}
      if(draft.count===8&&window.ZZLabStackMath?.eightError(draft.holes)){this.notify(window.ZZLabStackMath.eightError(draft.holes),true);return false}
      for(const hole of draft.holes){const error=this.manualMountingError(hole,draft.holes);if(error){this.notify(error,true);return false}}
      const setError=this.manualMountingSetError?.(draft.holes);if(setError){this.notify(setError,true);return false}
      const holes=clone(draft.holes).sort((a,b)=>a.rowIndex-b.rowIndex||a.columnIndex-b.columnIndex);
      this.setMountingHoles(holes);document.dispatchEvent(new CustomEvent('layout-validity-change'));this.notify('已应用手动选择的 M6 安装沉孔，可撤销恢复。');return true;
    }
    renderManualMounting(scene){
      if(this.manualMounting&&(this.boardFormDirty||this.manualMounting.source!==JSON.stringify(this.snapshot())))this.manualMounting=null;
      const draft=this.manualMounting,bar=document.getElementById('mounting-manual-bar');if(bar)bar.hidden=!draft;
      const button=document.getElementById('mounting-manual');if(button){button.setAttribute?.('aria-pressed',String(Boolean(draft)));textContent(button,draft?'退出手动选孔':'手动选孔')}
      this.viewport.classList.toggle('manual-mounting-active',Boolean(draft));
      attrs(scene.mountings,{display:draft?'none':'inline'});
      if(!scene.manualMountingLayer&&draft)scene.manualMountingLayer=svgNode('g',{class:'manual-mounting-layer','pointer-events':'none'},scene.sceneRoot||this.svg);
      if(!scene.manualMountingLayer)return;
      attrs(scene.manualMountingLayer,{display:draft?'inline':'none'});if(!draft)return;
      const error=new Set(draft.holes.map(h=>`${h.columnIndex},${h.rowIndex}`)).size!==draft.holes.length?'孔位重复，请重新选择不同的安装孔。':draft.holes.map(h=>this.manualMountingError(h,draft.holes)).find(Boolean)||window.ZZLabStackMath?.eightError(draft.holes)||(draft.holes.length===(draft.count||4)&&this.manualMountingSetError?.(draft.holes));
      textContent(document.getElementById('mounting-manual-status'),`手动选孔 · 已选 ${draft.holes.length} / ${draft.count||4}${error?' · '+error:''}`);
      document.getElementById('mounting-manual-apply').disabled=draft.holes.length!==(draft.count||4)||Boolean(error);
      const key=JSON.stringify([this.board,draft.holes]);if(scene.manualMountingKey===key)return;scene.manualMountingKey=key;
      scene.manualMountingLayer.replaceChildren();
      draft.holes.forEach((h,index)=>{const x=this.board.edgeOffsetMm+h.columnIndex*this.board.pitchMm,y=this.board.heightMm-this.board.edgeOffsetMm-h.rowIndex*this.board.pitchMm,g=svgNode('g',{transform:`translate(${x} ${y})`},scene.manualMountingLayer);svgNode('circle',{r:5.5},g);svgNode('circle',{r:3.3,class:'manual-mounting-center'},g);svgNode('text',{x:7,y:-6},g,`H${index+1}`)});
    }
    geometrySignature(){
      const engine=this.collisionEngine(),metadata=Array.from(new Set(this.instances.map(i=>i.kitId))).map(id=>{const kit=this.kits.get(id),l=kit?.layout||{};return engine?[id,kit?.name,l.placementAllowed,l.topViewUrl,l.widthMm,l.heightMm,l.anchorXMm,l.anchorYMm,l.baseBoundsMm,l.mountingHoleOffsetsMm,l.mountingHoleRadiusMm,l.minimumAlignedMountingHoles,l.baseOverhangAllowedWithPartialMounting,l.manualMountingPolicy,l.sourceAlignmentReference,l.opticalPortsMm]:[id,kit?.name,l]});
      // Small manufacturing/anchor metadata is included by value: imports and in-place
      // hole/base edits must invalidate validation without serializing large contours.
      return JSON.stringify([this.board,this.isReferenceSurface(),this.instances.map(i=>[i.id,i.kitId,i.xMm,i.yMm,i.rotationDeg,i.manualMount]),engine?.revision,metadata]);
    }
    validation(){const signature=this.geometrySignature();if(this._validationCache?.signature===signature)return this._validationCache.result;
      this.renderStats??={};this.renderStats.validationRuns=(this.renderStats.validationRuns||0)+1;
      const engine=this.collisionEngine(),pairLookup=engine?new Map():null,instanceLookup=new Map(this.instances.map(i=>[i.id,i]));if(engine)for(const [a,b]of engine.update(this.instances).pairs){if(!pairLookup.has(b))pairLookup.set(b,[]);pairLookup.get(b).push(a)}
      const issues=[],bounds=[],mountingAlignment=[];for(const i of this.instances){const name=`${this.label(i)} ${this.kits.get(i.kitId).name}`;const manual=window.ZZLabManualSourceMount?.reference(this.kits.get(i.kitId)?.layout);if(!manual&&!this.anchorGrid(i).known&&[[i.xMm,this.board.widthMm],[i.yMm,this.board.heightMm]].some(([value,limit])=>{const grid=(value-this.board.edgeOffsetMm)/this.board.pitchMm;return value<this.board.edgeOffsetMm-EPS||value>limit-this.board.edgeOffsetMm+EPS||Math.abs(grid-Math.round(grid))>EPS}))issues.push({code:'off_grid',instanceIds:[i.id],message:`${name} 的安装锚点未落在当前格点。`});if(this.outOfBounds(i))issues.push({code:'out_of_bounds',instanceIds:[i.id],message:`${name} 的底座越出面包板边缘；上部器件可以悬出。`});if(this.kits.get(i.kitId)?.layout?.placementAllowed===false||!this.kitLayout(i).actual)issues.push({code:'placement_unavailable',instanceIds:[i.id],message:`${name} 的摆放资料待补齐。`});const offsets=this.kits.get(i.kitId)?.layout?.mountingHoleOffsetsMm;
        if(manual){const g=this.kits.get(i.kitId).layout;if(window.ZZLabManualSourceMount.acceptedHeight(i,g)===null)issues.push({code:'manual_mount_unconfirmed',instanceIds:[i.id],message:'请在光学设置中填写手调后板面光轴高并确认人工支撑和名义出光参考。'});const p=this.worldPoint(i,manual);if(!this.isReferenceSurface()&&!window.ZZLabRegisteredBoards.isHole(this.board,p,this.catalog))issues.push({code:'source_reference_off_grid',instanceIds:[i.id],message:'出光口XY参考未对齐本板已有孔列；该参考不是安装孔。'});}else if(!Array.isArray(offsets)||!offsets.length)issues.push({code:'mounting_unconfirmed',instanceIds:[i.id],message:`${name} 的安装孔位置尚未确认。`});
        else{const alignment=this.mountingAlignment(i);if(alignment)mountingAlignment.push(alignment);if(!alignment||alignment.alignedCount<alignment.requiredCount)issues.push({code:'mounting_mismatch',instanceIds:[i.id],message:alignment&&this.kits.get(i.kitId)?.layout?.minimumAlignedMountingHoles!=null?`${name} 的安装孔已对齐 ${alignment.alignedCount}/${alignment.totalCount}，至少需要 ${alignment.requiredCount} 个不同的孔，请调整孔距或位置。`:`${name} 的安装孔没有全部对准板孔，请调整孔距或位置。`});}
        const polygons=pairLookup?null:this.worldPolygons(i),b=pairLookup?null:pointsBounds(polygons.flat()),colliders=pairLookup?(pairLookup.get(i.id)||[]).map(id=>instanceLookup.get(id)):bounds.filter(other=>boxesTouch(b,other.box)&&polygons.some(p=>other.polygons.some(q=>polygonsTouch(p,q)))).map(other=>other.instance);for(const other of colliders)issues.push({code:'collision',instanceIds:[other.id,i.id],message:`器件 ${this.label(other)} 与 ${this.label(i)} 的碰撞轮廓相交或接触。`});if(!pairLookup)bounds.push({instance:i,box:b,polygons});}issues.push(...this.mountingIssues());const result={valid:!issues.length,issues,mountingAlignment};this._validationCache={signature:this.geometrySignature(),result};return result}
    mountingMarkerMarkup(i){if(this.kits.get(i.kitId)?.layout?.minimumAlignedMountingHoles==null)return'';const grid=this.anchorGrid({...i,rotationDeg:0});if(!grid.known)return'';return grid.offsets.map(h=>{const point=this.worldPoint(i,h),aligned=this.partialMountingMinimum(i)&&!this.isReferenceSurface()?window.ZZLabRegisteredBoards.isMountingHole(this.board,point,this.catalog):this.isBoardHole(point.xMm,point.yMm),color=aligned?'#168550':'#d6811a';return`<circle class="mounting-alignment-marker" data-aligned="${aligned}" cx="${h.xMm}" cy="${-h.yMm}" r="3.6" fill="none" stroke="${color}" stroke-width="1" pointer-events="none"><title>${aligned?'安装孔已对齐':'安装孔未对齐'}</title></circle>`}).join('')}
    boundaryMarkup(i){const base=this.localBounds(i,'base');return this.localPolygons(i).map(p=>`<polygon class="collision-boundary" points="${p.map(v=>`${v.xMm},${-v.yMm}`).join(' ')}"/>`).join('')+`<rect class="base-boundary" x="${base.xMin}" y="${-base.yMax}" width="${base.xMax-base.xMin}" height="${base.yMax-base.yMin}"/>`+this.mountingMarkerMarkup(i)}
    contentBounds(){const all=[{xMm:0,yMm:0},{xMm:this.board.widthMm,yMm:this.board.heightMm}];for(const i of this.instances){const l=this.kitLayout(i);all.push(...rectPoints({xMin:-l.ax-5,yMin:l.ay-l.height-10,xMax:l.width-l.ax+5,yMax:l.ay+5}).map(p=>this.worldPoint(i,p)),...this.worldPolygons(i).flat())}return pointsBounds(all)}
    label(i){return String(this.instances.indexOf(i)+1).padStart(2,'0')}
    fit(){const w=this.viewport.clientWidth||700,h=this.viewport.clientHeight||560,aspect=w/h,pad=25,b=this.contentBounds();let vw=b.xMax-b.xMin+pad*2,vh=b.yMax-b.yMin+pad*2;if(vw/vh<aspect)vw=vh*aspect;else vh=vw/aspect;this.view={x:(b.xMin+b.xMax-vw)/2,y:this.board.heightMm-(b.yMin+b.yMax+vh)/2,w:vw,h:vh};this.renderView()}
    zoom(factor,point){const v=this.view;if(!v)return;const nw=v.w/factor;if(nw<30||nw>10000)return;const px=point?.x??v.x+v.w/2,py=point?.y??v.y+v.h/2,fx=(px-v.x)/v.w,fy=(py-v.y)/v.h;this.view={x:px-nw*fx,y:py-v.h/factor*fy,w:nw,h:v.h/factor};this.renderView()}
    world(e){const pt=this.svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(this.svg.getScreenCTM().inverse());return{x:p.x,y:p.y,xMm:p.x,yMm:this.board.heightMm-p.y}}
    imageMarkup(i){const k=this.kits.get(i.kitId),l=this.kitLayout(i);return l.actual?`<image href="${esc(l.url)}" x="${-l.ax}" y="${-l.ay}" width="${l.width}" height="${l.height}" preserveAspectRatio="none"/>`:`<rect class="missing-image" x="${-l.ax}" y="${-l.ay}" width="${l.width}" height="${l.height}" rx="2"/><text class="missing-image-text" x="0" y="0" text-anchor="middle">俯视图待补</text>`}
    ensureScene(){
      if(this._scene)return this._scene;
      this.renderStats??={};this.renderStats.sceneBuilds=(this.renderStats.sceneBuilds||0)+1;
      const defs=svgNode('defs',{},this.svg),holePattern=svgNode('pattern',{id:'hole-pattern',patternUnits:'userSpaceOnUse'},defs),holeDot=svgNode('circle',{fill:'#9aaa9d',stroke:'#758679','stroke-width':'.25'},holePattern);
      const outsidePattern=svgNode('pattern',{id:'outside-grid',patternUnits:'userSpaceOnUse'},defs),outsidePath=svgNode('path',{fill:'none',stroke:'#d5ded8','stroke-width':'.15'},outsidePattern),shadow=svgNode('filter',{id:'board-shadow',x:'-10%',y:'-10%',width:'130%',height:'130%'},defs);
      svgNode('feDropShadow',{dx:0,dy:2,stdDeviation:2,'flood-opacity':'.1'},shadow);
      const outside=svgNode('rect',{fill:'url(#outside-grid)'},this.svg),sceneRoot=svgNode('g',{'data-active-board':''},this.svg),board=svgNode('rect',{class:'breadboard',x:0,y:0,rx:3,filter:'url(#board-shadow)'},sceneRoot),holes=svgNode('rect',{fill:'url(#hole-pattern)'},svgNode('g',{class:'board-holes'},sceneRoot));
      const rulers=svgNode('g',{class:'board-rulers'},sceneRoot),widthLabel=svgNode('text',{'text-anchor':'middle'},rulers),heightLabel=svgNode('text',{'text-anchor':'middle'},rulers),rulerPath=svgNode('path',{},rulers),originLabel=svgNode('text',{x:0,class:'origin-label'},rulers,'(0, 0)');
      const parts=svgNode('g',{id:'placed-parts'},sceneRoot),boundaries=svgNode('g',{class:'boundary-layer'},sceneRoot),mountings=svgNode('g',{class:'mounting-layer'},sceneRoot),marquee=svgNode('rect',{class:'selection-marquee',display:'none'},sceneRoot);
      this._scene={sceneRoot,holePattern,holeDot,outsidePattern,outsidePath,outside,board,holes,rulers,widthLabel,heightLabel,rulerPath,originLabel,parts,boundaries,mountings,marquee,partNodes:new Map(),mountingNodes:new Map()};return this._scene;
    }
    renderView(){
      if(!this.svg||!this.view)return;
      if(!this._scene){this.render();return}
      const s=this._scene,v=this.view;attrs(this.svg,{viewBox:`${v.x} ${v.y} ${v.w} ${v.h}`});attrs(s.outside,{x:v.x,y:v.y,width:v.w,height:v.h});attrs(s.rulers,{'font-size':Math.max(2.8,Math.min(5.5,v.w/150))});
      this.svg.classList.toggle('placing',!!this.pendingKitId);this.svg.classList.toggle('panning',this.space||this.drag?.mode==='pan');
      textContent(document.getElementById('layout-zoom-label'),`${Math.round((this.board.widthMm+50)/v.w*100)}%`);
      this.renderStats.viewUpdates=(this.renderStats.viewUpdates||0)+1;
    }
    renderBoard(s){
      const b=this.board,key=JSON.stringify([b.widthMm,b.heightMm,b.pitchMm,b.edgeOffsetMm]);if(s.boardKey===key)return;s.boardKey=key;
      const radius=Math.min(1.4,b.pitchMm/8),lastX=b.edgeOffsetMm+Math.floor((b.widthMm-b.edgeOffsetMm*2)/b.pitchMm)*b.pitchMm,lastY=b.edgeOffsetMm+Math.floor((b.heightMm-b.edgeOffsetMm*2)/b.pitchMm)*b.pitchMm;
      attrs(s.holePattern,{x:b.edgeOffsetMm-b.pitchMm/2,y:b.heightMm-b.edgeOffsetMm-b.pitchMm/2,width:b.pitchMm,height:b.pitchMm});attrs(s.holeDot,{cx:b.pitchMm/2,cy:b.pitchMm/2,r:radius});attrs(s.outsidePattern,{width:b.pitchMm,height:b.pitchMm});attrs(s.outsidePath,{d:`M ${b.pitchMm} 0 L 0 0 0 ${b.pitchMm}`});attrs(s.board,{width:b.widthMm,height:b.heightMm});
      attrs(s.holes,{x:Math.max(0,b.edgeOffsetMm-radius),y:Math.max(0,b.heightMm-lastY-radius),width:lastX-b.edgeOffsetMm+radius*2,height:lastY-b.edgeOffsetMm+radius*2});
      attrs(s.widthLabel,{x:b.widthMm/2,y:b.heightMm+10});textContent(s.widthLabel,`${b.widthMm} mm`);attrs(s.heightLabel,{x:-10,y:b.heightMm/2,transform:`rotate(-90 -10 ${b.heightMm/2})`});textContent(s.heightLabel,`${b.heightMm} mm`);attrs(s.rulerPath,{d:`M0 ${b.heightMm+3}v3H${b.widthMm}v-3M-3 0h-3v${b.heightMm}h3`});attrs(s.originLabel,{y:b.heightMm+17});this.renderStats.boardUpdates=(this.renderStats.boardUpdates||0)+1;
    }
    createPartNodes(i,s){
      const l=this.kitLayout(i),layout=this.kits.get(i.kitId)?.layout,group=svgNode('g',{'data-instance':i.id,role:'button',tabindex:0},s.parts),title=svgNode('title',{},group);
      const rect={x:-l.ax-1.5,y:-l.ay-1.5,width:l.width+3,height:l.height+3,rx:1.5};svgNode('rect',{class:'part-hitarea',...rect},group);
      let image=null;if(l.actual){image=svgNode('image',{href:l.url,x:-l.ax,y:-l.ay,width:l.width,height:l.height,preserveAspectRatio:'none'},group);this.renderStats.imageCreates=(this.renderStats.imageCreates||0)+1}else{svgNode('rect',{class:'missing-image',x:-l.ax,y:-l.ay,width:l.width,height:l.height,rx:2},group);svgNode('text',{class:'missing-image-text',x:0,y:0,'text-anchor':'middle'},group,'俯视图待补')}
      svgNode('rect',{class:'part-outline',...rect},group);const upright=svgNode('g',{},group);svgNode('circle',{class:'anchor-point',r:1.7},upright);svgNode('path',{class:'anchor-cross',d:'M-3 0H3M0-3V3'},upright);const number=svgNode('g',{class:'part-number',transform:`translate(0 ${Math.max(l.height/2+3,8)})`},upright);svgNode('rect',{x:-4.4,y:-3.1,width:8.8,height:6.2,rx:2},number);const label=svgNode('text',{'text-anchor':'middle','dominant-baseline':'central','font-size':4},number);
      const boundary=svgNode('g',{},s.boundaries);for(const polygon of this.localPolygons(i))svgNode('polygon',{class:'collision-boundary',points:polygon.map(v=>`${v.xMm},${-v.yMm}`).join(' ')},boundary);const base=this.localBounds(i,'base');svgNode('rect',{class:'base-boundary',x:base.xMin,y:-base.yMax,width:base.xMax-base.xMin,height:base.yMax-base.yMin},boundary);
      const record={group,title,image,upright,label,boundary,layout,polygons:layout?.collisionPolygonsMm,base:layout?.baseBoundsMm,collision:layout?.collisionBoundsMm,kitId:i.kitId,assetKey:JSON.stringify(l),baseKey:JSON.stringify(base)};s.partNodes.set(i.id,record);this.renderStats.partCreates=(this.renderStats.partCreates||0)+1;return record;
    }
    renderParts(s,validation){
      const invalidIds=new Set(validation.issues.flatMap(issue=>issue.instanceIds)),outIds=new Set(validation.issues.filter(issue=>issue.code==='out_of_bounds').flatMap(issue=>issue.instanceIds)),activeIds=new Set(this.instances.map(i=>i.id));
      for(const [id,node]of s.partNodes)if(!activeIds.has(id)){node.group.remove();node.boundary.remove();s.partNodes.delete(id)}
      const orderKey=JSON.stringify(this.instances.map(i=>i.id)),orderChanged=s.orderKey!==orderKey;
      for(let index=0;index<this.instances.length;index++){
        const i=this.instances[index],layout=this.kits.get(i.kitId)?.layout;let node=s.partNodes.get(i.id);
        if(node&&(node.kitId!==i.kitId||node.layout!==layout||node.polygons!==layout?.collisionPolygonsMm||node.base!==layout?.baseBoundsMm||node.collision!==layout?.collisionBoundsMm||node.assetKey!==JSON.stringify(this.kitLayout(i))||node.baseKey!==JSON.stringify(this.localBounds(i,'base')))){node.group.remove();node.boundary.remove();s.partNodes.delete(i.id);node=null}
        const created=!node;if(!node)node=this.createPartNodes(i,s);
        const selected=this.selectedIds.has(i.id),invalid=invalidIds.has(i.id),transform=`translate(${i.xMm} ${this.board.heightMm-i.yMm}) rotate(${-i.rotationDeg})`,label=String(index+1).padStart(2,'0'),name=this.kits.get(i.kitId).name;
        attrs(node.group,{class:`placed-part${selected?' selected':''}${outIds.has(i.id)?' out-of-bounds':''}${invalid?' invalid-placement':''}`,transform,'aria-pressed':selected,'aria-label':`${label} ${name}，X ${i.xMm} Y ${i.yMm}，${i.rotationDeg} 度`});attrs(node.boundary,{class:invalid?'invalid-placement':'',transform});attrs(node.upright,{transform:`rotate(${i.rotationDeg})`});textContent(node.title,`${label} ${name}`);textContent(node.label,label);
        if(layout?.minimumAlignedMountingHoles!=null||node.mountingMarkers){if(!node.mountingMarkers)node.mountingMarkers=svgNode('g',{'pointer-events':'none'},node.boundary);htmlContent(node.mountingMarkers,this.mountingMarkerMarkup(i))}
        // Reordering is exceptional (import/undo); ordinary movement never detaches images.
        if(orderChanged||created){s.parts.appendChild(node.group);s.boundaries.appendChild(node.boundary)}
      }
      s.orderKey=orderKey;
    }
    renderMountings(s,validation){
      const mounting=this.mountingPositions(),alignment=validation.subBoardMountingAlignment?.find(r=>r.boardId===this.activeBoardId),states=new Map((alignment?.holes||[]).map(h=>[h.id,h])),issues=validation.issues.filter(i=>(!this.stacked||(i.boardId||null)===(this.activeBoardId||null))&&(i.code.startsWith('board_mounting_')||i.code==='mounting_hole_obstructed'||i.code==='sub_board_mounting_mismatch'||i.code==='sub_board_mounting_insufficient')),badHoles=new Set(issues.flatMap(i=>i.holeIds||[])),key=JSON.stringify([this.board.heightMm,mounting,Array.from(badHoles),issues.map(i=>i.message),alignment]);if(s.mountingKey===key)return;s.mountingKey=key;
      const ids=new Set(mounting.map(h=>h.id));for(const [id,node]of s.mountingNodes)if(!ids.has(id)){node.group.remove();s.mountingNodes.delete(id)}
      for(const h of mounting){let node=s.mountingNodes.get(h.id);if(!node){const group=svgNode('g',{},s.mountings),title=svgNode('title',{},group);svgNode('circle',{class:'mounting-counterbore',r:5.5},group);svgNode('circle',{class:'mounting-through',r:3.3},group);svgNode('path',{d:'M-7 0H7M0-7V7'},group);svgNode('text',{x:7,y:-5,'font-size':4},group,h.id);node={group,title};s.mountingNodes.set(h.id,node)}const state=states.get(h.id),spare=!this.board.registeredBoardId&&mounting.length===8&&state?.spare;attrs(node.group,{class:`mounting-hole${badHoles.has(h.id)?' obstructed':spare?' spare':''}`,style:spare&&!badHoles.has(h.id)?'stroke:#b4771c':'','data-spare':String(Boolean(spare)),transform:`translate(${h.xMm} ${this.board.heightMm-h.yMm})`});textContent(node.title,`${h.id} · ${h.holeId?'源孔 '+h.holeId:'第 '+(h.rowIndex+1)+' 行第 '+(h.columnIndex+1)+' 列'} · X ${h.xMm} Y ${h.yMm} mm${spare?' · 备用孔'+(state.obstructed?'（被器件轮廓遮挡）':'（未与大板对齐）'):alignment?' · 可用固定孔':''}`)}
      textContent(document.getElementById('mounting-settings-summary'),mounting.length?`已设置 ${mounting.length} 个${this.board.registeredBoardId?(window.ZZLabRegisteredBoards?.recordFor(this.board,this.catalog)?.customMountingHoles?'自选沉孔':'原板固定孔'):' M6 安装沉孔'}${alignment?` · ${alignment.usableCount} 个可用固定孔`:""}`:(window.ZZLabRegisteredBoards?.recordFor(this.board,this.catalog)?.customMountingHoles?'全螺纹孔 · 尚未选择沉孔':'四角安装沉孔 · 尚未设置'));document.getElementById('mounting-clear').disabled=!mounting.length;
      htmlContent(document.getElementById('mounting-results'),mounting.length?`<div class="mounting-result-grid">${mounting.map(h=>`<span class="${badHoles.has(h.id)?'blocked':''}"><strong>${h.id}${!this.board.registeredBoardId&&mounting.length===8&&states.get(h.id)?.spare?" · 备用":""}</strong> ${h.holeId?'源孔 '+esc(h.holeId):'第 '+(h.rowIndex+1)+' 行 · 第 '+(h.columnIndex+1)+' 列'}<br><small>X ${h.xMm} / Y ${h.yMm} mm</small></span>`).join('')}</div><p>${issues.length?'安装沉孔需要调整，请查看布局提示。':!this.board.registeredBoardId&&alignment&&mounting.length===8?`当前 ${alignment.usableCount} 个可用固定孔，至少需 4 个；备用孔仍全部加工。`:this.board.registeredBoardId?'仅使用源板已有的固定孔，没有新增加工孔。':'每组四孔的横纵坐标差均为 25 mm 的整数倍。'}</p>`:'<p>自动避开器件，寻找靠近四角的孔位。未设置时不加工安装沉孔。</p>');
    }
    renderMarquee(){const node=this._scene?.marquee;if(!node)return;const d=this.drag;if(d?.mode!=='marquee'){attrs(node,{display:'none'});return}attrs(node,{display:'inline',x:Math.min(d.start.x,d.current.x),y:Math.min(d.start.y,d.current.y),width:Math.abs(d.current.x-d.start.x),height:Math.abs(d.current.y-d.start.y)})}
    render(){
      if(!this.svg||!this.view)return;const s=this.ensureScene(),b=this.board;this.normalizeSelection();const selectedCount=this.selectedIds.size,validation=this.validation();
      this.renderView();this.renderBoard(s);this.renderParts(s,validation);this.renderMountings(s,validation);this.renderMarquee();this.renderManualMounting(s);
      const boardLabel=b.registeredBoardId?`${window.ZZLabRegisteredBoards.recordFor(b,this.catalog)?.name||'登记面包板'} · ${b.widthMm} × ${b.heightMm} × ${b.thicknessMm} mm · 源板孔位`:`${b.widthMm} × ${b.heightMm} × ${b.thicknessMm} mm · ${b.holeType==='M6_through'?'M6 通螺纹':'Ø'+b.holeDiameterMm+' 通孔'}`;
      textContent(document.getElementById('board-settings-summary'),`${boardLabel} · 孔距 ${b.pitchMm} mm`);textContent(document.getElementById('layout-board-label'),boardLabel);textContent(document.getElementById('layout-instance-count'),`${this.instances.length} 个套件${selectedCount?' · 选中 '+selectedCount+' 个':''}`);
      textContent(document.getElementById('layout-hint'),this.manualMounting?'手动选孔：点击孔位选择或取消 · 选满所选数量后应用 · Esc 取消 · 空格拖动平移':this.pendingKitId?`待放置：${this.kits.get(this.pendingKitId)?.name}。点击格点放下，Esc 取消。`:selectedCount>1?`已选 ${selectedCount} 个 · 拖动成员整体移动 · ⌘/Ctrl C、V 复制粘贴 · Esc 清选`:'⌘/Ctrl 或 Shift 点选多选 · Shift 拖空白框选 · 空白拖动平移');
      document.getElementById('rotate-part').disabled=selectedCount!==1;for(const id of ['duplicate-part','delete-part','copy-selection']){const button=document.getElementById(id);if(button)button.disabled=!selectedCount}const pasteButton=document.getElementById('paste-selection');if(pasteButton)pasteButton.disabled=!this.clipboard?.instances?.length;const selectAllButton=document.getElementById('select-all-parts');if(selectAllButton)selectAllButton.disabled=!this.instances.length;document.getElementById('layout-undo').disabled=!this.history.length;document.getElementById('layout-redo').disabled=!this.future.length;
      // Only changed validation reaches the inspector; pan/zoom and selection do not revalidate the plan.
      if(this._shownValidation!==validation){this._shownValidation=validation;const el=document.getElementById('layout-warning');el.hidden=validation.valid;el.classList.toggle('layout-invalid',!validation.valid);htmlContent(el,validation.valid?'':`<summary>布局不可用 · ${validation.issues.length} 项需要调整</summary><ul>${validation.issues.slice(0,50).map(issue=>`<li>${esc(issue.message)}</li>`).join('')}</ul><p>碰撞轮廓不能交汇；底座须在板内，允许边缘固定的器件须满足最少有效孔数。上部器件可悬出。普通面包板安装沉孔被遮挡时请重新选孔；位移台上板固定孔允许被覆盖。草稿仍可保存。</p>`);textContent(document.getElementById('layout-validity'),validation.valid?'布局可用':'布局不可用');document.getElementById('layout-validity').classList.toggle('invalid',!validation.valid);document.dispatchEvent(new CustomEvent('layout-validity-change'))}
    }
    downloadSvg(){const copy=this.svg.cloneNode(true);copy.setAttribute('xmlns',NS);copy.setAttribute('viewBox',`-20 -15 ${this.board.widthMm+40} ${this.board.heightMm+40}`);copy.setAttribute('width',`${this.board.widthMm+40}mm`);copy.setAttribute('height',`${this.board.heightMm+40}mm`);const style=document.createElementNS(NS,'style');style.textContent='.breadboard{fill:#fafbf9;stroke:#9eaaa0;stroke-width:.6}.board-holes{fill:#8b9b8e}.board-rulers{fill:#506457;stroke:none;font-family:sans-serif}.board-rulers path{stroke:#849489;stroke-width:.4;fill:none}.part-hitarea{fill:transparent}.part-outline,.anchor-cross,.anchor-point{display:none}.part-number rect{fill:#16736f}.part-number text{fill:white;font-family:sans-serif}.missing-image{fill:#fff4d9;stroke:#ac8a43;stroke-dasharray:2 1}.missing-image-text{font-size:3px;fill:#8b6829;font-family:sans-serif}';copy.insertBefore(style,copy.firstChild);return copy}
    keyboardContext(e){if(!this.keyboardActive)return false;if(e.target.closest?.('input,select,textarea,[contenteditable]:not([contenteditable="false"])'))return false;if(String(window.getSelection?.()?.toString()||'').trim())return false;const active=document.activeElement;return Boolean(e.target.closest?.('#layout-panel,#plan-panel')||active?.closest?.('#layout-panel,#plan-panel')||(active===document.body&&this.keyboardActive))}
    handleKeydown(e){if(!this.keyboardContext(e))return;const key=e.key.toLowerCase(),mod=e.metaKey||e.ctrlKey,hasSelection=this.selectedInstances().length>0;
      if(this.manualMounting){
        if(e.key==='Escape'){e.preventDefault();this.cancelManualMounting();return}
        if(e.key==='Enter'){e.preventDefault();this.applyManualMounting();return}
        if(e.key===' '){e.preventDefault();this.space=true;this.renderView()}
        return;
      }
      if(e.key==='Escape'){e.preventDefault();this.cancelPointerFrame();if(this.drag?.mode==='parts')this.restoreHistory(this.drag.before);const pointer=this.drag?.pointer;this.drag=null;if(pointer!==undefined&&this.svg.hasPointerCapture(pointer))this.svg.releasePointerCapture(pointer);this.pendingKitId=null;this.select(null);return}
      if(mod&&key==='a'){e.preventDefault();this.selectAll();return}
      if(mod&&key==='c'&&hasSelection){e.preventDefault();this.copySelection();return}
      if(mod&&key==='v'&&this.clipboard){e.preventDefault();this.pasteSelection();return}
      if(mod&&key==='d'&&hasSelection){e.preventDefault();this.duplicate();return}
      if(mod&&key==='z'){e.preventDefault();e.shiftKey?this.redo():this.undo();return}
      if(mod&&key==='y'){e.preventDefault();this.redo();return}
      if((e.key==='Delete'||e.key==='Backspace')&&hasSelection){e.preventDefault();this.remove();return}
      if(key==='r'&&!mod&&this.selected()){e.preventDefault();this.rotate();return}
      const moves={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,1],ArrowDown:[0,-1]};if(moves[e.key]&&hasSelection){e.preventDefault();this.move(...moves[e.key].map(value=>value*this.board.pitchMm));return}
      if(e.key===' '&&(this.viewport.contains(document.activeElement)||document.activeElement===document.body)){this.space=true;e.preventDefault();this.renderView()}
    }
    cancelPointerFrame(){if(this._pointerFrame!=null&&window.cancelAnimationFrame)window.cancelAnimationFrame(this._pointerFrame);this._pointerFrame=null;this._pendingPointer=null}
    queuePointerMove(e){
      if(!this.drag||e.pointerId!==this.drag.pointer)return;
      this._pendingPointer={clientX:e.clientX,clientY:e.clientY,pointerId:e.pointerId};
      if(!window.requestAnimationFrame){this.flushPointerMove();return}
      if(this._pointerFrame==null)this._pointerFrame=window.requestAnimationFrame(()=>{this._pointerFrame=null;const latest=this._pendingPointer;this._pendingPointer=null;if(latest)this.applyPointerMove(latest)});
    }
    flushPointerMove(finalEvent=null){
      const latest=finalEvent&&Number.isFinite(finalEvent.clientX)&&Number.isFinite(finalEvent.clientY)?{clientX:finalEvent.clientX,clientY:finalEvent.clientY,pointerId:finalEvent.pointerId}:this._pendingPointer;
      this.cancelPointerFrame();if(latest)this.applyPointerMove(latest);
    }
    applyPointerMove(e){
      const d=this.drag;if(!d||e.pointerId!==d.pointer)return;this.renderStats??={};this.renderStats.pointerFrames=(this.renderStats.pointerFrames||0)+1;
      if(d.mode==='pan'){
        const rect=this.svg.getBoundingClientRect(),dx=(e.clientX-d.lastX)/rect.width*this.view.w,dy=(e.clientY-d.lastY)/rect.height*this.view.h;if(!dx&&!dy)return;d.lastX=e.clientX;d.lastY=e.clientY;this.view.x-=dx;this.view.y-=dy;d.moved=true;this.renderView();return;
      }
      const p=this.world(e);
      if(d.mode==='parts'){
        if(Math.hypot(e.clientX-d.startClient.x,e.clientY-d.startClient.y)>3)d.moved=true;
        if(d.moved){const delta=this.commonDelta(d.originals,p.x-d.start.x,d.start.y-p.y),key=`${delta.xMm},${delta.yMm}`;if(d.deltaKey===key)return;d.deltaKey=key;this.applyGroupDelta(d.originals,delta.xMm,delta.yMm);this.render();textContent(document.getElementById('layout-coordinate'),`整组移动 · ${d.originals.length} 个`)}
      }else if(d.mode==='marquee'){
        if(d.current.x===p.x&&d.current.y===p.y)return;d.current=p;d.moved=true;this.selectInRect({xMin:Math.min(d.start.xMm,p.xMm),xMax:Math.max(d.start.xMm,p.xMm),yMin:Math.min(d.start.yMm,p.yMm),yMax:Math.max(d.start.yMm,p.yMm)},{additive:true,initialIds:d.initialIds});
      }
    }
    bind(){
      document.getElementById('mounting-manual')?.addEventListener('click',()=>this.beginManualMounting());
      document.getElementById('mounting-manual-apply')?.addEventListener('click',()=>this.applyManualMounting());
      document.getElementById('mounting-manual-cancel')?.addEventListener('click',()=>this.cancelManualMounting());
      document.getElementById('mounting-manual-reset')?.addEventListener('click',()=>{if(this.manualMounting){this.manualMounting.holes=[];this.render()}});
      for(const id of ['mounting-row-parity','mounting-column-parity'])document.getElementById(id)?.addEventListener('change',()=>{if(this.manualMounting){this.manualMounting.parity=this.manualMountingParity();this.render()}});
      document.getElementById('board-form').addEventListener('input',()=>{this.boardFormDirty=true;document.getElementById('board-draft-note').hidden=false;document.getElementById('board-hole-diameter-field').hidden=document.getElementById('board-hole-type').value!=='plain_through';document.dispatchEvent(new CustomEvent('layout-validity-change'))});
      document.getElementById('board-form').addEventListener('submit',e=>{e.preventDefault();const next=this.normalizeBoard({widthMm:document.getElementById('board-width').value,heightMm:document.getElementById('board-height').value,pitchMm:document.getElementById('board-pitch').value,edgeOffsetMm:document.getElementById('board-offset').value,thicknessMm:document.getElementById('board-thickness').value,holeType:document.getElementById('board-hole-type').value,holeDiameterMm:document.getElementById('board-hole-diameter').value,mountingHoles:this.board.mountingHoles||[]});const errors=this.boardErrors(next);if(errors.length){this.notify(errors.join(' '),true);return}const before=this.historySnapshot();this.board=next;for(const i of this.instances)Object.assign(i,this.snap(i.xMm,i.yMm,i));this.syncFields();this.commit(before);document.getElementById('board-settings').open=false;this.fit();this.notify('面包板已更新；板本体将计入生产清单。')});
      document.getElementById('layout-undo').onclick=()=>this.undo();document.getElementById('layout-redo').onclick=()=>this.redo();document.getElementById('layout-fit').onclick=()=>this.fit();document.getElementById('layout-zoom-in').onclick=()=>this.zoom(1.25);document.getElementById('layout-zoom-out').onclick=()=>this.zoom(.8);document.getElementById('rotate-part').onclick=()=>this.rotate();document.getElementById('duplicate-part').onclick=()=>this.duplicate();document.getElementById('delete-part').onclick=()=>this.remove();
      for(const [id,handler]of [['copy-selection',()=>this.copySelection()],['paste-selection',()=>this.pasteSelection()],['select-all-parts',()=>this.selectAll()]])document.getElementById(id)?.addEventListener('click',handler);
      this.svg.addEventListener('keydown',e=>{const id=e.target.closest('[data-instance]')?.dataset.instance;if(id&&e.key==='Enter'){e.preventDefault();if(this.measurement)this.pickMeasurement(id);else this.select(id,{toggle:e.ctrlKey||e.metaKey||e.shiftKey})}});
      this.svg.addEventListener('wheel',e=>{e.preventDefault();this.zoom(e.deltaY<0?1.1:1/1.1,this.world(e))},{passive:false});
      this.svg.addEventListener('pointerdown',e=>{
        if(e.button!==0&&e.button!==1)return;if(this.measurePointer?.(e))return;if(this.handleUnifiedPointerDown?.(e))return;const point=this.world(e),id=e.target.closest('[data-instance]')?.dataset.instance;this.keyboardActive=true;
        if(this.manualMounting&&!this.space&&e.button===0){e.preventDefault();this.svg.focus({preventScroll:true});this.pickManualMounting(point);return}
        if(this.pendingKitId&&e.button===0){this.add(this.pendingKitId,point);return}
        if(id&&!this.measurement&&!this.space&&e.button===0){const modified=e.ctrlKey||e.metaKey||e.shiftKey,already=this.selectedIds.has(id),collapseOnClick=already&&this.selectedIds.size>1&&!modified?id:null;if(modified)this.select(id,{toggle:true});else if(!already)this.select(id);if(!this.selectedIds.has(id)){this.svg.focus({preventScroll:true});e.preventDefault();return}this.drag={mode:'parts',start:point,startClient:{x:e.clientX,y:e.clientY},before:this.historySnapshot(),originals:clone(this.selectedInstances()),pointer:e.pointerId,moved:false,collapseOnClick};}
        else if(e.shiftKey&&!this.measurement&&!this.space&&e.button===0){this.drag={mode:'marquee',start:point,current:point,initialIds:Array.from(this.selectedIds),pointer:e.pointerId,moved:false};}
        else{if(!this.space&&e.button===0)this.select(null);this.drag={mode:'pan',start:point,lastX:e.clientX,lastY:e.clientY,view:clone(this.view),pointer:e.pointerId,moved:false};}
        this.svg.setPointerCapture(e.pointerId);this.svg.focus({preventScroll:true});e.preventDefault();this.render();
      });
      this.svg.addEventListener('pointermove',e=>this.queuePointerMove(e));
      const end=e=>{if(!this.drag||e.pointerId!==this.drag.pointer)return;const d=this.drag;if(e.type==='pointercancel')this.cancelPointerFrame();else this.flushPointerMove(e);this.drag=null;if(d.mode==='module'){if(e.type==='pointercancel'){this.restoreHistory(d.before);this.changed()}else this.commit(d.before)}if(d.mode==='parts'){if(e.type==='pointercancel'){this.restoreHistory(d.before);this.changed()}else if(!d.moved&&d.collapseOnClick)this.select(d.collapseOnClick);else this.commit(d.before)}if(this.svg.hasPointerCapture(e.pointerId))this.svg.releasePointerCapture(e.pointerId);if(d.mode==='pan'){this.renderView();this.renderMarquee()}else this.render()};this.svg.addEventListener('pointerup',end);this.svg.addEventListener('pointercancel',end);
      this.viewport.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('application/x-zzlab-kit')||e.dataTransfer.types.includes('application/x-zzlab-registered-board')){e.preventDefault();e.dataTransfer.dropEffect='copy';this.viewport.classList.add('drop-target')}});this.viewport.addEventListener('dragleave',e=>{if(!this.viewport.contains(e.relatedTarget))this.viewport.classList.remove('drop-target')});this.viewport.addEventListener('drop',e=>{const registered=e.dataTransfer.getData('application/x-zzlab-registered-board');if(registered){e.preventDefault();this.viewport.classList.remove('drop-target');try{this.addRegisteredBoard(registered,this.sceneWorld?this.sceneWorld(e):this.world(e))}catch(error){this.notify(error.message,true)}return;}const id=e.dataTransfer.getData('application/x-zzlab-kit');if(!this.kits.has(id))return;e.preventDefault();this.viewport.classList.remove('drop-target');this.placeAtEvent?this.placeAtEvent(id,e):this.add(id,this.world(e))});
      document.addEventListener('pointerdown',e=>{const path=e.composedPath?.()||[];this.keyboardActive=path.some(node=>node?.id==='layout-panel'||node?.id==='plan-panel')||Boolean(e.target.closest?.('#layout-panel,#plan-panel'))});
      document.addEventListener('focusin',e=>{this.keyboardActive=Boolean(e.target.closest?.('#layout-panel,#plan-panel'))});
      document.addEventListener('keydown',e=>this.handleKeydown(e));document.addEventListener('keyup',e=>{if(e.key===' '){this.space=false;this.renderView()}});

    }
  }
  window.BreadboardEditor=BreadboardEditor;
  window.ZZLabLayoutGeometry={polygonsTouch,circleTouchesPolygon,rectPoints,pointsBounds};
  window.ZZLabRegisteredBoards?.installBase(BreadboardEditor);
})();
