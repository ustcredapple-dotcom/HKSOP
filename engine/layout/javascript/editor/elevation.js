/* Heights are measured from the top surface of the carrier breadboard. */
(function(root,factory){
  const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.ZZLabElevation=api;
  if(root.BreadboardEditor)api.install(root.BreadboardEditor,root);
})(typeof globalThis!=='undefined'?globalThis:this,function(root){
  'use strict';
  const apiManual=()=>typeof module==='object'&&module.exports?require('./manual-source-mount.js'):root.ZZLabManualSourceMount;
  const EPS=1e-5,copy=x=>JSON.parse(JSON.stringify(x)),round=x=>Math.round(x*1e6)/1e6;
  const stageApi=()=>typeof module==='object'&&module.exports?require('./moving-stages.js'):globalThis.ZZLabMovingStages;
  const boardSupportHeight=(p,catalog)=>p?(stageApi()?.supportHeight(p,catalog)??p.board.thicknessMm):0;
  const postSeries=p=>p.seriesId??'legacy-imperial';
  const postSeriesLabel=p=>postSeries(p)==='legacy-imperial'?'旧英制系列':postSeries(p)==='metric-12p5-r1'?'公制系列 · 12.5 mm 步进':`系列 ${postSeries(p)}`;
  const automaticAxisTarget=reference=>reference===null?null:round(Math.ceil((reference-EPS)/12.5)*12.5);
  const validElevation=x=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=1000&&Math.abs(x*1000-Math.round(x*1000))<EPS;
  const validCount=x=>Number.isInteger(x)&&x>=1&&x<=128;
  const elevation=x=>Number.isFinite(x?.elevationMm)?x.elevationMm:0;
  const mapOf=value=>value instanceof Map?value:new Map((value||[]).map(x=>[x.id,x]));
  function alignedCount(instance,kit,board,catalog){
    const holes=[],a=instance.rotationDeg*Math.PI/180,c=Math.round(Math.cos(a)),s=Math.round(Math.sin(a));
    for(const h of kit?.layout?.mountingHoleOffsetsMm||[]){if(!Number.isFinite(h.xMm)||!Number.isFinite(h.yMm)||holes.some(p=>Math.abs(p.xMm-h.xMm)<EPS&&Math.abs(p.yMm-h.yMm)<EPS))continue;holes.push(h)}
    if(board.registeredBoardId){const source=(catalog?.registeredBoards||[]).find(r=>r.id===board.registeredBoardId&&r.revision===board.registeredBoardRevision);return holes.filter(h=>source?.holesMm.some(p=>p.type==='thread'&&Math.hypot(p.xMm-instance.xMm-c*h.xMm+s*h.yMm,p.yMm-instance.yMm-s*h.xMm-c*h.yMm)<EPS)).length;}
    return holes.filter(h=>[[instance.xMm+c*h.xMm-s*h.yMm,board.widthMm],[instance.yMm+s*h.xMm+c*h.yMm,board.heightMm]].every(([v,size])=>{const n=(v-board.edgeOffsetMm)/board.pitchMm;return v>=board.edgeOffsetMm-1e-5&&v<=size-board.edgeOffsetMm+1e-5&&Math.abs(n-Math.round(n))<=1e-5})).length;
  }
  function supportCount(target,kit,board,isBoard=false,catalog){
    if(validCount(target.elevationSupportCount))return target.elevationSupportCount;
    if(isBoard)return (target.stageMotion?stageApi()?.moduleFor(target,catalog)?.lowerAttachmentHoles?.length:0)||target.board?.mountingHoles?.length||4;
    const minimum=kit?.layout?.minimumAlignedMountingHoles,mountedSource=Boolean(kit?.layout?.opticalPortsMm?.length)&&Number.isInteger(minimum)&&minimum>=2;
    if(kit?.id==='laser-308nm'||mountedSource){
      if(kit?.id==='laser-308nm'&&target.laserAdapter?.enabled===true)return 4;
      return Math.max(mountedSource?minimum:2,alignedCount(target,kit,board,catalog));
    }
    return 1;
  }
  function materialsFor(height,count,catalog,target){
    const spec=target&&(catalog.registeredBoards||[]).find(b=>b.id===target.board?.registeredBoardId)?.customElevationSupport;
    const component=spec&&(catalog.components||[]).find(c=>c.id===spec.componentId);
    if(component&&Math.abs(spec.heightMm-height)<EPS)return[{componentId:component.id,name:component.name,kind:component.kind,model:component.model,unit:component.unit,heightMm:height,quantityPerSupport:1,quantity:count}];
    const materials=[],definitions=catalog.elevationMaterials||{},components=mapOf(catalog.components);let remain=Math.round(height*10);
    for(const group of [definitions.posts||[],definitions.spacers||[]])for(const entry of [...group].sort((a,b)=>b.heightMm-a.heightMm)){
      const unit=Math.round(entry.heightMm*10);if(!(unit>0))continue;const quantityPerSupport=Math.floor(remain/unit);if(!quantityPerSupport)continue;remain-=quantityPerSupport*unit;
      const component=components.get(entry.componentId)||{};materials.push({componentId:entry.componentId,name:component.name||`${entry.heightMm} mm 垫高配件`,kind:component.kind||'lubang',model:component.model||'',unit:component.unit||'个',heightMm:entry.heightMm,quantityPerSupport,quantity:quantityPerSupport*count});
    }
    if(remain>0){const h=remain/10;materials.push({componentId:`elevation-shim-${String(h).replace('.','p')}`,name:`精密调整片 · ${h} mm`,kind:'standard',model:'待确认',unit:definitions.fractionalShim?.unit||'片',heightMm:h,quantityPerSupport:1,quantity:count})}
    return materials;
  }
  function externalAxisHeights(geometry){
    const assembly=geometry?.opticalAssembly;
    if(!assembly||typeof assembly!=='object'||Array.isArray(assembly)||!Object.prototype.hasOwnProperty.call(assembly,'externalAxisHeightsMm'))return null;
    const values=assembly.externalAxisHeightsMm,faceHeights=[];
    for(const node of Array.isArray(assembly.nodes)?assembly.nodes:[])for(const face of Array.isArray(node?.faces)?node.faces:[]){
      const center=face?.centerMm,z=Array.isArray(center)&&center.length===3?center[2]:!Array.isArray(center)&&center&&typeof center==='object'?center.z:null;
      if(typeof z==='number'&&Number.isFinite(z))faceHeights.push(z);
    }
    if(assembly.verified!==true||!Array.isArray(values)||values.length<2||values.length>16||values.some(h=>typeof h!=='number'||!Number.isFinite(h)||h<0||h>10000)||values.some((h,n)=>values.slice(n+1).some(z=>Math.abs(h-z)<=EPS))||values.some(h=>!faceHeights.some(z=>Math.abs(h-z)<=EPS))){
      const error=new Error('爬架外部光高必须属于已核实总装，包含 2–16 个有限、非负、互异且对应真实光学面中心 Z 的高度。');error.code='external_axis_heights_invalid';throw error;
    }
    return [...values];
  }
  function heightValidation(axisHeights){
    const known=axisHeights.filter(r=>r.effectiveAxisHeightMm!==null&&r.globalHeightComparable!==false),axisHeightReferenceMm=known.length?Math.max(...known.map(r=>r.effectiveAxisHeightMm)):null;
    let mismatched=known.filter(r=>Math.abs(r.effectiveAxisHeightMm-axisHeightReferenceMm)>EPS),connectedAxisHeightsMm=null;
    const converters=axisHeights.map(r=>r.effectiveExternalAxisHeightsMm).filter(r=>r?.length);
    if(axisHeightReferenceMm!==null&&converters.length){
      // Shared measured heights connect converters; unrelated converters do not
      // authorize arbitrary axes elsewhere. Ray hits still use the 3D engine.
      const values=[axisHeightReferenceMm,...known.map(r=>r.effectiveAxisHeightMm)],edges=[];
      for(const group of converters){const start=values.length;values.push(...group);for(let n=1;n<group.length;n++)edges.push([start,start+n]);}
      const parents=values.map((_,n)=>n),find=n=>{while(parents[n]!==n){parents[n]=parents[parents[n]];n=parents[n]}return n},join=(a,b)=>{parents[find(a)]=find(b)},ordered=values.map((_,n)=>n).sort((a,b)=>values[a]-values[b]);
      for(let n=1;n<ordered.length;n++)if(values[ordered[n]]-values[ordered[n-1]]<=EPS)join(ordered[n-1],ordered[n]);
      for(const [a,b] of edges)join(a,b);
      mismatched=known.filter((r,n)=>find(n+1)!==find(0));connectedAxisHeightsMm=[...new Set(values.filter((_,n)=>find(n)===find(0)))].sort((a,b)=>a-b);
    }
    const heightMismatches=connectedAxisHeightsMm===null?[]:mismatched.map(row=>{const actual=row.effectiveAxisHeightMm,nearest=connectedAxisHeightsMm.reduce((best,value)=>Math.abs(value-actual)<Math.abs(best-actual)?value:best);return{instanceId:row.instanceId,effectiveAxisHeightMm:actual,nearestConnectedAxisHeightMm:nearest,heightDifferenceMm:round(actual-nearest)}});
    let message=`光轴高度未齐平：当前最高为 ${axisHeightReferenceMm} mm；请设置元件或小板垫高，使已知光轴高度一致。`;
    if(heightMismatches.length){const groups=new Map();for(const row of heightMismatches){const key=JSON.stringify([row.effectiveAxisHeightMm,row.nearestConnectedAxisHeightMm,row.heightDifferenceMm]);groups.set(key,(groups.get(key)||0)+1)}const details=[...groups].slice(0,6).map(([key,count])=>{const [actual,nearest,delta]=JSON.parse(key);return`${actual} mm × ${count}（比兼容光高 ${nearest} mm ${delta>0?'高':'低'} ${Math.abs(delta)} mm）`}).join('；')+(groups.size>6?`；另有 ${groups.size-6} 组高差`:'');message=`已计入爬架光高转换，可连通光高：${[...connectedAxisHeightsMm].reverse().join(' / ')} mm。${mismatched.length} 个器件仍有光高差：${details}；请核对这些器件的柱高、转接块或小板垫高。`}
    const issues=mismatched.length?[{code:'axis_height_mismatch',instanceIds:mismatched.map(r=>r.instanceId),message,...(connectedAxisHeightsMm===null?{}:{heightMismatches,connectedAxisHeightsMm})}]:[];
    return {axisHeights,axisHeightReferenceMm,autoAxisHeightTargetMm:automaticAxisTarget(axisHeightReferenceMm),...(connectedAxisHeightsMm===null?{}:{connectedAxisHeightsMm}),issues};
  }
  function fixedUniversalPostIds(kit,posts){
    const geometry=kit?.layout;if(!geometry||!Object.prototype.hasOwnProperty.call(geometry,'fixedUniversalPostComponentIds'))return new Set();
    const fixed=geometry.fixedUniversalPostComponentIds,registered=new Set(posts.map(p=>p.componentId)),present=new Set((kit.components||[]).map(p=>p.componentId));
    if(!Array.isArray(fixed)||fixed.length>128||fixed.some(id=>typeof id!=='string'||!registered.has(id)||!present.has(id))||new Set(fixed).size!==fixed.length){
      const error=new Error('固定柱必须为不重复、属于该套件BOM且已登记柱系列的组件编号数组。');error.code='fixed_universal_posts_invalid';throw error;
    }
    return new Set(fixed);
  }
  function universalPostContext(layout,catalog,id){
    const instance=(layout.instances||[]).find(i=>i.id===id);if(!instance)return null;
    const selection=instance.universalPostSelection??{},explicit=Object.keys(selection).length>0;
    const kit=mapOf(catalog.kits).get(instance.kitId),components=mapOf(catalog.components),posts=(catalog.universalPostSeries?.posts||[]).filter(p=>typeof p.componentId==='string'&&Number.isFinite(p.heightMm)&&p.heightMm>0).sort((a,b)=>a.heightMm-b.heightMm||a.componentId.localeCompare(b.componentId)),byId=new Map(posts.map(p=>[p.componentId,p]));
    const fixed=fixedUniversalPostIds(kit,posts);
    if(instance.boardId&&!explicit)return null;
    const originals=(kit?.components||[]).filter(ref=>byId.has(ref.componentId)&&!fixed.has(ref.componentId)).map(ref=>({...byId.get(ref.componentId),quantity:ref.quantity,name:components.get(ref.componentId)?.name||ref.componentId}));
    if(!originals.length&&!explicit)return null;
    const malformed=!selection||typeof selection!=='object'||Array.isArray(selection)||Object.keys(selection).length>32||Object.entries(selection).some(([key,value])=>!originals.some(p=>p.componentId===key)||!byId.has(value));
    const bases=originals.map(p=>({...p,...byId.get(selection[p.componentId]||p.componentId),originalComponentId:p.componentId,originalHeightMm:p.heightMm})),deltas=bases.map(p=>round(p.heightMm-p.originalHeightMm));
    const fixedSelected=Object.keys(selection).some(id=>fixed.has(id));
    const issue=malformed||deltas.some(d=>Math.abs(d-deltas[0])>EPS)?{code:'invalid_post_selection',instanceIds:[id],message:fixedSelected?'固定横柱或非Z支撑柱不能通过垫高设置替换；请修改机械配置。':'换柱必须选用已登记的组件，并使同一套件所有支撑柱改变相同高度。'}:null;
    return{instance,kit,components,posts,originals,bases,explicit,postHeightDeltaMm:deltas[0]||0,issue};
  }
  function universalPostReplacement(layout,catalog,id,height){
    const context=universalPostContext(layout,catalog,id);if(!context)return null;
    if(context.issue)return{context,issue:context.issue,group:null};
    const materials=[],missing=[],increment=context.instance.boardId?0:height;
    for(const basis of context.bases){const targetHeightMm=round(basis.heightMm+increment),sameSeries=context.posts.filter(p=>postSeries(p)===postSeries(basis)),target=sameSeries.find(p=>Math.abs(p.heightMm-targetHeightMm)<=EPS);
      if(!target){const nearest=[...sameSeries].sort((a,b)=>Math.abs(a.heightMm-targetHeightMm)-Math.abs(b.heightMm-targetHeightMm)||a.heightMm-b.heightMm).slice(0,2).sort((a,b)=>a.heightMm-b.heightMm);missing.push(`${basis.name} 需要 ${targetHeightMm} mm 柱高，最近可选 ${nearest.map(p=>`${p.heightMm} mm`).join('、')||'暂无'}`);continue}
      const component=context.components.get(target.componentId)||{};materials.push({componentId:target.componentId,replacesComponentId:basis.originalComponentId,originalHeightMm:basis.originalHeightMm,name:component.name||target.componentId,kind:component.kind||'custom',model:component.model||'',unit:component.unit||'个',heightMm:target.heightMm,quantityPerSupport:basis.quantity,quantity:basis.quantity});
    }
    const issue=missing.length?{code:'universal_post_unavailable',instanceIds:[id],message:`${context.kit.name}：${missing.join('；')}。当前柱高系列无法精确实现此垫高，请选择已有柱高或调整目标光轴高度。`}:null;
    return{context,issue,group:!issue&&(increment>0||context.explicit)?{targetType:'instance',targetId:id,name:context.kit.name,mode:'universalPostReplacement',elevationMm:increment,supportCount:1,materials,...(context.explicit?{postHeightDeltaMm:context.postHeightDeltaMm}:{})}:null};
  }
  function universalPostChoices(layout,catalog,id){
    const context=universalPostContext(layout,catalog,id);if(!context||context.issue||context.instance.boardId)return[];const first=context.bases[0],own=context.kit.layout?.opticalAxisHeightMm,adapter=context.instance.laserAdapter?.enabled===true?context.instance.laserAdapter.thicknessMm:0;
    return context.posts.filter(p=>postSeries(p)===postSeries(first)&&p.heightMm>=first.heightMm-EPS).map(p=>({...p,elevationMm:round(p.heightMm-first.heightMm)})).filter(p=>validElevation(p.elevationMm)&&context.bases.every(basis=>context.posts.some(candidate=>postSeries(candidate)===postSeries(basis)&&Math.abs(candidate.heightMm-basis.heightMm-p.elevationMm)<=EPS))).map(p=>({...p,name:context.components.get(p.componentId)?.name||`${p.heightMm} mm 万能柱`,effectiveAxisHeightMm:Number.isFinite(own)?round(own+context.postHeightDeltaMm+p.elevationMm+(adapter||0)):null}));
  }
  function analyze(layout,catalog,{periscopeMode=false}={}){
    const kits=mapOf(catalog.kits),plates=new Map((layout.subBoards||[]).map(p=>[p.id,p])),axisHeights=[],issues=[],elevationAccessories=[],universalPostReplacements=[];
    const check=(target,type)=>{if(('elevationMm'in target&&!validElevation(target.elevationMm))||('elevationSupportCount'in target&&!validCount(target.elevationSupportCount)))issues.push({code:'invalid_elevation',instanceIds:type==='instance'?[target.id]:[],...(type==='board'?{boardId:target.id}:{}),message:'垫高高度需为 0–1000 mm，精确到 0.001 mm；支撑组数需为 1–128 的整数。'})};
    for(const p of plates.values()){check(p,'board');const h=elevation(p),count=supportCount(p,null,null,true,catalog);if(h>0&&!periscopeMode)elevationAccessories.push({targetType:'board',targetId:p.id,name:p.name,elevationMm:h,supportCount:count,materials:materialsFor(h,count,catalog,p)})}
    for(const i of layout.instances||[]){
      check(i,'instance');const kit=kits.get(i.kitId),plate=plates.get(i.boardId),board=plate?.board||layout.board,manual=apiManual()?.reference(kit?.layout),base=manual?apiManual().acceptedHeight(i,kit.layout):kit?.layout?.opticalAxisHeightMm,known=typeof base==='number'&&Number.isFinite(base)&&base>=0,boardElevationMm=elevation(plate),boardThicknessMm=plate?Number(board.thicknessMm)||0:0,stageHeightOffsetMm=stageApi()?.heightOffset(plate,catalog)||0,h=elevation(i),count=supportCount(i,kit,board,false,catalog),adapterThicknessMm=i.laserAdapter?.enabled===true&&Number.isFinite(i.laserAdapter.thicknessMm)?i.laserAdapter.thicknessMm:0;
      const external=externalAxisHeights(kit?.layout),replacement=universalPostReplacement(layout,catalog,i.id,periscopeMode?0:h);
      const requestedEffectiveAxisHeightMm=known?round(boardElevationMm+boardThicknessMm+stageHeightOffsetMm+h+base+adapterThicknessMm+(replacement?.context.postHeightDeltaMm||0)):null,heightResolved=!replacement?.issue;
      axisHeights.push({instanceId:i.id,kitId:i.kitId,boardId:plate?.id||null,opticalAxisHeightMm:known?base:null,...(manual&&known?{axisHeightEvidence:'user-confirmed-manual-alignment',catalogHeightVerified:false}:{}),boardElevationMm,boardThicknessMm,...(plate?.stageMotion?{stageHeightOffsetMm}:{}),elevationMm:h,elevationSupportCount:replacement&&!plate?replacement.context.originals.reduce((sum,p)=>sum+p.quantity,0):count,adapterThicknessMm,...(replacement?.context.explicit?{postHeightDeltaMm:replacement.context.postHeightDeltaMm}:{}),heightResolved,...(kit?.layout?.opticalAssembly?{globalHeightComparable:false}:{}),...(external?{effectiveExternalAxisHeightsMm:heightResolved?external.map(value=>round(value+boardElevationMm+boardThicknessMm+stageHeightOffsetMm+h+adapterThicknessMm+(replacement?.context.postHeightDeltaMm||0))):null}:{}),...(!heightResolved?{requestedEffectiveAxisHeightMm}:{}),effectiveAxisHeightMm:heightResolved?requestedEffectiveAxisHeightMm:null});
      if(replacement){if(replacement.issue)issues.push(replacement.issue);if(replacement.group){elevationAccessories.push(replacement.group);for(const m of replacement.group.materials)universalPostReplacements.push({instanceId:i.id,kitId:i.kitId,originalComponentId:m.replacesComponentId,replacementComponentId:m.componentId,originalHeightMm:m.originalHeightMm,replacementHeightMm:m.heightMm,elevationMm:plate?0:h,quantity:m.quantity,...(replacement.context.explicit?{selectedBaseComponentId:replacement.context.bases.find(b=>b.originalComponentId===m.replacesComponentId).componentId,postHeightDeltaMm:replacement.context.postHeightDeltaMm}:{})})}}
      if(!periscopeMode&&(!replacement||plate)&&h>0)elevationAccessories.push({targetType:'instance',targetId:i.id,name:kit?.name||i.kitId,elevationMm:h,supportCount:count,materials:materialsFor(h,count,catalog,p)});
    }
    const heights=periscopeMode?{axisHeights,axisHeightReferenceMm:null,autoAxisHeightTargetMm:null,issues:[]}:heightValidation(axisHeights);
    return{...heights,elevationAccessories,universalPostReplacements,issues:[...issues,...heights.issues]};
  }
  function autoElevation(layout,catalog,type,id,explicitTarget){
    const result=analyze(layout,catalog);
    if(explicitTarget===undefined&&result.connectedAxisHeightsMm){
      const connected=h=>h!==null&&result.connectedAxisHeightsMm.some(v=>Math.abs(v-h)<=EPS);
      const matches=row=>row.heightResolved!==false&&(row.globalHeightComparable===false?row.effectiveExternalAxisHeightsMm?.some(connected):connected(row.effectiveAxisHeightMm));
      if(type==='board'){
        const plate=(layout.subBoards||[]).find(p=>p.id===id),rows=result.axisHeights.filter(r=>r.boardId===id&&(r.opticalAxisHeightMm!==null||r.effectiveExternalAxisHeightsMm));
        if(plate&&validElevation(elevation(plate))&&rows.length&&rows.every(matches))return elevation(plate);
      }else{const row=result.axisHeights.find(r=>r.instanceId===id);if(row&&validElevation(row.elevationMm)&&matches(row))return row.elevationMm;}
    }
    let target=explicitTarget===undefined?result.autoAxisHeightTargetMm:explicitTarget;if(target!==null&&(!Number.isFinite(target)||target<0||target>10000||Math.abs(target*10-Math.round(target*10))>EPS))throw new Error('目标光轴须为0–10000 mm，精确到0.001 mm。');if(target===null)throw new Error('当前元件尚无已知光轴高度，不能自动计算垫高。');let height;
    const chooseConnectedTarget=(base,current)=>{if(explicitTarget!==undefined||!result.connectedAxisHeightsMm)return target;const options=result.connectedAxisHeightsMm.filter(t=>validElevation(round(t-base))).sort((a,b)=>Math.abs(a-current)-Math.abs(b-current)||a-b);const selected=options.find(t=>type!=='instance'||!universalPostReplacement(layout,catalog,id,round(t-base))?.issue);if(selected===undefined)throw new Error('现有高度组没有可用垫高或柱高能精确达到的光轴，请手动调整机械配置。');return selected};
    if(type==='board'){
      const plate=(layout.subBoards||[]).find(p=>p.id===id);if(!plate)throw new Error('小板已不存在。');const known=result.axisHeights.filter(r=>r.boardId===id&&r.opticalAxisHeightMm!==null&&r.globalHeightComparable!==false),internal=known.map(r=>r.opticalAxisHeightMm+r.elevationMm+(r.adapterThicknessMm||0)+(r.postHeightDeltaMm||0));
      if(!known.length)throw new Error('小板内尚无已知光轴高度的元件。');if(internal.some(h=>Math.abs(h-internal[0])>EPS))throw new Error('小板内的光轴高度不同，请先逐个元件配平，再自动垫高整块小板。');target=chooseConnectedTarget(internal[0]+boardSupportHeight(plate,catalog),known[0].effectiveAxisHeightMm);height=target-internal[0]-boardSupportHeight(plate,catalog);
    }else{const row=result.axisHeights.find(r=>r.instanceId===id);if(row?.globalHeightComparable===false)throw new Error('整装内有多个三维光学面，请手动设置垫高，并通过实际光路检查匹配。');if(!row||row.opticalAxisHeightMm===null)throw new Error('此元件的本体光轴高度待确认，不能自动垫高。');const base=row.boardElevationMm+row.boardThicknessMm+(row.stageHeightOffsetMm||0)+row.opticalAxisHeightMm+(row.adapterThicknessMm||0)+(row.postHeightDeltaMm||0);target=chooseConnectedTarget(base,row.effectiveAxisHeightMm??row.requestedEffectiveAxisHeightMm);height=target-base}
    height=round(height);if(!validElevation(height))throw new Error('所需垫高无法用 0.001 mm 精度在 0–1000 mm 范围内准确配平，请核对板厚和光轴高度。');if(type==='instance'){const replacement=universalPostReplacement(layout,catalog,id,height);if(replacement?.issue)throw new Error(replacement.issue.message)}return height;
  }
  function install(Editor,root){
    const P=Editor.prototype,oldValidation=P.validation,$=id=>root.document.getElementById(id),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    P.elevationCatalog=function(){return{...this.catalog,kits:[...this.kits.values()]}};
    P.elevationAnalysis=function(){return analyze(this.snapshot(),this.elevationCatalog(),{periscopeMode:true})};
    P.validation=function(){const base=oldValidation.call(this),layout=this.snapshot(),catalog=this.elevationCatalog(),key=JSON.stringify([layout.instances.map(i=>[i.id,i.boardId,i.elevationMm,i.elevationSupportCount,i.laserAdapter,i.universalPostSelection,i.manualMount]),layout.subBoards?.map(p=>[p.id,p.elevationMm,p.elevationSupportCount,p.board.thicknessMm,p.stageMotion]),catalog.stageModules,[...this.kits.values()].map(k=>[k.id,k.layout?.opticalAxisHeightMm,k.layout?.opticalAssembly,k.layout?.fixedUniversalPostComponentIds,k.components]),catalog.elevationMaterials,catalog.universalPostSeries]);if(this._elevationValidation?.base===base&&this._elevationValidation.key===key)return this._elevationValidation.value;const heights=analyze(layout,catalog,{periscopeMode:true}),value={...base,...heights,issues:[...base.issues,...heights.issues],valid:base.valid&&!heights.issues.length};this._elevationValidation={base,key,value};return value};
    P.elevationDraftLayout=function(){const layout=this.snapshot(),id=this._elevationTarget?.id,target=layout.instances.find(i=>i.id===id);if(target&&this._elevationPostDraft!==undefined){if(Object.keys(this._elevationPostDraft).length)target.universalPostSelection=copy(this._elevationPostDraft);else delete target.universalPostSelection;}return layout};
    P.setElevation=function(type,id,height,count,postSelection){
      if(!validElevation(height)||!validCount(count))throw new Error('垫高高度需为 0–1000 mm、精确到 0.001 mm；支撑组数需为 1–128 的整数。');
      if(this.boardFormDirty||this.manualMounting)throw new Error('请先完成当前面包板参数或选孔修改。');
      const proposed=this.snapshot(),instance=proposed.instances.find(i=>i.id===id);if(type==='instance'&&postSelection!==undefined){if(Object.keys(postSelection).length)instance.universalPostSelection=copy(postSelection);else delete instance.universalPostSelection;}
      const replacement=type==='instance'?universalPostReplacement(proposed,this.elevationCatalog(),id,height):null;if(replacement?.issue)throw new Error(replacement.issue.message);
      const before=this.historySnapshot();let target;if(type==='board')target=this.stacked?.subBoards.find(p=>p.id===id);else target=this.instances.find(i=>i.id===id)||this.stacked?.instances.find(i=>i.id===id);if(!target)throw new Error('所选对象已不存在。');
      target.elevationMm=height;target.elevationSupportCount=replacement&&!target.boardId?1:count;
      if(type==='instance'&&postSelection!==undefined){if(Object.keys(postSelection).length)target.universalPostSelection=copy(postSelection);else delete target.universalPostSelection;}
      this.commit(before);return this.elevationAnalysis();
    };
    P.autoElevate=function(type,id,count){const height=autoElevation(this.snapshot(),this.elevationCatalog(),type,id);return this.setElevation(type,id,height,count)};
    P.openElevationProperties=function(type,id){
      const layout=this.snapshot(),info=this.elevationAnalysis(),plate=type==='board'?(layout.subBoards||[]).find(p=>p.id===id):null,instance=type==='instance'?layout.instances.find(i=>i.id===id):null;if(!plate&&!instance)return;this._elevationTarget={type,id};this._elevationPostDraft=copy(instance?.universalPostSelection||{});const row=info.axisHeights.find(r=>r.instanceId===id),kit=instance?this.kits.get(instance.kitId):null;
      $('elevation-title').textContent=plate?`${plate.name} · 小板设置`:`${kit?.name||'元件'} · 属性`;
      $('elevation-height').value=elevation(plate||instance);$('elevation-support-count').value=plate?supportCount(plate,null,null,true,this.elevationCatalog()):row.elevationSupportCount;
      $('elevation-body-axis').textContent=plate?'由小板内各元件决定':externalAxisHeights(kit?.layout)?.length?externalAxisHeights(kit.layout).map(h=>`${h} mm`).join(' ↔ '):row.opticalAxisHeightMm===null?'待确认':`${row.opticalAxisHeightMm} mm`;
      $('elevation-board-top').textContent=plate?`${round(elevation(plate)+boardSupportHeight(plate,this.elevationCatalog()))} mm`:`${round(row.boardElevationMm+row.boardThicknessMm+(row.stageHeightOffsetMm||0))} mm`;
      $('elevation-current-axis').textContent=plate?([...new Set(info.axisHeights.filter(r=>r.boardId===id&&r.effectiveAxisHeightMm!==null).map(r=>r.effectiveAxisHeightMm))].map(h=>`${h} mm`).join('、')||'待确认'):row.heightResolved===false?(row.requestedEffectiveAxisHeightMm===null?'当前柱高无法实现':`不可实现（需要 ${row.requestedEffectiveAxisHeightMm} mm）`):row.effectiveExternalAxisHeightsMm?.length?row.effectiveExternalAxisHeightsMm.map(h=>`${h} mm`).join(' ↔ '):row.effectiveAxisHeightMm===null?'待确认':`${row.effectiveAxisHeightMm} mm`;
      const postContext=instance?universalPostContext(layout,this.elevationCatalog(),id):null;
      if($('elevation-post-fields')){
        $('elevation-post-fields').hidden=!postContext;$('elevation-support-field').hidden=Boolean(postContext&&!instance?.boardId);$('elevation-support-count').disabled=Boolean(postContext&&!instance?.boardId);$('elevation-post-height').disabled=!postContext||Boolean(instance?.boardId);
        $('elevation-height-label').textContent=postContext&&!instance?.boardId?'从所选基础柱继续增加的高度（mm）':'额外垫高高度（mm）';
        $('elevation-material-description').textContent=postContext&&!instance?.boardId?'明确选择基础柱后，继续增高只在该柱系列内精确匹配。选柱会重新计算真实光轴，原转接块保持不变；不会自动认证为62.5 mm。生产清单按原数量替换柱子。':'每组使用麓邦 Ø25 mm 无基座 M6 接杆、OP1 垫片与所需尾差薄片。材料按支撑组数自动加入采购清单。';
        $('elevation-post-original').textContent=postContext?`原柱：${postContext.originals.map(p=>`${p.name}（${p.heightMm} mm）× ${p.quantity}`).join('；')} · ${[...new Set(postContext.bases.map(postSeriesLabel))].join('／')}；增高按所选基础柱系列。`:'';
        if($('elevation-post-selection'))$('elevation-post-selection').innerHTML=postContext?postContext.originals.map(original=>`<label class="shared-field">${esc(original.name)} · 基础柱<select data-post-original="${esc(original.componentId)}"><option value=""${!this._elevationPostDraft[original.componentId]?' selected':''}>保留原柱 ${original.heightMm} mm</option>${postContext.posts.filter(p=>p.componentId!==original.componentId).map(p=>`<option value="${esc(p.componentId)}"${this._elevationPostDraft[original.componentId]===p.componentId?' selected':''}>${esc(postContext.components.get(p.componentId)?.name||p.componentId)} · ${p.heightMm} mm · ${esc(postSeriesLabel(p))}${postContext.components.get(p.componentId)?.postTopThread?` · 顶中心 ${esc(postContext.components.get(p.componentId).postTopThread)}`:''}</option>`).join('')}</select></label>`).join(''):'';
        $('elevation-post-height').innerHTML='<option value="">请选择现有柱高</option>'+universalPostChoices(layout,this.elevationCatalog(),id).map(p=>`<option value="${p.elevationMm}">${esc(p.name)} · 柱高 ${p.heightMm} mm${p.effectiveAxisHeightMm===null?'':` · 总光轴 ${p.effectiveAxisHeightMm} mm`}</option>`).join('');
      }
      $('elevation-reference').textContent=info.connectedAxisHeightsMm?`已核实高度组：${info.connectedAxisHeightsMm.join(' / ')} mm（自动垫高保留已匹配高度）`:info.autoAxisHeightTargetMm===null?'待确认':`${info.autoAxisHeightTargetMm} mm（当前最高 ${info.axisHeightReferenceMm} mm，自动向上取 12.5 mm 倍数）`;if($('elevation-target-axis'))$('elevation-target-axis').value=info.autoAxisHeightTargetMm??'';$('elevation-error').hidden=true;this.renderElevationPreview();const dialog=$('elevation-dialog');if(!dialog.open)dialog.showModal();
    };
    P.renderElevationPreview=function(){
      const target=this._elevationTarget;if(!target)return;const height=Number($('elevation-height').value),count=Number($('elevation-support-count').value),catalog=this.elevationCatalog(),draft=this.elevationDraftLayout(),replacement=target.type==='instance'?universalPostReplacement(draft,catalog,target.id,height):null,valid=validElevation(height)&&(replacement||validCount(count));
      if(replacement&&$('elevation-post-height'))$('elevation-post-height').value=universalPostChoices(draft,catalog,target.id).some(p=>Math.abs(p.elevationMm-height)<=EPS)?String(height):'';
      let markup;
      if(!valid)markup='<p>请输入有效的垫高高度和支撑组数。</p>';
      else if(replacement?.issue)markup=`<p class="shared-form-error">${esc(replacement.issue.message)}</p>`;
      else if(replacement&&!replacement.context.instance.boardId){const own=replacement.context.kit.layout?.opticalAxisHeightMm;markup=height===0&&!replacement.context.explicit?'<p>保留套件原万能柱，不新增支撑材料。</p>':replacement.group.materials.map(m=>`<p>${esc(replacement.context.components.get(m.replacesComponentId)?.name||m.replacesComponentId)} → ${esc(m.name)} · 柱高 ${m.heightMm} mm × ${m.quantity} ${esc(m.unit)}</p>`).join('');if(Number.isFinite(own))markup+=`<p>设置后的总光轴高度：${round(own+height+replacement.context.postHeightDeltaMm+(replacement.context.instance.laserAdapter?.enabled?replacement.context.instance.laserAdapter.thicknessMm||0:0))} mm</p>`}
      else markup=height===0?'<p>直接安装，不新增垫高配件。</p>':materialsFor(height,count,catalog).map(m=>`<p>${esc(m.name)}${m.model?'（'+esc(m.model)+'）':''} × ${m.quantity} ${esc(m.unit)}</p>`).join('');
      if(replacement?.context.instance.boardId&&!replacement.issue){const row=analyze(draft,catalog).axisHeights.find(r=>r.instanceId===target.id);if(row?.effectiveAxisHeightMm!=null)markup+=`<p>设置后的总光轴高度：${round(row.effectiveAxisHeightMm-elevation(replacement.context.instance)+height)} mm</p>`;}
      if(replacement?.group)for(const m of replacement.group.materials){const from=catalog.components.find(c=>c.id===m.replacesComponentId)?.postTopThread,to=catalog.components.find(c=>c.id===m.componentId)?.postTopThread;if(from&&to&&from!==to)markup+=`<p>顶中心螺纹 ${esc(from)} → ${esc(to)}：原连接件的螺纹适配需要核对。</p>`;}
      if(replacement?.context.explicit&&!replacement.issue)markup+=`<p>基础柱改变光轴：${replacement.context.postHeightDeltaMm>=0?'+':''}${replacement.context.postHeightDeltaMm} mm；原转接块保持不变。</p>`;
      $('elevation-material-preview').innerHTML=markup;
    };
    P.initElevation=function(){if(this._elevationBound||!$('elevation-dialog'))return;this._elevationBound=true;const menu=$('component-context-menu'),dialog=$('elevation-dialog'),error=message=>{$('elevation-error').textContent=message;$('elevation-error').hidden=false};
      this.svg.addEventListener('contextmenu',e=>{if(this.measurement||this.manualMounting)return;const node=e.target.closest?.('[data-instance]'),id=node?.dataset.instance;if(!id)return;e.preventDefault();e.stopImmediatePropagation();this._menuInstanceId=id;$('module-context-menu').hidden=true;menu.hidden=false;menu.style.left=Math.max(4,Math.min(e.clientX,root.innerWidth-220))+'px';menu.style.top=Math.max(4,Math.min(e.clientY,root.innerHeight-100))+'px';},true);
      menu.addEventListener('click',()=>{menu.hidden=true;this.openElevationProperties('instance',this._menuInstanceId)});
      root.document.addEventListener('pointerdown',e=>{if(!menu.contains(e.target))menu.hidden=true});root.document.addEventListener('keydown',e=>{if(e.key==='Escape')menu.hidden=true});
      for(const id of ['elevation-close','elevation-cancel'])$(id).addEventListener('click',()=>dialog.close());
      for(const id of ['elevation-height','elevation-support-count'])$(id).addEventListener('input',()=>{error('');$('elevation-error').hidden=true;this.renderElevationPreview()});
      $('elevation-post-height')?.addEventListener('change',()=>{if($('elevation-post-height').value==='')return;$('elevation-height').value=$('elevation-post-height').value;$('elevation-error').hidden=true;this.renderElevationPreview()});
      $('elevation-post-selection')?.addEventListener('change',event=>{const original=event.target?.dataset?.postOriginal;if(!original)return;const value=event.target.value;if(value)this._elevationPostDraft[original]=value;else delete this._elevationPostDraft[original];$('elevation-height').value=0;const draft=this.elevationDraftLayout(),context=universalPostContext(draft,this.elevationCatalog(),this._elevationTarget.id);if(context)$('elevation-post-original').textContent=`原柱：${context.originals.map(p=>`${p.name}（${p.heightMm} mm）× ${p.quantity}`).join('；')} · ${[...new Set(context.bases.map(postSeriesLabel))].join('／')}；增高按所选基础柱系列。`;$('elevation-post-height').innerHTML='<option value="">请选择增高后的柱高</option>'+universalPostChoices(draft,this.elevationCatalog(),this._elevationTarget.id).map(p=>`<option value="${p.elevationMm}">${esc(p.name)} · 柱高 ${p.heightMm} mm · 总光轴 ${p.effectiveAxisHeightMm??'待确认'} mm</option>`).join('');this.renderElevationPreview()});
      $('elevation-apply-target')?.addEventListener('click',()=>{try{$('elevation-height').value=autoElevation(this.elevationDraftLayout(),this.elevationCatalog(),this._elevationTarget.type,this._elevationTarget.id,Number($('elevation-target-axis').value));$('elevation-error').hidden=true;this.renderElevationPreview()}catch(e){error(e.message)}});
      $('elevation-auto').addEventListener('click',()=>{try{$('elevation-height').value=autoElevation(this.elevationDraftLayout(),this.elevationCatalog(),this._elevationTarget.type,this._elevationTarget.id);$('elevation-error').hidden=true;this.renderElevationPreview()}catch(e){error(e.message)}});
      $('elevation-form').addEventListener('submit',e=>{e.preventDefault();if(!$('elevation-form').reportValidity())return;try{const target=this._elevationTarget,replacement=target.type==='instance'&&universalPostContext(this.snapshot(),this.elevationCatalog(),target.id);this.setElevation(target.type,target.id,Number($('elevation-height').value),Number($('elevation-support-count').value),target.type==='instance'?this._elevationPostDraft:undefined);dialog.close();this.notify(replacement?'已更新万能柱，生产清单会按所选柱高替换原柱。':'已更新垫高设置，配套材料会自动计入采购清单。')}catch(e){error(e.message)}});
    };
  }
  return{analyze,autoElevation,automaticAxisTarget,materialsFor,externalAxisHeights,heightValidation,fixedUniversalPostIds,universalPostContext,universalPostReplacement,universalPostChoices,validElevation,validCount,supportCount,install};
});
