/* Pure canvas-combination transforms. The caller applies the returned project as
 * one history transaction. This module never changes a source project or DOM.
 * Board/grid/base fit is checked; collisions remain editable layout feedback.
 */
(function(root,factory){
  const api=factory(typeof module==='object'&&module.exports?require('./project-file.js'):root.ZZLabProjectFile,root);
  if(typeof module==='object'&&module.exports)module.exports=api;else root.ZZLabSharedProject=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(codec,root){
  'use strict';
  const R=typeof module==='object'&&module.exports?require('./registered-boards.js'):root.ZZLabRegisteredBoards;
  const Adapter=typeof module==='object'&&module.exports?require('./laser-adapter.js'):root.ZZLabLaserAdapter;
  const Manual=typeof module==='object'&&module.exports?require('./manual-source-mount.js'):root.ZZLabManualSourceMount;
  const EPS=1e-5,clone=value=>JSON.parse(JSON.stringify(value));
  class SharedProjectError extends Error{constructor(code,message){super(message);this.name='SharedProjectError';this.code=code}}
  const fail=(code,message)=>{throw new SharedProjectError(code,message)};
  function optionsFor(options){if(!codec)fail('missing_codec','工程读取工具尚未准备好。');return{catalog:options.catalog,validateBoard:options.validateBoard,...(options.now?{now:options.now}:{})}}
  function read(project,options){const parsed=codec.parse(project,optionsFor(options));if(parsed.legacy)fail('unsupported_format','共享组合需要完整的新版工程文件。');return parsed.project}
  // Input has already passed the strict project codec. An exemption belongs to
  // these two instances only, never to a kit type or a replacement instance.
  function retainedOverrides(layout,ids){return layout.collisionOverrides===undefined?{}:{collisionOverrides:layout.collisionOverrides.filter(row=>row.instanceIds.every(id=>ids.has(id)))}}
  function subset(project,ids=null,options={}){
    const source=read(project,options),partial=ids!==null;
    if(partial&&(!Array.isArray(ids)||ids.some(id=>typeof id!=='string')||new Set(ids).size!==ids.length))fail('invalid_selection','请选择不重复的画布实例。');
    const allowed=new Set(source.layout.instances.map(i=>i.id)),selected=new Set(partial?ids:allowed);
    if([...selected].some(id=>!allowed.has(id)))fail('unknown_instance','选中器件已不存在，请重新选择。');
    const instances=source.layout.instances.filter(i=>selected.has(i.id)),overrides=retainedOverrides(source.layout,selected);
    if(!instances.length&&!source.layout.subBoards?.some(p=>p.stageMotion))fail('empty_combination','请先在画布上放置或选中至少一个器件。');
    const kids=new Set(instances.map(i=>i.kitId));
    source.layout.instances=instances;
    source.optical=Object.fromEntries(Object.entries(source.optical).filter(([key])=>selected.has(key.slice(0,key.lastIndexOf('::')))));
    source.extras=source.extras.filter(e=>e.instanceId?selected.has(e.instanceId):e.kitId===null?!partial:kids.has(e.kitId));
    // Standalone module cards are not members of a canvas combination.
    source.moduleQuantities=[];source.ui.selectedIds=instances.map(i=>i.id);
    if(partial){
      if(source.layout.subBoards){const owners=new Set(instances.map(i=>i.boardId||null));if(owners.size!==1)fail('mixed_boards','请在同一块面包板上选择要发布的器件。');const owner=[...owners][0],plate=owner?source.layout.subBoards.find(p=>p.id===owner):null,board=plate?plate.board:source.layout.board;if(plate?.stageMotion){source.layout={baseMode:'table',board:source.layout.board,subBoards:[clone(plate)],instances}}else source.layout={...(!owner&&source.layout.baseMode?{baseMode:source.layout.baseMode}:{}),board:clone(board),instances:instances.map(({boardId,...i})=>i)}}
      if(!source.layout.board.registeredBoardId)source.layout.board.mountingHoles=[];source.ui.mountingSelection={rowParity:'any',columnParity:'any'}
    }
    Object.assign(source.layout,overrides);
    return codec.create(source,optionsFor(options));
  }
  function extractBoard(current,boardId,options={}){
    const source=read(current,options),plate=source.layout.subBoards?.find(p=>p.id===boardId);
    if(!plate)fail('unknown_board','请选择要保存的小面包板。');
    const ids=source.layout.instances.filter(i=>i.boardId===boardId).map(i=>i.id);if(plate.stageMotion){const selected=new Set(ids);source.layout={baseMode:'table',board:source.layout.board,subBoards:[clone(plate)],instances:source.layout.instances.filter(i=>selected.has(i.id)),...retainedOverrides(source.layout,selected)};source.optical=Object.fromEntries(Object.entries(source.optical).filter(([key])=>selected.has(key.slice(0,key.lastIndexOf('::')))));const childKits=new Set(source.layout.instances.map(i=>i.kitId));source.extras=source.extras.filter(e=>e.instanceId?selected.has(e.instanceId):e.kitId!==null&&childKits.has(e.kitId));source.moduleQuantities=[];source.ui.selectedIds=ids;source.ui.view=null;source.metadata.name=plate.name;return codec.create(source,optionsFor(options))}const result=subset(source,ids,options);
    result.layout.board=clone(plate.board);result.metadata.name=plate.name;result.ui.view=null;
    result.metadata.moduleElevation=Object.fromEntries(['elevationMm','elevationSupportCount'].filter(key=>plate[key]!==undefined).map(key=>[key,plate[key]]));
    return codec.create(result,optionsFor(options));
  }
  const gridAligned=(value,offset,pitch)=>Math.abs((value-offset)/pitch-Math.round((value-offset)/pitch))<=EPS;
  function kitBounds(kit){
    const l=kit.layout||{},b=l.baseBoundsMm;
    if(b&&['xMin','yMin','xMax','yMax'].every(k=>Number.isFinite(b[k]))&&b.xMax>b.xMin&&b.yMax>b.yMin)return b;
    const width=Number(l.widthMm)||25,height=Number(l.heightMm)||25;
    const ax=Number.isFinite(Number(l.anchorXMm))?Number(l.anchorXMm):width/2,ay=Number.isFinite(Number(l.anchorYMm))?Number(l.anchorYMm):height/2;
    return{xMin:-ax,yMin:ay-height,xMax:width-ax,yMax:ay};
  }
  function rotated(point,instance){const angle=instance.rotationDeg*Math.PI/180,c=Math.round(Math.cos(angle)),s=Math.round(Math.sin(angle));return{xMm:instance.xMm+point.xMm*c-point.yMm*s,yMm:instance.yMm+point.xMm*s+point.yMm*c}}
  function fitOffset(instances,sourceBoard,targetBoard,kits,requested,reference=false,catalog){
    if(!reference&&R&&instances.some(i=>R.partialMountingMinimum(kits.get(i.kitId)?.layout))){
      if(requested!==undefined&&(!requested||typeof requested!=='object'||Array.isArray(requested)||Object.keys(requested).some(k=>!['xMm','yMm'].includes(k))||!['xMm','yMm'].every(k=>Number.isFinite(requested[k]))))fail('invalid_offset','组合平移量应为有限的 X、Y 毫米数。');
      if(!sourceBoard.registeredBoardId&&!targetBoard.registeredBoardId&&Math.abs(sourceBoard.pitchMm-targetBoard.pitchMm)>EPS)fail('incompatible_pitch','共享组合与当前面包板的孔距不同，不能直接整组加入。');
      const offsets=i=>{const l=kits.get(i.kitId)?.layout||{},data=Adapter?.enabled(i)?Adapter.spec({board:sourceBoard,instances},i,{kits:[...kits.values()]}):null,raw=data?data.spec.boardMountingHolesMm:Manual?.reference(l)?[Manual.reference(l)]:l.mountingHoleOffsetsMm;if(data&&!data.beamAligned)fail('incompatible_mounting','共享激光器的出光线未与孔阵行列对齐，请先调整光轴垫板。');if(l.placementAllowed===false||!l.topViewUrl||!(l.widthMm>0)||!(l.heightMm>0))fail('placement_unavailable','共享组合包含尚不能放到画布上的套件。');if(!Array.isArray(raw)||!raw.length||raw.some(p=>!Number.isFinite(p.xMm)||!Number.isFinite(p.yMm)))fail('mounting_unconfirmed','共享组合包含安装孔位置尚未确认的套件。');const unique=[];for(const p of raw){const point=rotated(p,{...i,xMm:0,yMm:0});if(!unique.some(h=>Math.hypot(h.xMm-point.xMm,h.yMm-point.yMm)<EPS))unique.push(point)}return unique},minimum=i=>Adapter?.enabled(i)?4:kits.get(i.kitId).layout.minimumAlignedMountingHoles??offsets(i).length;
      const fits=delta=>instances.every(i=>{if(R.partialMountingMinimum(kits.get(i.kitId)?.layout))return true;const b=kitBounds(kits.get(i.kitId)),poly=[{xMm:b.xMin,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMax},{xMm:b.xMin,yMm:b.yMax}].map(p=>rotated(p,{...i,xMm:i.xMm+delta.xMm,yMm:i.yMm+delta.yMm}));return R.containsPolygon(targetBoard,poly,catalog)});
      const delta=R.snapMountedDelta(targetBoard,instances,offsets,minimum,requested||{xMm:25,yMm:25},catalog,fits);if(!delta)fail('group_does_not_fit','当前面包板找不到符合每个器件安装孔要求的位置；边缘固定至少需要所要求数量的有效螺纹孔。');return delta;
    }
    if(R&&(sourceBoard.registeredBoardId||targetBoard.registeredBoardId)){
      if(requested!==undefined&&(!requested||!Number.isFinite(requested.xMm)||!Number.isFinite(requested.yMm)))fail('invalid_offset','组合平移量应为有限的 X、Y 毫米数。');
      const offsets=i=>{const g=kits.get(i.kitId)?.layout||{},port=Manual?.reference(g),raw=port?[port]:g.mountingHoleOffsetsMm;if(!Array.isArray(raw)||!raw.length)fail('mounting_unconfirmed','共享组合包含安装孔位置尚未确认的套件。');return raw.map(p=>rotated(p,{...i,xMm:0,yMm:0}))};
      const fits=delta=>instances.every(i=>{const b=kitBounds(kits.get(i.kitId)),poly=[{xMm:b.xMin,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMax},{xMm:b.xMin,yMm:b.yMax}].map(p=>rotated(p,{...i,xMm:i.xMm+delta.xMm,yMm:i.yMm+delta.yMm}));return R.containsPolygon(targetBoard,poly,catalog)}),desired=requested||{xMm:25,yMm:25},delta=reference?desired:R.snapDelta(targetBoard,instances,offsets,desired,catalog,fits);
      if(!fits(delta))fail('group_does_not_fit','整个组合的底座放不进当前板的真实轮廓，请调整位置或连同原板加入。');
      if(!reference)for(const i of instances){const points=offsets(i),minimum=kits.get(i.kitId)?.layout?.minimumAlignedMountingHoles??points.length;if(points.filter(h=>R.isHole(targetBoard,{xMm:i.xMm+delta.xMm+h.xMm,yMm:i.yMm+delta.yMm+h.yMm},catalog,{threadOnly:true,excludeMounting:true})).length<minimum)fail('incompatible_mounting','当前板的实际螺纹孔不能同时配合这个组合；请连同原板加入。');}
      return delta;
    }
    const p=targetBoard.pitchMm,o=targetBoard.edgeOffsetMm;
    if(!reference&&Math.abs(p-sourceBoard.pitchMm)>EPS)fail('incompatible_pitch','共享组合与当前面包板的孔距不同，不能直接整组加入。');
    const lastX=o+Math.floor((targetBoard.widthMm-2*o)/p)*p,lastY=o+Math.floor((targetBoard.heightMm-2*o)/p)*p;
    const limits={xMin:-Infinity,xMax:Infinity,yMin:-Infinity,yMax:Infinity};
    for(const i of instances){
      const kit=kits.get(i.kitId),l=kit?.layout||{};
      if(l.placementAllowed===false||typeof l.topViewUrl!=='string'||!l.topViewUrl.trim()||!(Number(l.widthMm)>0&&Number(l.heightMm)>0))fail('placement_unavailable','共享组合包含尚不能放到画布上的套件。');
      // The instance origin is an optical/base datum, not necessarily a screw
      // hole. Fit only the physical base and the rotated mounting holes.
      const b=kitBounds(kit),corners=[{xMm:b.xMin,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMax},{xMm:b.xMin,yMm:b.yMax}].map(point=>rotated(point,i));
      limits.xMin=Math.max(limits.xMin,-Math.min(...corners.map(v=>v.xMm)));limits.xMax=Math.min(limits.xMax,targetBoard.widthMm-Math.max(...corners.map(v=>v.xMm)));
      limits.yMin=Math.max(limits.yMin,-Math.min(...corners.map(v=>v.yMm)));limits.yMax=Math.min(limits.yMax,targetBoard.heightMm-Math.max(...corners.map(v=>v.yMm)));
      if(reference)continue;
      const manualPort=Manual?.reference(l);
      if(manualPort){
        const output=rotated(manualPort,i);
        if(!gridAligned(output.xMm,sourceBoard.edgeOffsetMm,p)||!gridAligned(output.yMm,sourceBoard.edgeOffsetMm,p))fail('source_reference_off_grid','人工光源名义出光参考未对齐原板孔列；请先定位，再组合。');
        limits.xMin=Math.max(limits.xMin,o-output.xMm);limits.xMax=Math.min(limits.xMax,lastX-output.xMm);
        limits.yMin=Math.max(limits.yMin,o-output.yMm);limits.yMax=Math.min(limits.yMax,lastY-output.yMm);
        continue;
      }
      if(i.laserAdapter?.enabled){
        const port=l.opticalPortsMm?.[0];
        if(!port)fail('mounting_unconfirmed','激光器未登记出光口位置。');
        const output=rotated(port,i),horizontal=i.rotationDeg%180===0;
        if(!gridAligned(horizontal?output.yMm:output.xMm,sourceBoard.edgeOffsetMm,p))fail('incompatible_mounting','共享激光器的出光线未与孔阵行列对齐，请先调整光轴垫板。');
        // The adapter's separate board holes follow the board phase. Original
        // laser mounting holes attach to the adapter, not to this grid.
        continue;
      }
      if(!Array.isArray(l.mountingHoleOffsetsMm)||!l.mountingHoleOffsetsMm.length)fail('mounting_unconfirmed','共享组合包含安装孔位置尚未确认的套件。');
      const distinct=[];
      for(const point of l.mountingHoleOffsetsMm){
        if(!Number.isFinite(point.xMm)||!Number.isFinite(point.yMm))fail('mounting_unconfirmed','共享组合的安装孔位置无效。');
        if(!distinct.some(h=>Math.abs(h.xMm-point.xMm)<=EPS&&Math.abs(h.yMm-point.yMm)<=EPS))distinct.push(point);
      }
      const minimum=l.minimumAlignedMountingHoles,required=minimum==null?distinct.length:Number.isInteger(minimum)&&minimum>=1&&minimum<=128?minimum:Infinity;
      // Preserve a source's already aligned two-dimensional hole group. A common
      // board-phase translation keeps those actual holes aligned for every member;
      // unmatched holes must not impose a contradictory phase or a false fit bound.
      const aligned=distinct.map(point=>rotated(point,i)).filter(hole=>gridAligned(hole.xMm,sourceBoard.edgeOffsetMm,p)&&gridAligned(hole.yMm,sourceBoard.edgeOffsetMm,p));
      if(aligned.length<required)fail('incompatible_mounting','共享组合的安装孔未达到所需对齐数量，与当前孔距不兼容。');
      for(const hole of aligned){
        limits.xMin=Math.max(limits.xMin,o-hole.xMm);limits.xMax=Math.min(limits.xMax,lastX-hole.xMm);
        limits.yMin=Math.max(limits.yMin,o-hole.yMm);limits.yMax=Math.min(limits.yMax,lastY-hole.yMm);
      }
    }
    if(requested!==undefined&&(!requested||typeof requested!=='object'||Array.isArray(requested)||Object.keys(requested).some(k=>!['xMm','yMm'].includes(k))||!['xMm','yMm'].every(k=>Number.isFinite(requested[k]))))fail('invalid_offset','组合平移量应为有限的 X、Y 毫米数。');
    const result={};
    for(const [axis,min,max]of[['xMm',limits.xMin,limits.xMax],['yMm',limits.yMin,limits.yMax]]){
      const phase=o-sourceBoard.edgeOffsetMm,low=Math.ceil((min-phase-EPS)/p),high=Math.floor((max-phase+EPS)/p);
      if(low>high)fail('group_does_not_fit','当前面包板放不下整个组合，请增大面包板；组内间距不会被改变。');
      // One common grid-compatible translation: never independently clamp members.
      const desired=requested?requested[axis]:phase+p;
      result[axis]=phase+Math.max(low,Math.min(high,Math.round((desired-phase)/p)))*p;
    }
    return result;
  }
  function idFactory(options,used){return(kind,original)=>{
    for(let tries=0;tries<100;tries++){
      const id=options.newId?options.newId(kind,original):root.crypto?.randomUUID?`shared-${kind}-${root.crypto.randomUUID()}`:fail('missing_uuid','当前环境无法生成新的器件编号。');
      if(typeof id!=='string'||!id.trim()||id!==id.trim()||id.length>80||id.includes('::')||id.startsWith('module:')||['__proto__','prototype','constructor'].includes(id))fail('invalid_id_generator','新的器件编号无效。');
      if(!used.has(id)){used.add(id);return id}
    }
    fail('duplicate_id_generator','无法生成不重复的器件编号，请重试。');
  }}
  function merge(current,shared,options={}){
    const target=read(current,options),source=subset(shared,null,options),incoming=source.layout.instances;
    if(target.layout.instances.length+incoming.length>codec.MAX_INSTANCES)fail('too_many_instances','加入后超过500个器件，未修改当前工程。');
    if(target.layout.subBoards||source.layout.subBoards)fail('stacked_merge','多板工程请使用装入模块或打开工程。');
    const kits=new Map(options.catalog.kits.map(k=>[k.id,k])),offsetMm=fitOffset(incoming,source.layout.board,target.layout.board,kits,options.offsetMm,target.layout.baseMode==='table',options.catalog);
    const result=combineParts(target,source,options,offsetMm);
    result.project=codec.create(result.project,optionsFor(options));return result;
  }
  // Both operations share identity and accessory bookkeeping. Only a component-
  // only merge fits geometry to the destination grid; a mounted board keeps its
  // source coordinates, including editable drafts that still need validation.
  function combineParts(target,source,options,offsetMm){
    const incoming=source.layout.instances,kits=new Map(options.catalog.kits.map(k=>[k.id,k]));
    if(target.layout.instances.length+incoming.length>codec.MAX_INSTANCES)fail('too_many_instances','加入后超过500个器件，未修改当前工程。');
    const kids=new Set(incoming.map(i=>i.kitId)),currentInstances=target.layout.instances.slice();
    // Expansion can multiply a kit-scoped row by hundreds of instances. Reject
    // its final size before allocating all rows or generating replacement IDs.
    let extraCount=0;
    for(const e of target.extras){
      const owners=!e.instanceId&&e.kitId!==null&&kids.has(e.kitId)?currentInstances.filter(i=>i.kitId===e.kitId):null;
      if(owners&&!owners.length)fail('inactive_template_conflict',`当前工程为【${kits.get(e.kitId).name}】预存了每套配件，请先放置该器件或调整这项配件，再加入共享套件；也可打开共享工程。`);
      extraCount+=owners?owners.length:1;
    }
    for(const e of source.extras)extraCount+=e.instanceId||e.kitId===null?1:incoming.filter(i=>i.kitId===e.kitId).length;
    if(extraCount>2000)fail('too_many_extras','加入后补充配件超过2000项，未修改当前工程。请减少每套配件配置后重试。');
    if(Object.keys(target.optical).length+Object.keys(source.optical).length>2000)fail('too_many_optical','加入后光学选配超过2000项，未修改当前工程。');
    const used=new Set([...target.layout.instances,...source.layout.instances,...target.extras,...source.extras].map(e=>e.id)),fresh=idFactory(options,used),mapping=incoming.map(i=>({fromId:i.id,toId:fresh('instance',i.id)})),mapped=new Map(mapping.map(m=>[m.fromId,m.toId]));
    const added=incoming.map(i=>({...clone(i),id:mapped.get(i.id),xMm:i.xMm+offsetMm.xMm,yMm:i.yMm+offsetMm.yMm})),warnings=[];
    // Freeze current per-kit extras onto their existing instances first. Otherwise
    // they would unintentionally apply to the newly inserted same-kit members.
    const extras=[];
    for(const e of target.extras){
      if(e.instanceId||e.kitId===null||!kids.has(e.kitId)){extras.push(e);continue}
      const owners=currentInstances.filter(i=>i.kitId===e.kitId);
      for(const i of owners)extras.push({...e,id:fresh('extra',e.id),instanceId:i.id});
    }
    for(const e of source.extras){
      const owners=e.instanceId?added.filter(i=>i.id===mapped.get(e.instanceId)):e.kitId===null?[added[0]]:added.filter(i=>i.kitId===e.kitId);
      for(const i of owners)extras.push({...e,id:fresh('extra',e.id),kitId:i.kitId,instanceId:i.id});
    }
    target.extras=extras;target.layout.instances.push(...added);
    if(target.layout.collisionOverrides!==undefined||source.layout.collisionOverrides!==undefined)target.layout.collisionOverrides=[...(target.layout.collisionOverrides||[]),...(source.layout.collisionOverrides||[]).map(row=>({instanceIds:row.instanceIds.map(id=>mapped.get(id))}))];
    for(const [key,value]of Object.entries(source.optical)){const split=key.lastIndexOf('::'),id=mapped.get(key.slice(0,split));if(id)target.optical[id+key.slice(split)]=clone(value)}
    target.ui.selectedIds=added.map(i=>i.id);
    return{project:target,insertedIds:added.map(i=>i.id),mapping,offsetMm,warnings};
  }
  function requireCarrier(board){if(![12.5,25].includes(board.pitchMm)||board.holeType!=='M6_through')fail('unsupported_carrier','当前面包板作为承载大板时，需要12.5或25 mm孔距的M6螺纹孔。请先更新面包板参数。')}
  function mount(current,shared,options={}){
    const target=read(current,options),source=subset(shared,null,options);
    const stage=source.layout.subBoards?.length===1&&source.layout.subBoards[0].stageMotion&&!source.layout.instances.some(i=>i.boardId!==source.layout.subBoards[0].id)?source.layout.subBoards[0]:null;
    if(source.layout.baseMode==='table'&&!stage)fail('source_without_board','此工程没有可连同安装的根面包板；请只加入器件，或先选中其中的小板模块。');
    if(!target.layout.subBoards)fail('missing_carrier','请先创建承载大面包板。');
    if(target.layout.baseMode!=='table')requireCarrier(target.layout.board);
    if(source.layout.subBoards&&!stage)fail('nested_carrier','装入模块请选择单块面包板工程；多板总装可用“打开工程”恢复。');
    if(target.layout.subBoards.length>=24)fail('too_many_boards','最多支持24块小面包板。');
    if(options.platePosition!==undefined&&(!options.platePosition||typeof options.platePosition!=='object'||Array.isArray(options.platePosition)||Object.keys(options.platePosition).some(k=>!['xMm','yMm'].includes(k))||!['xMm','yMm'].every(k=>Number.isFinite(options.platePosition[k]))))fail('invalid_offset','小板安装位置应为有限的X、Y毫米数。');
    if(stage){const S=typeof module==='object'&&module.exports?require('./moving-stages.js'):root.ZZLabMovingStages,m=S.moduleFor(stage,options.catalog),result=combineParts(target,source,options,{xMm:0,yMm:0}),used=new Set([...target.layout.subBoards,...target.layout.instances,...target.extras].map(i=>i.id)),pid=idFactory(options,used)('board',source.metadata.name),fixed={xMm:options.platePosition?.xMm??target.layout.board.widthMm/2,yMm:options.platePosition?.yMm??target.layout.board.heightMm/2,rotationDeg:stage.rotationDeg},plate={...clone(stage),id:pid,...S.topAtFixed(fixed,m,stage.stageMotion.qMm)};Object.assign(plate,S.snapPlate(target.layout.board,plate,options.catalog,target.layout.baseMode==='table'));const ids=new Set(result.insertedIds);result.project.layout={...result.project.layout,board:target.layout.board,subBoards:[...target.layout.subBoards,plate],instances:result.project.layout.instances.map(i=>({...i,...(ids.has(i.id)?{boardId:pid}:{})}))};result.project=codec.create(result.project,optionsFor(options));result.boardId=pid;return result;}
    const result=combineParts(target,source,options,{xMm:0,yMm:0}),used=new Set([...target.layout.subBoards,...target.layout.instances,...target.extras].map(i=>i.id)),pid=idFactory(options,used)('board',source.metadata.name);
    const ids=new Set(result.insertedIds),phase=target.layout.board.edgeOffsetMm-source.layout.board.edgeOffsetMm,registeredPose=source.layout.board.registeredBoardId&&R?R.snapPlate(target.layout.board,source.layout.board,{xMm:options.platePosition?.xMm||phase,yMm:options.platePosition?.yMm||phase,rotationDeg:0},options.catalog,target.layout.baseMode==='table'):null;
    result.project.layout={...result.project.layout,board:target.layout.board,subBoards:[...target.layout.subBoards,{id:pid,name:source.metadata.name,board:source.layout.board,...clone(source.metadata.moduleElevation||{}),xMm:registeredPose?registeredPose.xMm:options.platePosition?phase+Math.round((options.platePosition.xMm-phase)/12.5)*12.5:phase,yMm:registeredPose?registeredPose.yMm:options.platePosition?phase+Math.round((options.platePosition.yMm-phase)/12.5)*12.5:phase,rotationDeg:0}],instances:result.project.layout.instances.map(i=>({...i,...(ids.has(i.id)?{boardId:pid}:{} )}))};
    result.project=codec.create(result.project,optionsFor(options));result.boardId=pid;return result;
  }
  function mountOnBoard(current,shared,options={}){
    const target=read(current,options);if(target.layout.baseMode!=='table')requireCarrier(target.layout.board);
    if(!target.layout.subBoards)target.layout.subBoards=[];
    return mount(target,shared,options);
  }
  return Object.freeze({subset,merge,mount,mountOnBoard,extractBoard,SharedProjectError});
});
