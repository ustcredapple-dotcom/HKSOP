/* Two board levels. Component coordinates remain local; only plate poses move. */
(function(root){
  'use strict';
  const R=root.ZZLabRegisteredBoards;
  const EPS=1e-5,copy=x=>JSON.parse(JSON.stringify(x)),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const point=(p,x,y)=>{const [c,s]=({0:[1,0],90:[0,1],180:[-1,0],270:[0,-1]})[p.rotationDeg];return{xMm:p.xMm+c*x-s*y,yMm:p.yMm+s*x+c*y}};
  const aligned=(b,p)=>b.registeredBoardId&&R?R.isHole(b,p,undefined,{threadOnly:true,excludeMounting:true}):[[p.xMm,b.widthMm],[p.yMm,b.heightMm]].every(([v,size])=>{const n=(v-b.edgeOffsetMm)/b.pitchMm;return n>=-EPS&&v<=size-b.edgeOffsetMm+EPS&&Math.abs(n-Math.round(n))<=EPS})&&!b.mountingHoles?.some(h=>Math.abs(b.edgeOffsetMm+h.columnIndex*b.pitchMm-p.xMm)<EPS&&Math.abs(b.edgeOffsetMm+h.rowIndex*b.pitchMm-p.yMm)<EPS);
  const polygon=p=>R?R.outline(p.board).map(v=>point(p,v.xMm,v.yMm)):[[0,0],[p.board.widthMm,0],[p.board.widthMm,p.board.heightMm],[0,p.board.heightMm]].map(([x,y])=>point(p,x,y));
  const boardHoles=b=>R?R.holes(b):Array.from({length:(Math.floor((b.heightMm-2*b.edgeOffsetMm)/b.pitchMm)+1)*(Math.floor((b.widthMm-2*b.edgeOffsetMm)/b.pitchMm)+1)},(_,n)=>{const cols=Math.floor((b.widthMm-2*b.edgeOffsetMm)/b.pitchMm)+1;return{xMm:b.edgeOffsetMm+n%cols*b.pitchMm,yMm:b.edgeOffsetMm+Math.floor(n/cols)*b.pitchMm}});
  const holePosition=(b,h)=>b.registeredBoardId&&R?R.holes(b).find(p=>p.holeId===h.holeId)||{xMm:NaN,yMm:NaN}:{xMm:b.edgeOffsetMm+h.columnIndex*b.pitchMm,yMm:b.edgeOffsetMm+h.rowIndex*b.pitchMm};
  const globalInstance=(i,plates)=>{const p=plates.find(p=>p.id===i.boardId);return p?{...i,...point(p,i.xMm,i.yMm),rotationDeg:(i.rotationDeg+p.rotationDeg)%360}:{...i}};
  function eightError(holes){if(holes.length!==8)return '';const groups=new Map();for(const h of holes){const key=`${h.columnIndex%2},${h.rowIndex%2}`;groups.set(key,(groups.get(key)||0)+1)}const keys=[...groups.keys()];return keys.length===2&&[...groups.values()].every(n=>n===4)&&keys[0][0]!==keys[1][0]&&keys[0][2]!==keys[1][2]?'':'八孔需由行列奇偶均相反的两组四孔组成。'}
  root.ZZLabStackMath={point,aligned,polygon,globalInstance,eightError};
  if(typeof module==='object'&&module.exports)module.exports=root.ZZLabStackMath;
  if(!root.BreadboardEditor)return;
  const P=root.BreadboardEditor.prototype,old={};for(const key of ['snapshot','historySnapshot','restoreHistory','render','validation','manualMountingError','mountingIssues','renderManualMounting','world','fit','zoom','contentBounds','applyPointerMove','handleKeydown','remove','rotate','move','copySelection','pasteSelection','duplicate','downloadSvg','select','setSelection','selectAll','beginManualMounting'])old[key]=P[key];
  const $=id=>document.getElementById(id);
  P.localSnapshot=function(){return{board:copy(this.board),instances:copy(this.instances),...(this.collisionOverrides?.length?{collisionOverrides:root.ZZLabCollisionOverrides?.normalize(this.collisionOverrides,this.instances)||[]}:{})}};
  P.allInstances=function(){return this.snapshot().instances};
  P.snapshot=function(){if(!this.stacked)return old.snapshot.call(this);const layout=copy(this.stacked),pid=this.activeBoardId||null;if(pid)layout.subBoards.find(p=>p.id===pid).board=copy(this.board);else layout.board=copy(this.board);if(this.baseMode==='table')layout.baseMode='table';else delete layout.baseMode;layout.instances=layout.instances.filter(i=>(i.boardId||null)!==pid).concat(this.instances.map(i=>({...copy(i),...(pid?{boardId:pid}:{})})));const overrides=root.ZZLabCollisionOverrides?.normalize(this.collisionOverrides,layout.instances)||this.collisionOverrides;if(overrides?.length)layout.collisionOverrides=copy(overrides);else delete layout.collisionOverrides;return layout};
  P.historySnapshot=function(){return{...old.historySnapshot.call(this),activeBoardId:this.activeBoardId||null,selectedModuleId:this.selectedModuleId||null}};
  P.loadLayout=function(layout,active=null){
    this.collisionOverrides=copy(layout.collisionOverrides||[]);this.baseMode=layout.baseMode==='table'?'table':'breadboard';this.cancelManualMounting(false);this.stacked=Object.prototype.hasOwnProperty.call(layout,'subBoards')?copy({board:layout.board,subBoards:layout.subBoards,instances:layout.instances,...(layout.glassChamber?{glassChamber:layout.glassChamber}:{})}):null;
    this.selectedModuleId=null;this.activeBoardId=this.stacked?.subBoards.some(p=>p.id===active)?active:null;
    this.board=this.validBoard(this.activeBoardId?this.stacked.subBoards.find(p=>p.id===this.activeBoardId).board:layout.board);
    if(!this.board)throw new Error('面包板参数无效。');
    this.instances=copy(layout.instances.filter(i=>(i.boardId||null)===this.activeBoardId)).map(({boardId,...i})=>i);
    this._stackValidation=null;this._validationCache=null;this.pendingKitId=null;this.drag=null;this.setSelection([]);this.syncFields();if($('mounting-count'))$('mounting-count').value=String(this.board.mountingHoles?.length===8?8:4);
  };
  P.restoreHistory=function(state){this.loadLayout(state,state.activeBoardId);this.selectedModuleId=state.selectedModuleId||null;this.setSelection(state.selection?.ids||[],state.selection?.primary);if('externalState'in state)this.restoreExternalState?.(copy(state.externalState));this.syncFields()};
  P.initStacked=function(saved){if(saved?.subBoards)this.loadLayout(saved);this.bindStacked();if($('mounting-count'))$('mounting-count').value=String(this.board.mountingHoles?.length===8?8:4);this.render();this.onChange?.(this.snapshot())};
  P.switchBoard=function(id){
    id=id||null;if(id===(this.activeBoardId||null))return true;
    if(this.boardFormDirty||this.manualMounting){this.notify('请先应用或取消当前板的参数、选孔修改。',true);return false}
    this.onBeforeContextChange?.();const full=this.snapshot();this.loadLayout(full,id);this.changed();return true;
  };
  P.selectModule=function(id){if(!this.stacked?.subBoards.some(p=>p.id===id))return false;if(!this.switchBoard(null))return false;this.selectedModuleId=id;this.setSelection([]);this.keyboardActive=true;this.render();this.onSelect?.(null,[]);return true};
  P.editModule=function(id=this.selectedModuleId){if(!id||!this.stacked?.subBoards.some(p=>p.id===id))return false;if(!this.switchBoard(id))return false;this.selectedModuleId=null;this.render();return true};
  P.finishModuleEdit=function(){return this.switchBoard(null)};
  P.setSelection=function(ids,primary){if(ids.length)this.selectedModuleId=null;return old.setSelection.call(this,ids,primary)};
  P.selectAll=function(){this.selectedModuleId=null;return old.selectAll.call(this)};
  P.beginManualMounting=function(){if(this.selectedModuleId&&!this.editModule(this.selectedModuleId))return false;return old.beginManualMounting.call(this)};
  P.select=function(id,options){this.selectedModuleId=null;return old.select.call(this,id,options)};
  P.editPlate=function(id,changes){if(this.boardFormDirty||this.manualMounting)return this.notify('请先完成当前编辑。',true);const before=this.historySnapshot(),layout=this.snapshot(),p=layout.subBoards.find(p=>p.id===id);if(!p)return;
    Object.assign(p,changes);if(!Number.isFinite(p.xMm)||!Number.isFinite(p.yMm)||p.xMm< -5000||p.xMm>10000||p.yMm< -5000||p.yMm>10000||!p.name.trim()||p.name.length>160)return this.notify('小板名称和位置无效。',true);
    const selected=this.selectedModuleId;this.loadLayout(layout,this.activeBoardId);this.selectedModuleId=selected;this.commit(before);this.render();
  };
  P.createCarrier=function(board){if(this.baseMode==='table')throw new Error('桌子已经是承载平台，请直接新建小板或装入模块。');if(this.stacked)throw new Error('已创建大板，可切换到大板后修改参数。');if(this.boardFormDirty||this.manualMounting)throw new Error('请先完成当前板的编辑。');const normalized=this.validBoard(board);if(!normalized||![12.5,25].includes(board.pitchMm))throw new Error('大板参数无效；孔距只能12.5或25 mm，每板最多2500孔。');const before=this.historySnapshot(),id='plate-'+crypto.randomUUID(),local=this.localSnapshot();this.loadLayout({board:normalized,subBoards:[{id,name:'小面包板 1',board:local.board,xMm:0,yMm:0,rotationDeg:0}],instances:local.instances.map(i=>({...i,boardId:id})),...(local.collisionOverrides?.length?{collisionOverrides:local.collisionOverrides}:{})},id);this.commit(before);this.fit();this.notify('已创建大板，原画布作为小板保留。可在画布拖动整个模块，并重新核对固定孔。')};
  P.useCurrentAsCarrier=function(){
    if(this.stacked)return;
    if(this.boardFormDirty||this.manualMounting)throw new Error('请先完成当前板的参数或选孔编辑。');
    if(this.baseMode!=='table'&&(![12.5,25].includes(this.board.pitchMm)||this.board.holeType!=='M6_through'))throw new Error('承载大板需要12.5或25 mm孔距的M6通螺纹孔，请先更新当前板参数。');
    const before=this.historySnapshot(),layout=this.snapshot();layout.subBoards=[];
    this.loadLayout(layout);this.commit(before);this.fit();
    this.notify('当前面包板已作为大板，原有器件保留。可新建小板或连同小板装入共享模块。');
  };
  P.addSmallBoard=function(){
    if(this.boardFormDirty||this.manualMounting)return this.notify('请先完成当前板的参数或选孔编辑。',true);
    if(this.baseMode!=='table'&&!this.stacked&&(![12.5,25].includes(this.board.pitchMm)||this.board.holeType!=='M6_through'))return this.notify('底板需要12.5或25 mm孔距的M6通螺纹孔。',true);
    this.onBeforeContextChange?.();const before=this.historySnapshot(),layout=this.snapshot();layout.subBoards??=[];
    if(layout.subBoards.length>=24)return this.notify('最多支持24块小面包板。',true);
    const id='plate-'+crypto.randomUUID(),offset=layout.subBoards.length*25;
    layout.subBoards.push({id,name:`小面包板 ${layout.subBoards.length+1}`,board:{widthMm:200,heightMm:150,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:R?.recordFor(layout.board,this.catalog)?.planningOnly?12.5:12.7,holeType:'M6_through',mountingHoles:[]},xMm:offset,yMm:offset,rotationDeg:0});
    this.loadLayout(layout,id);this.commit(before);this.render();this.notify('已插入小板，可直接在同一画布编辑尺寸和内部器件。');return id;
  };
  P.mountingSpareMode=function(){return Boolean(this._mountingAllowSpares||this.stacked&&this.activeBoardId)&&(this.manualMounting?.count||this.board.mountingHoles?.length)===8};
  P.subBoardMountingStatus=function(layout,plate,holes=plate.board.mountingHoles||[]){
    if(plate.stageMotion){const world=this.stackFake(layout.board,layout.instances.filter(i=>i.boardId!==plate.id).map(i=>globalInstance(i,layout.subBoards||[])));return root.ZZLabMovingStages.mountingStatus(layout,plate,this.catalog,v=>world.mountingObstructions(v).length>0)}
    const b=plate.board,onTable=layout.baseMode==='table',world=this.stackFake(layout.board,layout.instances.map(i=>globalInstance(i,layout.subBoards||[]))),positions=holes.map((h,n)=>{const {xMm,yMm}=holePosition(b,h),v=point(plate,xMm,yMm),support=R?.recordFor(b,this.catalog)?.customElevationSupport,offsets=support&&Math.abs(support.heightMm-(plate.elevationMm||0))<1e-6?support.baseMountingOffsetsMm||[]:[],supportPoints=offsets.length?offsets.map(o=>point(plate,xMm+o.xMm,yMm+o.yMm)):[v],isAligned=onTable||supportPoints.every(q=>aligned(layout.board,q)),obstructed=world.mountingObstructions(v).length>0,usable=isAligned&&!obstructed;return{id:'H'+(n+1),label:'H'+(n+1),xMm,yMm,globalXMm:v.xMm,globalYMm:v.yMm,supportBasePointsMm:supportPoints,aligned:isAligned,obstructed,usable,spare:!usable}}),count=key=>new Set(positions.filter(h=>h[key]).map(h=>`${h.xMm},${h.yMm}`)).size;
    return{boardId:plate.id,onTable,totalCount:positions.length,requiredCount:onTable&&!positions.length?0:b.registeredBoardId&&R?(R.recordFor(b)?.minimumAlignedMountingHoles??Math.min(4,R.recordFor(b)?.mountingHoleIds?.length||0)):4,alignedCount:count('aligned'),usableCount:count('usable'),holes:positions};
  };
  P.mountingSparesError=function(status,name){return status.totalCount===8&&status.usableCount<4?`${name}：8 个沉孔中只有 ${status.usableCount} 个${status.onTable?'':'对齐且'}无遮挡的可用固定孔，至少需要 4 个；其余孔可作为备用。`:''};
  P.manualMountingSetError=function(holes){if(this.board.registeredBoardId||!this.stacked||!this.activeBoardId||holes.length!==8)return '';const layout=this.snapshot(),plate=layout.subBoards.find(p=>p.id===this.activeBoardId);return this.mountingSparesError(this.subBoardMountingStatus(layout,plate,holes),plate.name)};
  P.stackCandidateError=function(hole){if(!this.stacked||!this.activeBoardId||this.mountingSpareMode())return '';const layout=this.snapshot(),plate=layout.subBoards.find(p=>p.id===this.activeBoardId);if(plate.stageMotion&&R?.allowsCoveredMounting(this.board,this.catalog))return '';const b=this.board,position=holePosition(b,hole),world=point(plate,position.xMm,position.yMm);if(layout.baseMode!=='table'&&!aligned(layout.board,world))return '这个孔没有与大板有效螺纹孔重合，不能作为固定沉孔。';
    const fake=this.stackFake(layout.board,layout.instances.filter(i=>i.boardId!==plate.id).map(i=>globalInstance(i,layout.subBoards)));
    if(fake.mountingObstructions(world).length)return '这个孔被另一块板上的器件遮挡。';return '';
  };
  P.manualMountingError=function(hole,chosen=[]){return old.manualMountingError.call(this,hole,chosen)||this.stackCandidateError(hole)};
  P.mountingIssues=function(){const issues=old.mountingIssues.call(this),error=this.board.registeredBoardId?'':eightError(this.board.mountingHoles||[]);if(error)issues.push({code:'board_mounting_invalid',instanceIds:[],message:error});return issues};
  P.stackFake=function(board,instances){const fake=Object.create(P);Object.assign(fake,{board,instances,catalog:this.catalog,kits:this.kits,selectedIds:new Set(),stacked:null,renderStats:{}});return fake};
  P.validation=function(){if(!this.stacked)return old.validation.call(this);const layout=this.snapshot(),kitPolicy=Array.from(new Set(layout.instances.map(i=>i.kitId))).map(id=>[id,this.kits.get(id)?.layout?.minimumAlignedMountingHoles,this.kits.get(id)?.layout?.mountingHoleOffsetsMm,this.kits.get(id)?.layout?.baseOverhangAllowedWithPartialMounting]),key=JSON.stringify([layout,kitPolicy]);if(this._stackValidation?.key===key)return this._stackValidation.value;
    const issues=[],mountingAlignment=[],subBoardMountingAlignment=[],G=root.ZZLabLayoutGeometry,plates=layout.subBoards,global=layout.instances.map(i=>globalInstance(i,plates)),world=this.stackFake(layout.board,global),polygons=global.map(i=>world.worldPolygons(i));
    const add=(code,message,boardId=null,more={})=>issues.push({code,message,instanceIds:[],...(boardId?{boardId}:{}),...more});
    if(layout.baseMode!=='table'&&(![12.5,25].includes(layout.board.pitchMm)||layout.board.holeType!=='M6_through'))add('invalid_board','大板需要12.5或25 mm孔距的M6螺纹孔。');
    for(const board of [{id:null,name:'大面包板',board:layout.board},...plates]){
      const instances=layout.instances.filter(i=>(i.boardId||null)===board.id);this._stackLocalCache??=new Map();let cached=this._stackLocalCache.get(board.id);const localKey=JSON.stringify([board.board,instances,kitPolicy,board.id===null&&layout.baseMode==='table']);if(!cached||cached.key!==localKey){const fake=this.stackFake(board.board,instances);fake._mountingAllowSpares=Boolean(board.id);fake._referenceSurface=board.id===null&&layout.baseMode==='table';cached={key:localKey,value:old.validation.call(fake)};this._stackLocalCache.set(board.id,cached)}
      for(const issue of cached.value.issues)issues.push({...issue,boardId:board.id,message:board.name+'：'+issue.message});
      for(const match of cached.value.mountingAlignment||[])mountingAlignment.push({...match,boardId:board.id,globalAlignedPositionsMm:match.alignedPositionsMm.map(h=>board.id?point(board,h.xMm,h.yMm):{...h})});
    }
    const boxes=plates.map(p=>G.pointsBounds(polygon(p)));
    for(let n=0;n<plates.length;n++){
      const p=plates[n],b=p.board,box=boxes[n];if(R?!R.containsPolygon(layout.board,polygon(p),this.catalog):box.xMin<-EPS||box.yMin<-EPS||box.xMax>layout.board.widthMm+EPS||box.yMax>layout.board.heightMm+EPS)add('sub_board_out_of_bounds',p.name+'：小板底面超出大板。',p.id);
      const overlap=boardHoles(b).some(h=>aligned(layout.board,point(p,h.xMm,h.yMm)));
      if(!p.stageMotion&&layout.baseMode!=='table'&&!overlap)add('sub_board_no_overlap',p.name+'：没有孔与大板重合，请移动小板。',p.id);
      if(!p.stageMotion&&layout.baseMode!=='table'&&!b.mountingHoles?.length)add('sub_board_unfastened',p.name+'：尚未选择与大板对齐的固定沉孔。',p.id);
      const fastening=this.subBoardMountingStatus(layout,p);subBoardMountingAlignment.push(fastening);
      if((b.registeredBoardId||p.stageMotion)&&fastening.usableCount<fastening.requiredCount)add('sub_board_mounting_insufficient',`${p.name}：已有 ${fastening.usableCount} 个可用原板固定孔，至少需要 ${fastening.requiredCount} 个。`,p.id);
      if(!b.registeredBoardId&&fastening.totalCount===8){const message=this.mountingSparesError(fastening,p.name);if(message)add('sub_board_mounting_insufficient',message,p.id,{holeIds:fastening.holes.filter(h=>!h.usable).map(h=>h.id),usableCount:fastening.usableCount,requiredCount:4,totalCount:8})}
      else for(const h of fastening.holes){
        if(!h.aligned)add('sub_board_mounting_mismatch',`${p.name}：${h.id} 沉孔未与大板重合，请重新选孔。`,p.id,{holeIds:[h.id]});
        const other=this.stackFake(layout.board,global.filter(i=>i.boardId!==p.id));if(other.mountingObstructions({xMm:h.globalXMm,yMm:h.globalYMm}).length)add('mounting_hole_obstructed',`${p.name}：${h.id} 被另一块板上的器件遮挡。`,p.id,{holeIds:[h.id]});
      }
      for(let j=0;j<n;j++)if((b.registeredBoardId||plates[j].board.registeredBoardId)&&R?R.overlaps(R.region(b,p,this.catalog),R.region(plates[j].board,plates[j],this.catalog)):Math.min(box.xMax,boxes[j].xMax)-Math.max(box.xMin,boxes[j].xMin)>EPS&&Math.min(box.yMax,boxes[j].yMax)-Math.max(box.yMin,boxes[j].yMin)>EPS)add('sub_board_collision',`${p.name} 与 ${plates[j].name} 的板面重叠。`,p.id,{boardIds:[p.id,plates[j].id]});
      global.forEach((i,index)=>{if(!i.boardId&&polygons[index].some(poly=>p.board.registeredBoardId&&R?R.overlaps({outer:poly,cuts:[]},R.region(p.board,p,this.catalog)):G.polygonsTouch(poly,polygon(p))))add('collision',p.name+' 与直接安装在大板上的器件相交。',p.id,{instanceIds:[i.id]})});
      for(const h of layout.baseMode==='table'?[]:layout.board.mountingHoles||[]){const v=holePosition(layout.board,h);if(p.board.registeredBoardId&&R?R.overlaps({outer:Array.from({length:32},(_,j)=>({xMm:v.xMm+5.5*Math.cos(j*Math.PI/16),yMm:v.yMm+5.5*Math.sin(j*Math.PI/16)})),cuts:[]},R.region(p.board,p,this.catalog)):G.circleTouchesPolygon(v,5.5,polygon(p)))add('mounting_hole_obstructed','大板安装孔被 '+p.name+' 遮挡。',p.id)}
    }
    for(let i=0;i<global.length;i++)for(let j=0;j<i;j++)if(global[i].boardId!==global[j].boardId&&polygons[i].some(a=>polygons[j].some(b=>G.polygonsTouch(a,b)))&&issues.length<250)add('collision','不同面包板上的器件轮廓相交。',null,{instanceIds:[global[i].id,global[j].id]});
    const value={valid:!issues.length,issues,mountingAlignment,subBoardMountingAlignment};this._stackValidation={key,value};return value;
  };
  P.renderManualMounting=function(scene){old.renderManualMounting.call(this,scene);if(!this.board.registeredBoardId&&this.stacked&&this.activeBoardId&&this.manualMounting?.count===8){const layout=this.snapshot(),plate=layout.subBoards.find(p=>p.id===this.activeBoardId),status=this.subBoardMountingStatus(layout,plate,this.manualMounting.holes);$('mounting-manual-status').textContent+=` · ${status.usableCount} 个可用固定孔（至少 4 个）`;Array.from(scene.manualMountingLayer?.children||[]).forEach((node,n)=>{const spare=status.holes[n]?.spare;node.setAttribute('data-spare',String(Boolean(spare)));for(const child of Array.from(node.children||[])){if(child.tagName==='circle')child.setAttribute('style',spare?'stroke:#b4771c':'');if(child.tagName==='text')child.textContent=`H${n+1}${spare?' · 备用':''}`}})}if(!this.stacked||!this.activeBoardId||this.baseMode==='table'){if(scene.alignedLayer)scene.alignedLayer.setAttribute('display','none');return}
    const layout=this.snapshot(),p=layout.subBoards.find(p=>p.id===this.activeBoardId),b=this.board,key=JSON.stringify([layout.board,p]);if(!scene.alignedLayer){scene.alignedLayer=document.createElementNS('http://www.w3.org/2000/svg','g');scene.alignedLayer.setAttribute('pointer-events','none');scene.alignedLayer.setAttribute('class','aligned-hole-layer');scene.parts.parentNode.insertBefore(scene.alignedLayer,scene.parts)}scene.alignedLayer.setAttribute('display','inline');if(scene.alignedKey===key)return;scene.alignedKey=key;
    let markup='';for(const hole of boardHoles(b)){const x=hole.xMm,y=hole.yMm;if(aligned(layout.board,point(p,x,y)))markup+=`<circle cx="${x}" cy="${b.heightMm-y}" r="2.3" fill="none" stroke="#16736f" stroke-width=".5"/>`}scene.alignedLayer.innerHTML=markup;
  };
  // One SVG always uses the carrier coordinate system. The active edit scene is
  // transformed into that space; all other boards remain visible and interactive.
  P.sceneWorld=function(e){const pt=this.svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(this.svg.getScreenCTM().inverse());const b=this.stacked?this.snapshot().board:this.board;return{x:p.x,y:p.y,xMm:p.x,yMm:b.heightMm-p.y}};
  P.localPointForBoard=function(world,id=this.activeBoardId){const p=this.stacked?.subBoards.find(p=>p.id===id);if(!p)return{xMm:world.xMm,yMm:world.yMm};const dx=world.xMm-p.xMm,dy=world.yMm-p.yMm,[c,s]=({0:[1,0],90:[0,1],180:[-1,0],270:[0,-1]})[p.rotationDeg];return{xMm:c*dx+s*dy,yMm:-s*dx+c*dy}};
  P.world=function(e){if(!this.stacked)return old.world.call(this,e);const w=this.sceneWorld(e),local=this.localPointForBoard(w);return{x:local.xMm,y:this.board.heightMm-local.yMm,...local,sceneX:w.x,sceneY:w.y}};
  P.boardAtPoint=function(world){if(!this.stacked)return null;for(const p of [...this.snapshot().subBoards].reverse()){const q=this.localPointForBoard(world,p.id);if(R?R.contains(p.board,q,this.catalog):q.xMm>=0&&q.yMm>=0&&q.xMm<=p.board.widthMm&&q.yMm<=p.board.heightMm)return p.id}return null};
  P.placeAtEvent=function(id,e){const w=this.sceneWorld(e),owner=this.boardAtPoint(w);if(!this.switchBoard(owner))return;return this.add(id,this.localPointForBoard(w,owner))};
  P.contentBounds=function(){if(!this.stacked)return old.contentBounds.call(this);const l=this.snapshot(),all=[{xMm:0,yMm:0},{xMm:l.board.widthMm,yMm:l.board.heightMm}];for(const p of l.subBoards)all.push(...polygon(p));const fake=this.stackFake(l.board,l.instances.map(i=>globalInstance(i,l.subBoards)));const b=old.contentBounds.call(fake);all.push({xMm:b.xMin,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMax});return root.ZZLabLayoutGeometry.pointsBounds(all)};
  P.fit=function(){if(!this.stacked)return old.fit.call(this);const w=this.viewport.clientWidth||700,h=this.viewport.clientHeight||560,aspect=w/h,pad=25,b=this.contentBounds(),board=this.snapshot().board;let vw=b.xMax-b.xMin+pad*2,vh=b.yMax-b.yMin+pad*2;if(vw/vh<aspect)vw=vh*aspect;else vh=vw/aspect;this.view={x:(b.xMin+b.xMax-vw)/2,y:board.heightMm-(b.yMin+b.yMax+vh)/2,w:vw,h:vh};this.renderView()};
  P.zoom=function(factor,p){return old.zoom.call(this,factor,p&&Number.isFinite(p.sceneX)?{x:p.sceneX,y:p.sceneY}:p)};
  P.render=function(){old.render.call(this);if(this.stackBound)this.renderStacked()};
  P.renderStacked=function(){
    const panel=$('stack-workspace');if(!panel)return;panel.hidden=false;if($('stack-create'))$('stack-create').hidden=Boolean(this.stacked);
    const layout=this.snapshot(),b=layout.board,plates=layout.subBoards||[],validation=this.validation(),issues=validation.issues,p=plates.find(p=>p.id===(this.selectedModuleId||this.activeBoardId));
    const options=`<option value="">${this.baseMode==='table'?'桌子（无大板）':R?.recordFor(b,this.catalog)?'主板 · '+esc(R.recordFor(b,this.catalog).name):'主面包板'}</option>`+plates.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');if($('stack-active').innerHTML!==options)$('stack-active').innerHTML=options;$('stack-active').value=this.activeBoardId||'';
    $('stack-active-label').textContent=this.activeBoardId?`${p?.name||'小板'} · 正在编辑内部，其他模块仍可见`:this.selectedModuleId?`${p?.name||'模块'} · 已选中整组，拖动移动；右键编辑内部`:'在底板上放置器件或小板模块；双击或右键小板编辑内部';
    for(const id of ['stack-remove','stack-rotate'])if($(id))$(id).disabled=!p;
    if($('stack-edit-module'))$('stack-edit-module').disabled=!this.selectedModuleId;
    if($('stack-finish-edit'))$('stack-finish-edit').hidden=!this.activeBoardId;
    if($('stack-save-module'))$('stack-save-module').disabled=!p||!p.stageMotion&&!layout.instances.some(i=>i.boardId===p.id);
    $('stack-pose').hidden=!p;if(p)for(const [id,key]of [['stack-x','xMm'],['stack-y','yMm'],['stack-name','name']])if(document.activeElement!==$(id))$(id).value=p[key];
    $('stack-status').textContent=issues.length?`布局需调整 · ${issues[0].message}${issues.length>1?'（共 '+issues.length+' 项）':''}`:`布局可用 · ${plates.length} 个小板模块`;$('stack-status').classList.toggle('invalid',Boolean(issues.length));
    const scene=this._scene;if(!scene?.sceneRoot)return;
    const active=plates.find(p=>p.id===this.activeBoardId);scene.sceneRoot.setAttribute('data-active-board',this.activeBoardId||'');
    if(active){scene.sceneRoot.setAttribute('data-plate',active.id);scene.sceneRoot.setAttribute('transform',`translate(${active.xMm} ${b.heightMm-active.yMm}) rotate(${-active.rotationDeg}) translate(0 ${-active.board.heightMm})`)}else{scene.sceneRoot.removeAttribute('data-plate');scene.sceneRoot.removeAttribute('transform')}
    if(!scene.context){scene.context=document.createElementNS('http://www.w3.org/2000/svg','g');scene.context.setAttribute('class','board-context');this.svg.insertBefore(scene.context,scene.sceneRoot)}
    // Keep board surfaces together below every component, including the active
    // board's parts. Both layers retain the same board-local transforms/owners.
    if(!scene.contextParts){scene.contextParts=document.createElementNS('http://www.w3.org/2000/svg','g');scene.contextParts.setAttribute('class','board-context-parts');this.svg.appendChild(scene.contextParts)}
    if(!scene.activeParts){scene.activeParts=document.createElementNS('http://www.w3.org/2000/svg','g');scene.activeParts.setAttribute('class','active-board-parts');this.svg.appendChild(scene.activeParts)}
    for(const node of [scene.alignedLayer,scene.parts,scene.boundaries,scene.mountings,scene.marquee,scene.manualMountingLayer])if(node&&node.parentNode!==scene.activeParts)scene.activeParts.appendChild(node);
    scene.activeParts.setAttribute('data-active-board',this.activeBoardId||'');
    if(active){scene.activeParts.setAttribute('data-plate',active.id);scene.activeParts.setAttribute('transform',scene.sceneRoot.getAttribute('transform'))}else{scene.activeParts.removeAttribute('data-plate');scene.activeParts.removeAttribute('transform')}
    if(active){if(scene.context.nextSibling!==scene.sceneRoot)this.svg.insertBefore(scene.context,scene.sceneRoot)}else if(scene.sceneRoot.nextSibling!==scene.context)this.svg.insertBefore(scene.context,scene.sceneRoot.nextSibling);
    const boardMarkup=(board,id)=>{if(board.registeredBoardId&&R)return R.markup(board,this.catalog);const pitch=board.pitchMm,o=board.edgeOffsetMm,w=board.widthMm,h=board.heightMm,lx=o+Math.floor((w-2*o)/pitch)*pitch,ly=o+Math.floor((h-2*o)/pitch)*pitch;return `<defs><pattern id="${id}" width="${pitch}" height="${pitch}" x="${o-pitch/2}" y="${h-o-pitch/2}" patternUnits="userSpaceOnUse"><circle cx="${pitch/2}" cy="${pitch/2}" r="1.4" fill="#899e91"/></pattern></defs><rect class="breadboard" width="${w}" height="${h}" rx="2"/><rect x="${o-2}" y="${h-ly-2}" width="${lx-o+4}" height="${ly-o+4}" fill="url(#${id})"/>`};
    const structure=JSON.stringify([this.activeBoardId,b,plates.filter(p=>p.id!==this.activeBoardId).map(p=>[p.id,p.name,p.board,p.stageMotion?.moduleId]),layout.instances.filter(i=>(i.boardId||null)!==(this.activeBoardId||null)).map(i=>[i.id,i.kitId,i.boardId,i.laserAdapter,this.kitLayout(i),this.localBounds(i,'base'),this.kits.get(i.kitId)?.layout?.minimumAlignedMountingHoles!=null?[i.xMm,i.yMm,i.rotationDeg,this.kits.get(i.kitId).layout.minimumAlignedMountingHoles,this.kits.get(i.kitId).layout.mountingHoleOffsetsMm]:null])]);
    if(scene.contextKey!==structure){
      scene.contextKey=structure;
      const part=i=>{const owner=plates.find(p=>p.id===i.boardId)?.board||b,fake=this.stackFake(owner,[]);return `<g data-instance="${esc(i.id)}" data-context-part="${esc(i.id)}" role="button" tabindex="0" aria-label="${esc(this.kits.get(i.kitId)?.name)}"><title>${esc(this.kits.get(i.kitId)?.name)}</title>${this.imageMarkup(i)}${fake.boundaryMarkup(i)}</g>`};
      const holes=(board,owner)=>(R?R.mountingPositions(board,this.catalog):(board.mountingHoles||[]).map(h=>({...h,...holePosition(board,h)}))).map((h,j)=>`<g data-context-hole="${j}" data-owner="${esc(owner)}" transform="translate(${h.xMm} ${-h.yMm})" pointer-events="none" fill="none"><circle r="5.5"/><circle r="3.3"/></g>`).join('');
      let html=active?boardMarkup(b,'context-root-grid')+`<g transform="translate(0 ${b.heightMm})">${holes(b,'')}</g>`:'';
      let partsHtml=active?`<g transform="translate(0 ${b.heightMm})">${layout.instances.filter(i=>!i.boardId).map(part).join('')}</g>`:'';
      for(let n=0;n<plates.length;n++){const p=plates[n];if(p.id===this.activeBoardId)continue;const h=p.board.heightMm;html+=`<g data-plate="${esc(p.id)}" role="button" tabindex="0" aria-label="模块 ${esc(p.name)}"><g transform="translate(0 ${-h})">${p.stageMotion?root.ZZLabMovingStages.movingMarkup(p,this.catalog):boardMarkup(p.board,'context-grid-'+n)}${p.board.registeredBoardId&&R?R.markup(p.board,this.catalog,{outlineOnly:true}):`<rect class="stack-outline" width="${p.board.widthMm}" height="${h}" fill="none"/>`}<text x="4" y="-5" font-size="8">${esc(p.name)}</text></g>${p.stageMotion?'':holes(p.board,p.id)}</g>`;partsHtml+=`<g data-plate="${esc(p.id)}">${layout.instances.filter(i=>i.boardId===p.id).map(part).join('')}</g>`}
      scene.context.innerHTML=html;scene.contextParts.innerHTML=partsHtml;scene.contextNodes={plates:[...scene.context.querySelectorAll('[data-plate]')],partPlates:[...scene.contextParts.querySelectorAll('[data-plate]')],parts:[...scene.contextParts.querySelectorAll('[data-context-part]')],holes:[...scene.context.querySelectorAll('[data-context-hole]')]};
    }
    const plateMap=new Map(plates.map(p=>[p.id,p])),instanceMap=new Map(layout.instances.map(i=>[i.id,i]));
    for(const node of [...scene.contextNodes.plates,...scene.contextNodes.partPlates]){const p=plateMap.get(node.dataset.plate),bad=issues.some(i=>i.boardId===p.id||i.boardIds?.includes(p.id));node.setAttribute('transform',`translate(${p.xMm} ${b.heightMm-p.yMm}) rotate(${-p.rotationDeg})`);node.setAttribute('class',`stack-plate${p.id===this.selectedModuleId?' selected':''}${bad?' invalid':''}`)}
    for(const node of scene.contextNodes.parts){const i=instanceMap.get(node.dataset.contextPart);node.setAttribute('transform',`translate(${i.xMm} ${-i.yMm}) rotate(${-i.rotationDeg})`);node.setAttribute('class',issues.some(x=>x.instanceIds?.includes(i.id))?'invalid-placement':'')}
    for(const node of scene.contextNodes.holes){const p=plateMap.get(node.dataset.owner),n=Number(node.dataset.contextHole),state=validation.subBoardMountingAlignment?.find(row=>row.boardId===p?.id)?.holes[n],spare=p?.board.mountingHoles?.length===8&&state?.spare;node.setAttribute('stroke',!p||state?.usable?'#795ba0':spare?'#b4771c':'#cb433d');node.setAttribute('data-spare',String(Boolean(spare)));node.setAttribute('aria-label',`H${n+1}${spare?' · 备用孔':state?.usable?' · 可用固定孔':''}`)}
    const lastSurface=active?scene.sceneRoot:scene.context;
    if(lastSurface.nextSibling!==scene.contextParts)this.svg.insertBefore(scene.contextParts,lastSurface.nextSibling);
    if(scene.contextParts.nextSibling!==scene.activeParts)this.svg.insertBefore(scene.activeParts,scene.contextParts.nextSibling);
    if(this.selectedModuleId){for(const id of ['rotate-part','duplicate-part','delete-part','copy-selection'])if($(id))$(id).disabled=false;$('layout-hint').textContent='已选中小板模块 · 拖动整体移动 · 右键或双击编辑内部 · Delete 删除整组'}
    if($('paste-selection')&&this.moduleClipboard)$('paste-selection').disabled=false;
    $('layout-instance-count').textContent=`${layout.instances.length} 个套件${plates.length?' · '+plates.length+' 个小板模块':''}`;
    if(active)$('layout-board-label').textContent=`编辑 ${active.name} · ${active.board.widthMm} × ${active.board.heightMm} mm`;
  };
  P.handleUnifiedPointerDown=function(e){
    if(!this.stacked||this.measurement||this.space||e.button!==0)return false;
    if(this.manualMounting)return false;
    const w=this.sceneWorld(e),plateId=e.target.closest?.('[data-plate]')?.dataset.plate||null;
    if(this.pendingKitId){const id=this.pendingKitId;this.placeAtEvent(id,e);e.preventDefault();return true}
    if(plateId&&plateId!==this.activeBoardId){
      if(!this.selectModule(plateId)){e.preventDefault();return true}
      this.drag={mode:'module',id:plateId,start:w,startClient:{x:e.clientX,y:e.clientY},before:this.historySnapshot(),pose:copy(this.stacked.subBoards.find(p=>p.id===plateId)),pointer:e.pointerId,moved:false};
      this.svg.setPointerCapture(e.pointerId);this.svg.focus({preventScroll:true});e.preventDefault();return true;
    }
    if(this.activeBoardId&&!plateId){if(!this.switchBoard(null)){e.preventDefault();return true}}
    this.selectedModuleId=null;return false;
  };
  P.applyPointerMove=function(e){const d=this.drag;if(d?.mode!=='module')return old.applyPointerMove.call(this,e);if(e.pointerId!==d.pointer)return;const w=this.sceneWorld(e);if(Math.hypot(e.clientX-d.startClient.x,e.clientY-d.startClient.y)<=3&&!d.moved)return;d.moved=true;const p=this.stacked.subBoards.find(p=>p.id===d.id),step=this.snapshot().instances.some(i=>i.boardId===d.id&&root.ZZLabLaserAdapter?.enabled(i))?this.stacked.board.pitchMm:12.5;if(p.board.registeredBoardId&&R)Object.assign(p,R.snapPlate(this.stacked.board,p.board,{xMm:d.pose.xMm+w.xMm-d.start.xMm,yMm:d.pose.yMm+w.yMm-d.start.yMm,rotationDeg:p.rotationDeg},this.catalog,this.baseMode==='table'));else{p.xMm=d.pose.xMm+Math.round((w.xMm-d.start.xMm)/step)*step;p.yMm=d.pose.yMm+Math.round((w.yMm-d.start.yMm)/step)*step;}this._stackValidation=null;this.render()};
  P.removeModule=function(id=this.selectedModuleId||this.activeBoardId){if(!id||this.manualMounting||this.boardFormDirty)return;this.onBeforeContextChange?.();const before=this.historySnapshot(),layout=this.snapshot(),ids=layout.instances.filter(i=>i.boardId===id).map(i=>i.id);layout.instances=layout.instances.filter(i=>i.boardId!==id);layout.subBoards=layout.subBoards.filter(p=>p.id!==id);try{this.onRemove?.(ids);this.loadLayout(layout);this.commit(before)}catch(error){this.restoreHistory(before);this.changed();this.notify('删除未完成，模块已保留。',true);return}this.notify('已移除小板及其器件，可撤销恢复。');return ids};
  P.rotateModule=function(id=this.selectedModuleId||this.activeBoardId){const p=this.snapshot().subBoards?.find(p=>p.id===id);if(p){const rotationDeg=(p.rotationDeg+90)%360;this.editPlate(id,{rotationDeg,...(p.board.registeredBoardId&&R?R.snapPlate(this.snapshot().board,p.board,{...p,rotationDeg},this.catalog,this.baseMode==='table'):{})})}};
  P.remove=function(){return this.selectedModuleId?this.removeModule():old.remove.call(this)};
  P.rotate=function(){return this.selectedModuleId?this.rotateModule():old.rotate.call(this)};
  P.move=function(dx,dy){const p=this.stacked?.subBoards.find(p=>p.id===this.selectedModuleId);if(p&&this.snapshot().instances.some(i=>i.boardId===p.id&&root.ZZLabLaserAdapter?.enabled(i))){const pitch=this.stacked.board.pitchMm;dx=Math.sign(dx)*Math.max(dx?1:0,Math.round(Math.abs(dx)/pitch))*pitch;dy=Math.sign(dy)*Math.max(dy?1:0,Math.round(Math.abs(dy)/pitch))*pitch}return p?this.editPlate(p.id,{xMm:p.xMm+dx,yMm:p.yMm+dy}):old.move.call(this,dx,dy)};
  P.copyModule=function(){const p=this.stacked?.subBoards.find(p=>p.id===this.selectedModuleId);if(!p)return null;const instances=this.snapshot().instances.filter(i=>i.boardId===p.id),metadata=this.onCopy?.(instances.map(i=>i.id));this.moduleClipboard=copy({plate:p,instances,metadata:metadata??null,...(this.collisionOverrides?.length?{collisionOverrides:root.ZZLabCollisionOverrides?.normalize(this.collisionOverrides,instances)||[]}:{})});this.clipboard=null;this.modulePasteCount=0;this.render();this.notify('已复制小板模块及全部内部器件。');return this.moduleClipboard};
  P.pasteModule=function(packet=this.moduleClipboard){if(!packet)return null;const layout=this.snapshot();layout.subBoards??=[];if(layout.subBoards.length>=24||layout.instances.length+packet.instances.length>500)return this.notify('本次粘贴超过小板或器件数量上限。',true);if(this.boardFormDirty||this.manualMounting)return this.notify('请先完成当前编辑。',true);const before=this.historySnapshot(),id='plate-'+crypto.randomUUID(),n=(this.modulePasteCount||0)+1,plate={...copy(packet.plate),id,name:packet.plate.name+' 副本',xMm:packet.plate.xMm+25*n,yMm:packet.plate.yMm+25*n},mapping=[];layout.subBoards.push(plate);for(const i of packet.instances){const toId='instance-'+crypto.randomUUID();mapping.push({fromId:i.id,toId});layout.instances.push({...copy(i),id:toId,boardId:id})}if(root.ZZLabCollisionOverrides){const overrides=root.ZZLabCollisionOverrides.merge(layout.collisionOverrides,root.ZZLabCollisionOverrides.remap(packet.collisionOverrides,mapping));if(overrides.length>root.ZZLabCollisionOverrides.MAX){this.notify('本次粘贴会超过 10000 对人工碰撞豁免，未粘贴。',true);return null}if(overrides.length)layout.collisionOverrides=overrides}try{this.loadLayout(layout);this.selectedModuleId=id;this.onPaste?.(copy(mapping),copy(packet.metadata));this.commit(before);this.modulePasteCount=n;return{id,mapping}}catch(error){this.restoreHistory(before);this.changed();this.notify('粘贴未完成，原布局已保留。',true);return null}};
  P.copySelection=function(){if(this.selectedModuleId)return this.copyModule();this.moduleClipboard=null;return old.copySelection.call(this)};
  P.pasteSelection=function(){return this.moduleClipboard?this.pasteModule():old.pasteSelection.call(this)};
  P.duplicate=function(){if(!this.selectedModuleId)return old.duplicate.call(this);const packet=this.copyModule();return packet?this.pasteModule(packet):null};
  P.handleKeydown=function(e){
    if(!this.keyboardContext(e))return;const key=e.key.toLowerCase(),mod=e.metaKey||e.ctrlKey;
    if(e.key==='Escape'&&this.drag?.mode==='module'){e.preventDefault();const pointer=this.drag.pointer;this.cancelPointerFrame();this.restoreHistory(this.drag.before);this.drag=null;if(this.svg.hasPointerCapture(pointer))this.svg.releasePointerCapture(pointer);this.changed();return}
    if(!this.manualMounting&&mod&&key==='v'&&this.moduleClipboard){e.preventDefault();this.pasteModule();return}
    if(this.selectedModuleId&&!this.manualMounting){
      if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();this.removeModule();return}
      if(key==='r'&&!mod){e.preventDefault();this.rotateModule();return}
      if(mod&&key==='c'){e.preventDefault();this.copyModule();return}
      if(mod&&key==='d'){e.preventDefault();this.duplicate();return}
      if(e.key==='Enter'){e.preventDefault();this.editModule();return}
      const moves={ArrowLeft:[-12.5,0],ArrowRight:[12.5,0],ArrowUp:[0,12.5],ArrowDown:[0,-12.5]};if(moves[e.key]){e.preventDefault();this.move(...moves[e.key]);return}
    }
    return old.handleKeydown.call(this,e);
  };
  P.downloadSvg=function(){const svg=old.downloadSvg.call(this),b=this.snapshot().board;svg.setAttribute('viewBox',`-20 -15 ${b.widthMm+40} ${b.heightMm+40}`);svg.setAttribute('width',`${b.widthMm+40}mm`);svg.setAttribute('height',`${b.heightMm+40}mm`);return svg};
  P.bindStacked=function(){if(this.stackBound||!$('stack-workspace'))return;this.stackBound=true;const safe=fn=>{try{fn()}catch(e){this.notify(e.message,true)}},listen=(id,event,fn)=>$(id)?.addEventListener(event,fn);
    listen('stack-use-current','click',()=>safe(()=>this.useCurrentAsCarrier()));
    listen('stack-create-button','click',()=>safe(()=>this.createCarrier({widthMm:Number($('stack-width').value),heightMm:Number($('stack-height').value),pitchMm:Number($('stack-pitch').value),edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]})));
    listen('stack-active','change',e=>this.switchBoard(e.target.value));listen('stack-add','click',()=>this.addSmallBoard());
    listen('stack-edit-module','click',()=>this.editModule());listen('stack-finish-edit','click',()=>this.finishModuleEdit());
    for(const [id,key]of [['stack-x','xMm'],['stack-y','yMm'],['stack-name','name']])listen(id,'change',e=>this.editPlate(this.selectedModuleId||this.activeBoardId,{[key]:key==='name'?e.target.value:Number(e.target.value)}));
    listen('stack-rotate','click',()=>this.rotateModule());listen('stack-remove','click',()=>this.removeModule());
    this.svg.addEventListener('dblclick',e=>{if(this.measurement||this.pendingKitId||this.manualMounting)return;const id=e.target.closest?.('[data-plate]')?.dataset.plate;if(id){e.preventDefault();this.editModule(id)}});
    const menu=$('module-context-menu');
    this.svg.addEventListener('contextmenu',e=>{if(this.measurement||this.manualMounting)return;const id=e.target.closest?.('[data-plate]')?.dataset.plate;if(!id)return;e.preventDefault();if(id!==this.activeBoardId&&!this.selectModule(id))return;this._menuModuleId=id;if(menu){menu.hidden=false;menu.style.left=Math.min(e.clientX,window.innerWidth-210)+'px';menu.style.top=Math.min(e.clientY,window.innerHeight-200)+'px';menu.querySelector('[data-module-action="finish"]')?.toggleAttribute('hidden',!this.activeBoardId)}else this.editModule(id)});
    if(menu){menu.addEventListener('click',e=>{const action=e.target.closest?.('[data-module-action]')?.dataset.moduleAction,id=this._menuModuleId;menu.hidden=true;if(action==='settings')this.openElevationProperties?.('board',id);if(action==='edit')this.editModule(id);if(action==='finish')this.finishModuleEdit();if(action==='rotate')this.rotateModule(id);if(action==='remove')this.removeModule(id)});document.addEventListener('pointerdown',e=>{if(!menu.contains(e.target))menu.hidden=true});document.addEventListener('keydown',e=>{if(e.key==='Escape')menu.hidden=true})}
    listen('mounting-count','change',()=>{if(this.manualMounting){this.manualMounting.count=Number($('mounting-count').value);this.render()}if($('mounting-manual-apply'))$('mounting-manual-apply').textContent='应用所选孔位'});
  };
  root.ZZLabRegisteredBoards?.installStack(root.BreadboardEditor);
})(typeof globalThis!=='undefined'?globalThis:this);
