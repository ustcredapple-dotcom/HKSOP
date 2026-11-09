/* Fixed board fixtures: catalog geometry is immutable; projects store optics only. */
(function(root){
 'use strict';
 const copy=v=>JSON.parse(JSON.stringify(v)),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const record=(b,c)=>(c?.registeredBoards||[]).find(r=>r.id===b?.registeredBoardId&&r.revision===b.registeredBoardRevision);
 const fields=['elementType','inserted','configured','focalLengthMm','clearApertureMm'];
 const sourceFields=['enabled','wavelengthNm','powerMw','beamDiameterMm','beamQualityM2','polarizationType','polarizationAngleDeg','ellipticityDeg','wavefrontRadiusMm'];
 const kind=d=>d.elementType||'lens';
 function validateSource(v){
  const s=v.source,ranges={wavelengthNm:[1,1e6],powerMw:[0,1e9],beamDiameterMm:[1e-6,1e4],beamQualityM2:[1,100],polarizationAngleDeg:[-3600,3600],ellipticityDeg:[-45,45]};
  if(!s||typeof s!=='object'||Array.isArray(s)||Object.keys(s).some(k=>!sourceFields.includes(k))||typeof s.enabled!=='boolean')throw Error('固定出光口只接受光束参数；位置与方向由目录固定。');
  for(const[k,[lo,hi]]of Object.entries(ranges))if(k in s&&(!Number.isFinite(s[k])||s[k]<lo||s[k]>hi))throw Error('固定出光口参数超出范围：'+k);
  if('polarizationType'in s&&!['linear','circular-left','circular-right','elliptical','unpolarized'].includes(s.polarizationType))throw Error('出光偏振类型无效。');
  if('wavefrontRadiusMm'in s&&s.wavefrontRadiusMm!==null&&(!Number.isFinite(s.wavefrontRadiusMm)||Math.abs(s.wavefrontRadiusMm)<1e-6||Math.abs(s.wavefrontRadiusMm)>1e12))throw Error('波前半径无效。');
 }

 function normalizeState(board,catalog){
  if(board.fixedOptics===undefined)return{};
  const raw=board.fixedOptics,rows=record(board,catalog)?.fixedOpticalElements||[];
  if(!raw||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).length>32)throw Error('固定镜架的光学设置格式无效。');
  const out={};for(const[id,v]of Object.entries(raw)){
   const def=rows.find(r=>r.id===id);
   if(def&&kind(def)==='source'){
    if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).some(k=>!['elementType','inserted','configured','source'].includes(k))||v.elementType!=='source'||typeof v.inserted!=='boolean'||('configured'in v&&typeof v.configured!=='boolean'))throw Error('固定出光口设置格式无效。');
    validateSource(v);out[id]=copy(v);continue;
   }
   if(!def||!v||Array.isArray(v)||Object.keys(v).some(k=>!fields.includes(k))||v.elementType!=='lens'||typeof v.inserted!=='boolean'||('configured'in v&&typeof v.configured!=='boolean'))throw Error('固定镜架只接受透镜参数，位置与朝向由目录固定。');
   if('focalLengthMm'in v&&v.focalLengthMm!==null&&(!Number.isFinite(v.focalLengthMm)||v.focalLengthMm===0||Math.abs(v.focalLengthMm)>1e6))throw Error('透镜焦距应为非零数值，未知可留空。');
   if('clearApertureMm'in v&&(!Number.isFinite(v.clearApertureMm)||v.clearApertureMm<=0||v.clearApertureMm>def.lensDiameterMm))throw Error('有效通光口径不能大于镜片外径。');
   out[id]=copy(v);
  }return Object.keys(out).length?{fixedOptics:out}:{};
 }
 const key=(owner,id)=>`fixed-board:${owner||'root'}:${id}`;
 const posePoint=(p,v)=>{const a=(p?.rotationDeg||0)*Math.PI/180,c=Math.cos(a),s=Math.sin(a);return{x:(p?.xMm||0)+c*v.xMm-s*v.yMm,y:(p?.yMm||0)+s*v.xMm+c*v.yMm}};
 function targets(layout,catalog,engine){
  return[{board:layout.board,id:null},...(layout.subBoards||[])].flatMap(owner=>(record(owner.board,catalog)?.fixedOpticalElements||[]).map(def=>{
   const saved=normalizeState(owner.board,catalog).fixedOptics?.[def.id],isSource=kind(def)==='source';
   const config=isSource?engine.normalizeOptics({...saved,elementType:'source',inserted:saved?.inserted??true,configured:saved?.configured??false,source:{...(saved?.source||{}),enabled:saved?.source?.enabled??false,directionAngleDeg:def.sourceDirectionDeg}},engine.defaults('source')):engine.normalizeOptics({...saved,elementType:'lens',inserted:saved?.inserted??false,configured:saved?.configured??false,focalLengthMm:saved?.focalLengthMm??null,surfaceAngleDeg:def.surfaceAngleDeg,clearApertureMm:saved?.clearApertureMm??def.lensDiameterMm},engine.defaults('lens'));
   if(!isSource&&config.inserted&&!Number.isFinite(saved?.clearApertureMm))config.configured=false;
   const id=key(owner.id,def.id),center=posePoint(owner.id?owner:null,def.centerMm),rotationDeg=owner.rotationDeg||0;
   const element={id,name:def.name,center,rotationDeg,axisHeightMm:def.axisHeightMm+(owner.id?owner.board.thicknessMm+(owner.elevationMm||0):0),boardId:owner.id||null,moduleId:owner.id||null,optics:config};
   if(isSource){element.sourcePoint={...center};element.sourceDirectionDeg=rotationDeg+def.sourceDirectionDeg;const issue=engine.sourcePortParameterIssue(saved||{});if(issue)element.simulationIssue=issue;}
   const kit={id:def.kitId,name:def.name,opticalSlots:[],layout:{opticalType:kind(def),opticalDatumVerified:true,...(!isSource?{opticalClearApertureVerified:false}:{}),opticalSurfaceAngleDeg:def.surfaceAngleDeg,opticalAxisHeightMm:def.axisHeightMm}};
   return{id,ownerId:owner.id||null,def,config,element,kit,instance:{id,kitId:def.kitId,xMm:def.centerMm.xMm,yMm:def.centerMm.yMm,rotationDeg:0,...(saved?{optics:copy(saved)}:{})}};
  }));
 }
 function markup(layout,catalog,engine){return targets(layout,catalog,engine).map(t=>{
  const p=(layout.subBoards||[]).find(p=>p.id===t.ownerId),d=t.def;
  if(kind(d)==='source'){
   const x=t.element.center.x,y=layout.board.heightMm-t.element.center.y;
   return `<g data-fixed-board-optic="${esc(t.id)}" role="button" tabindex="0" aria-label="${esc(d.name)} · 点击设置光束" style="cursor:pointer"><title>${esc(d.name)} · 点击设置光束；位置与方向固定</title><circle cx="${x}" cy="${y}" r="5" fill="${t.config.source.enabled?'#dcffed':'#eee'}" stroke="#167963" stroke-width="1"/><circle cx="${x}" cy="${y}" r="1.5" fill="#167963"/><text x="${x+8}" y="${y+3}" font-size="6" fill="#23615e" stroke="#fff" stroke-width="1.5" paint-order="stroke">出光口 · Z${esc(t.element.axisHeightMm)}</text></g>`;
  }
  const b=d.imageBoundsMm,h=layout.board.heightMm,a=d.surfaceAngleDeg*Math.PI/180,dx=Math.cos(a)*d.lensDiameterMm/2,dy=Math.sin(a)*d.lensDiameterMm/2;
  const transform=p?`translate(${p.xMm} ${h-p.yMm}) rotate(${-p.rotationDeg})`:`translate(0 ${h})`;
  return `<g transform="${transform}" data-fixed-board-optic="${esc(t.id)}" role="button" tabindex="0" aria-label="${esc(d.name)} · 固定在腿6，点击设置透镜" style="cursor:pointer"><title>${esc(d.name)} · 位置与朝向固定，点击设置透镜</title><image x="${b.xMin}" y="${-b.yMax}" width="${b.xMax-b.xMin}" height="${b.yMax-b.yMin}" href="./${esc(d.topViewPath)}"/><rect x="${b.xMin}" y="${-b.yMax}" width="${b.xMax-b.xMin}" height="${b.yMax-b.yMin}" fill="transparent" stroke="#267d78" stroke-width=".8" stroke-dasharray="3 2"/><path d="M ${d.centerMm.xMm-dx} ${-d.centerMm.yMm+dy} L ${d.centerMm.xMm+dx} ${-d.centerMm.yMm-dy}" fill="none" stroke="${t.config.inserted?'#35bacd':'#809394'}" stroke-width="2"/><text x="${b.xMin}" y="${-b.yMax-4}" font-size="7" fill="#23615e" stroke="#fff" stroke-width="1.5" paint-order="stroke">固定 · R200</text></g>`;
 }).join('')}
 const api={normalizeState,targets,key,markup};root.ZZLabFixedBoardOptics=api;if(typeof module==='object'&&module.exports)module.exports=api;
 if(!root.BreadboardEditor)return;
 const P=root.BreadboardEditor.prototype;
 P.fixedBoardOpticalTarget=function(id){return targets(this.snapshot(),this.catalog,root.ZZLabOpticalEngine).find(t=>t.id===id)||null};
 P.saveFixedBoardOptics=function(id,optics){const t=this.fixedBoardOpticalTarget(id);if(!t)return false;const allowed=kind(t.def)==='source'?['elementType','inserted','configured','source']:fields,value=Object.fromEntries(allowed.filter(k=>k in optics).map(k=>[k,copy(optics[k])]));if(value.elementType!==kind(t.def))throw Error('固定器件不能更换光学类型。');if(value.source)delete value.source.directionAngleDeg;const board=t.ownerId===(this.activeBoardId||null)?this.board:t.ownerId?this.stacked?.subBoards.find(p=>p.id===t.ownerId)?.board:this.stacked?.board;if(!board)throw Error('对应面包板已被移除。');const next={...board,fixedOptics:{...(board.fixedOptics||{}),[t.def.id]:value}};normalizeState(next,this.catalog);const before=this.historySnapshot();this._opticalMutating=true;try{board.fixedOptics=next.fixedOptics;this.commit(before)}finally{this._opticalMutating=false}this.renderOptics();return true};
 const render=P.render;P.render=function(...args){const result=render.apply(this,args);if(!this.svg)return result;let layer=this.svg.querySelector('[data-fixed-board-optics-layer]');if(!layer){layer=root.document.createElementNS('http://www.w3.org/2000/svg','g');layer.setAttribute('data-fixed-board-optics-layer','')}/* markup uses whole-layout coordinates; never inherit the active board transform. */if(layer.parentNode!==this.svg)this.svg.appendChild(layer);const html=markup(this.snapshot(),this.catalog,root.ZZLabOpticalEngine);if(layer.innerHTML!==html)layer.innerHTML=html;return result};
 const bind=P.bind;P.bind=function(...args){const open=e=>{const hit=e.target.closest?.('[data-fixed-board-optic]');if(!hit)return;if(e.type==='keydown'&&!['Enter',' '].includes(e.key))return;e.preventDefault();e.stopImmediatePropagation();if(this.boardFormDirty||this.manualMounting)return this.notify('请先完成当前板的编辑。');this.openOpticalProperties(hit.getAttribute('data-fixed-board-optic'))};this.svg.addEventListener('pointerdown',open,true);this.svg.addEventListener('keydown',open,true);this.svg.addEventListener('contextmenu',open,true);return bind.apply(this,args)};
 const form=P.opticalFormMarkup;P.opticalFormMarkup=function(o){let html=form.call(this,o);if(this._opticalTarget?.fixedBoardOptic)html=html.replace(/<p class="optical-inline-note">光片外径不代表实际通光口径。[\s\S]*?<\/p>/,'<p class="optical-inline-note">请输入实物透镜与镜架组合的有效通光口径（最大25.4 mm）。光学面按原R7机械中心作名义近似。</p>').replace(/(<select[^>]*id="optics-type")/,'$1 disabled').replace(/(<input[^>]*id="optics-surface")/,'$1 readonly').replace(/(<input[^>]*id="optics-direction")/,'$1 readonly');return html};
})(typeof window==='object'?window:globalThis);
