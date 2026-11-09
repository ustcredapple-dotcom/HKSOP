/* Pure, DOM-independent optical trace: millimetres, X right / Y up, angles CCW. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.ZZLabOpticalEngine=api;})(typeof globalThis!=='undefined'?globalThis:this,function(root){
  'use strict';
  const EPS=1e-7,RAD=Math.PI/180,TYPES=['empty','mirror','dichroic','pbs','waveplate','lens','coupler','source','unsupported','aom'],POLS=['linear','circular-left','circular-right','elliptical','unpolarized'];
  const copy=x=>JSON.parse(JSON.stringify(x)),finite=x=>typeof x==='number'&&Number.isFinite(x),clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  const vec=a=>({x:Math.cos(a*RAD),y:Math.sin(a*RAD)}),dot=(a,b)=>a.x*b.x+a.y*b.y,cross=(a,b)=>a.x*b.y-a.y*b.x,add=(a,b)=>({x:a.x+b.x,y:a.y+b.y}),scale=(a,t)=>({x:a.x*t,y:a.y*t}),sub=(a,b)=>({x:a.x-b.x,y:a.y-b.y}),norm=v=>{const l=Math.hypot(v.x,v.y);if(!(l>EPS))throw new Error('光线方向不能为零。');return scale(v,1/l)};
  function number(value,fallback,label,min,max,nullable=false){if(value===undefined)return fallback;if(nullable&&value===null)return null;if(!finite(value)||value<min||value>max)throw new Error(`${label}需为 ${min}–${max} 的有限数值${nullable?'或留空':''}。`);return value}
  function boolean(value,fallback,label){if(value===undefined)return fallback;if(typeof value!=='boolean')throw new Error(`${label}需为是或否。`);return value}
  function defaults(type='empty'){
    if(!TYPES.includes(type))type='empty';
    return{elementType:type,configured:false,inserted:type==='coupler'||type==='source',surfaceAngleDeg:['mirror','dichroic','pbs'].includes(type)?45:0,pbsHandedness:'left',fastAxisDeg:0,retardanceDeg:180,designWavelengthNm:532,focalLengthMm:null,clearApertureMm:25.4,source:{enabled:false,wavelengthNm:532,powerMw:1,beamDiameterMm:2,polarizationType:'linear',polarizationAngleDeg:0,ellipticityDeg:0,wavefrontRadiusMm:null,beamQualityM2:1,directionAngleDeg:-90}};
  }
  function normalizeSource(input={},fallback={}){
    if(!input||typeof input!=='object'||Array.isArray(input))throw new Error('出光设置需为对象。');
    const d={...defaults('source').source,...fallback},s={...d,...input},polarizationType=s.polarizationType;
    if(!POLS.includes(polarizationType))throw new Error('不支持该偏振类型。');
    const radius=number(s.wavefrontRadiusMm,null,'波前曲率半径',-1e12,1e12,true);
    if(radius!==null&&Math.abs(radius)<1e-6)throw new Error('波前曲率半径不能为零；平面波前请留空。');
    return{enabled:boolean(s.enabled,false,'启用出光'),wavelengthNm:number(s.wavelengthNm,532,'波长（nm）',1,1e6),powerMw:number(s.powerMw,1,'功率（mW）',0,1e9),beamDiameterMm:number(s.beamDiameterMm,2,'1/e² 光斑直径（mm）',1e-6,1e4),polarizationType,polarizationAngleDeg:number(s.polarizationAngleDeg,0,'偏振角（°）',-3600,3600),ellipticityDeg:number(s.ellipticityDeg,0,'椭圆率角（°）',-45,45),wavefrontRadiusMm:radius,beamQualityM2:number(s.beamQualityM2,1,'M²',1,100),directionAngleDeg:number(s.directionAngleDeg,-90,'出光方向（°）',-3600,3600)};
  }
  function normalizePlate(s,d={}){if(!s||typeof s!=='object'||Array.isArray(s))throw new Error('每片波片设置需为对象。');return{inserted:boolean(s.inserted,d.inserted??false,'是否安装波片'),fastAxisDeg:number(s.fastAxisDeg,d.fastAxisDeg??0,'快轴角（°）',-3600,3600),retardanceDeg:number(s.retardanceDeg,d.retardanceDeg??180,'延迟（°）',-36000,36000),designWavelengthNm:number(s.designWavelengthNm,d.designWavelengthNm??532,'设计波长（nm）',1,1e6)}}
  function normalizeMirror(value){
    if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!['mode','model','samples'].includes(k))||!['ideal','data'].includes(value.mode)||!Array.isArray(value.samples)||value.samples.length>256)throw new Error('镜面参数需要 ideal/data 模式及最多 256 个完整数据点。');
    const result={mode:value.mode,samples:[]};
    if(value.model!==undefined){if(typeof value.model!=='string'||Array.from(value.model).length>160||/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value.model))throw new Error('镜片型号需为最多 160 字的文字。');result.model=value.model;}
    const fields=['wavelengthNm','incidenceAngleDeg','reflectanceP','reflectanceS','phaseDifferenceDeg'],seen=new Set();
    result.samples=value.samples.map(s=>{
      if(!s||typeof s!=='object'||Array.isArray(s)||Object.keys(s).length!==5||fields.some(k=>!Object.hasOwn(s,k)))throw new Error('镜面数据点需包含波长、入射角、Rp、Rs 和相位差五项。');
      if(!finite(s.wavelengthNm)||!finite(s.incidenceAngleDeg))throw new Error('数据点波长与入射角不能留空。');
      if(fields.slice(2).some(k=>s[k]!==null&&!finite(s[k])))throw new Error('镜面反射率与相位差需为有限数值或明确留空。');
      const identity=`${s.wavelengthNm}:${s.incidenceAngleDeg}`;if(seen.has(identity))throw new Error('同一波长与入射角不能有重复镜面数据点。');seen.add(identity);
      return{wavelengthNm:number(s.wavelengthNm,null,'数据波长（nm）',1,1e6),incidenceAngleDeg:number(s.incidenceAngleDeg,null,'数据入射角（°）',0,90),reflectanceP:number(s.reflectanceP,null,'P 反射率',0,1,true),reflectanceS:number(s.reflectanceS,null,'S 反射率',0,1,true),phaseDifferenceDeg:number(s.phaseDifferenceDeg,null,'镜面相位差（°）',-36000,36000,true)};
    });return result;
  }
  function normalizeZeroOrderPreview(v){
    const keys=['version','wavelengthNm','referenceAngleDeg','maxAngleDeviationDeg','output'];
    if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).length!==keys.length||keys.some(k=>!Object.hasOwn(v,k))||v.version!==1||!['reflected','transmitted'].includes(v.output)||!['wavelengthNm','referenceAngleDeg','maxAngleDeviationDeg'].every(k=>finite(v[k])))throw Error('零级几何预览需要完整v1波长、参考角、允许角差和路由；不代表镀膜数据。');
    return{version:1,wavelengthNm:number(v.wavelengthNm,null,'几何预览波长',1,1e6),referenceAngleDeg:number(v.referenceAngleDeg,null,'参考入射角',0,90),maxAngleDeviationDeg:number(v.maxAngleDeviationDeg,null,'几何预览角差',.000001,5),output:v.output};
  }
  function normalizeDichroic(value){
    const fields=['wavelengthNm','incidenceAngleDeg','reflectanceP','reflectanceS','transmittanceP','transmittanceS','reflectionPhaseDifferenceDeg','transmissionPhaseDifferenceDeg'];
    if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!['mode','model','samples','zeroOrderPreview'].includes(k))||value.mode!=='data'||!Array.isArray(value.samples)||value.samples.length>256)throw new Error('双色镜需要 data 模式及最多 256 个完整数据点。');
    const model=normalizeMirror({mode:'data',...(value.model!==undefined?{model:value.model}:{}),samples:[]}),seen=new Set();
    const samples=value.samples.map(s=>{
      if(!s||typeof s!=='object'||Array.isArray(s)||Object.keys(s).length!==8||fields.some(k=>!Object.hasOwn(s,k)))throw new Error('双色镜数据点需完整包含波长、入射角、Rp/Rs、Tp/Ts 和反射/透射相位差八项。');
      if(!finite(s.wavelengthNm)||!finite(s.incidenceAngleDeg)||fields.slice(2).some(k=>s[k]!==null&&!finite(s[k])))throw new Error('双色镜数据波长与角度需为有限数值，系数和相位可明确留空。');
      const identity=`${s.wavelengthNm}:${s.incidenceAngleDeg}`;if(seen.has(identity))throw new Error('同一波长与入射角不能有重复双色镜数据点。');seen.add(identity);
      const r={wavelengthNm:number(s.wavelengthNm,null,'数据波长',1,1e6),incidenceAngleDeg:number(s.incidenceAngleDeg,null,'数据入射角',0,90)};
      for(const k of fields.slice(2))r[k]=number(s[k],null,k,k.endsWith('Deg')?-36000:0,k.endsWith('Deg')?36000:1,true);
      for(const polarization of ['P','S'])if(r['reflectance'+polarization]!==null&&r['transmittance'+polarization]!==null&&r['reflectance'+polarization]+r['transmittance'+polarization]>1+1e-12)throw new Error('无源双色镜的反射率与透射率之和不能大于 1。');
      return r;
    });return{mode:'data',...(model.model!==undefined?{model:model.model}:{}),samples,...(value.zeroOrderPreview!==undefined?{zeroOrderPreview:normalizeZeroOrderPreview(value.zeroOrderPreview)}:{})};
  }

  function normalizeLensPrescription(p){
    if(!p||p.version!==1||p.kind!=='plano-convex'||p.material!=='fused_silica'||Object.keys(p).some(k=>!['version','kind','material','model','frontRadiusMm','thicknessMm','frontVertexOffsetMm'].includes(k)))throw Error('不支持的实体透镜处方；目前支持有出处的熔融石英平凸透镜。');
    if(!['frontRadiusMm','thicknessMm','frontVertexOffsetMm'].every(k=>finite(p[k])))throw Error('实体透镜处方尺寸必须完整。');
    if(typeof p.model!=='string'||!p.model||p.model.length>160)throw Error('实体透镜需提供型号。');
    return{version:1,kind:p.kind,material:p.material,model:p.model,frontRadiusMm:number(p.frontRadiusMm,null,'前曲率半径',1e-3,1e6),thicknessMm:number(p.thicknessMm,null,'中心厚度',1e-4,1e3),frontVertexOffsetMm:number(p.frontVertexOffsetMm,null,'前顶点偏置',-1e4,1e4)};
  }
  function silicaLensIndex(nm){if(!(nm>=210&&nm<=3700))throw Error('熔融石英处方超出色散模型有效范围。');const u=(nm/1000)**2;return Math.sqrt(1+.6961663*u/(u-.0684043**2)+.4079426*u/(u-.1162414**2)+.8974794*u/(u-9.896161**2));}
  function physicalLensHit(origin,direction,element,inside=false){
    const p=element.optics.lensPrescription,a=vec(elementAngle(element)-90),t=vec(elementAngle(element)),front=add(element.center,scale(a,p.frontVertexOffsetMm)),rear=add(front,scale(a,p.thicknessMm)),sc=add(front,scale(a,p.frontRadiusMm)),hits=[];
    const put=(distance,surface,point,inward,radius)=>{const entering=dot(direction,inward)>0;if(distance<=EPS||entering===inside)return;const offset=dot(sub(point,front),t);if(Math.abs(offset)>element.optics.clearApertureMm/2+EPS)return;hits.push({distance,offset,point,element,lensSurface:{surface,entering,normal:entering?inward:scale(inward,-1),radiusMm:radius===null?null:(entering?radius:-radius)}});};
    const v=sub(origin,sc),b=dot(v,direction),disc=b*b-dot(v,v)+p.frontRadiusMm**2;
    if(disc>=0)for(const distance of[-b-Math.sqrt(disc),-b+Math.sqrt(disc)]){const point=add(origin,scale(direction,distance));if(dot(sub(point,sc),a)>EPS)continue;put(distance,'curved',point,norm(sub(sc,point)),p.frontRadiusMm);}
    const den=dot(direction,a);if(Math.abs(den)>EPS){const distance=dot(sub(rear,origin),a)/den;put(distance,'plane',add(origin,scale(direction,distance)),scale(a,-1),null);}
    return hits.sort((x,y)=>x.distance-y.distance)[0]||null;
  }
  function refractLensSurface(direction,normal,n1,n2){const ci=dot(direction,normal),eta=n1/n2,s2=eta*eta*(1-ci*ci);if(ci<=0||s2>1)return null;return norm(add(scale(direction,eta),scale(normal,Math.sqrt(Math.max(0,1-s2))-eta*ci)));}
  function refractLensQ(q,n1,n2,ci,cr,radius,tangential){const power=radius===null?0:(n2*cr-n1*ci)/radius,A=tangential?cr/ci:1,D=tangential?n1*ci/(n2*cr):n1/n2,C=tangential?-power/(n2*ci*cr):-power/n2;return cdiv({re:A*q.re,im:A*q.im},{re:C*q.re+D,im:C*q.im});}
  function advancePhysicalLens(session,element,ray,next){
    const s=ray.lensSurface,p=element.optics.lensPrescription,ng=silicaLensIndex(ray.beam.wavelengthNm),n1=s.entering?1:ng,n2=s.entering?ng:1,out=refractLensSurface(ray.direction,s.normal,n1,n2);
    if(Math.abs((ray.beam.mediumIndex||1)-n1)>1e-7){warning(session,'lens_medium_mismatch','实体透镜当前仅支持空气中的独立镜片。',element.id);session.pending.push({...ray,blockedIssue:{code:'lens_medium_mismatch',message:'透镜周围介质不匹配。'}});return;}
    if(!out){warning(session,'lens_total_internal_reflection','透镜界面全反射，未继续透射路径。',element.id);complete(session,next,'lens-total-internal-reflection');return;}
    const ci=dot(ray.direction,s.normal),cr=dot(out,s.normal);next.beam.q=refractLensQ(ray.beam.q,n1,n2,ci,cr,s.radiusMm,true);next.beam.qSagittal=refractLensQ(ray.beam.qSagittal||ray.beam.q,n1,n2,ci,cr,s.radiusMm,false);next.beam.mediumIndex=n2;next.direction=out;
    delete next.lensSurface;if(s.entering)next.lensInsideId=element.id;else delete next.lensInsideId;
    session.lensEvents=session.lensEvents||[];session.lensEvents.push({instanceId:element.id,sourceId:ray.sourceId,branchId:ray.branchId,model:p.model,surface:s.surface,point:copy(ray.point),entering:s.entering,n1,n2,normal:s.normal,incoming:ray.direction,outgoing:out,incidenceDeg:Math.acos(clamp(ci,-1,1))/RAD,refractionDeg:Math.acos(clamp(cr,-1,1))/RAD});
    warning(session,'physical_lens_paraxial_envelope','实体透镜按真实曲面/厚度及色散逐面折射中心线；高斯包络使用局部近轴折射矩阵，未计算球差、衍射截光或镀膜损耗。',element.id);extend(session,next);
  }


  // Geometry-only AOM model: nominal optical wavelength is retained for coating tables.
  // RF shift is tracked separately. Equal preview weights are not diffraction efficiencies.
  function normalizeAom(a){
    const fields=['version','angleMrad','referenceWavelengthNm','rfMHz','awayLocalDeg','powerMode','nominalDatumAccepted'];
    if(!a||typeof a!=='object'||Array.isArray(a)||Object.keys(a).length!==fields.length||fields.some(k=>!Object.hasOwn(a,k))||a.version!==1||a.powerMode!=='geometry-only'||a.nominalDatumAccepted!==true)throw Error('AOM需要完整v1名义几何配置；必须明确接受名义作用点，功率仅作归一化显示。');
    for(const k of ['angleMrad','referenceWavelengthNm','rfMHz','awayLocalDeg'])if(!finite(a[k]))throw Error('AOM数值参数必须完整且有限。');
    return {version:1,angleMrad:number(a.angleMrad,null,'AOM零级/+1夹角(mrad)',.000001,100),referenceWavelengthNm:number(a.referenceWavelengthNm,null,'AOM参考波长',1,1e6),rfMHz:number(a.rfMHz,null,'RF频率(MHz)',.001,10000),awayLocalDeg:number(a.awayLocalDeg,null,'远离线缆方向(局部度)',-3600,3600),powerMode:'geometry-only',nominalDatumAccepted:true};
  }
  function aomIssue(e,ray){
    const a=e.optics.aom;if(!a)return {code:'aom_config_missing',message:'AOM衍射角、方向与名义基准尚未填写。'};
    if(Math.abs(ray.beam.wavelengthNm-a.referenceWavelengthNm)>.01)return {code:'aom_wavelength_mismatch',message:'AOM仅按已填写的参考波长估算；此波长未标定。'};
    const away=vec(e.rotationDeg+a.awayLocalDeg);
    if(Math.abs(cross(ray.direction,away))<.5)return {code:'aom_deflection_ambiguous',message:'远离线缆方向接近传播轴，无法确定横向正一级；请核对安装方向。'};
    return null;
  }
  function advanceAom(session,e,ray,next){
    const issue=aomIssue(e,ray);if(issue){session.pending.push(ray);warning(session,issue.code,issue.message,e.id);return;}
    const a=e.optics.aom,away=vec(e.rotationDeg+a.awayLocalDeg),theta=Math.sign(cross(ray.direction,away))*a.angleMrad/1000,inAngle=Math.atan2(ray.direction.y,ray.direction.x),d={x:Math.cos(inAngle+theta),y:Math.sin(inAngle+theta)};
    warning(session,'aom_nominal_geometry','AOM采用名义作用点与估算偏角；0/+1仅示意归一化权重，效率/绝对功率未知。波长沿用名义值计算透镜与镀膜，RF频移单独记录。',e.id);
    session.aomEvents=session.aomEvents||[];session.aomEvents.push({instanceId:e.id,sourceId:ray.sourceId,point:copy(ray.point),incoming:ray.direction,zeroOrder:ray.direction,positiveFirstOrder:d,angleMrad:a.angleMrad,awayWorld:away,rfMHz:a.rfMHz});
    for(const order of [0,1]){
      const label=order?'aom:+1':'aom:0',branchPath=[...(ray.branchPath||[]),{instanceId:e.id,encounter:(ray.branchPath||[]).filter(p=>p.instanceId===e.id).length+1,output:label}],beam={...copy(next.beam),powerMw:next.beam.powerMw/2,powerIsRelative:true,frequencyShiftMHz:(next.beam.frequencyShiftMHz||0)+(order?a.rfMHz:0),aomOrders:[...(next.beam.aomOrders||[]),{instanceId:e.id,order}]};
      const outgoing={...next,beam,direction:order?d:ray.direction,parentBranchId:ray.branchId,branchPath,lineageKey:JSON.stringify([ray.sourceId,...branchPath])};
      if(session.counters.branches>=session.options.maxBranches){warning(session,'branch_limit','AOM分支数量达到上限。',e.id);complete(session,outgoing,'branch-limit');continue;}
      extend(session,{...outgoing,branchId:`branch-${++session.counters.branches}`});
    }
  }

  function normalizeOptics(input={},fallback={}){
    if(!input||typeof input!=='object'||Array.isArray(input))throw new Error('光学设置需为对象。');
    const type=input.elementType??fallback.elementType??'empty';if(!TYPES.includes(type))throw new Error('不支持该光学元件类型。');
    const d={...defaults(type),...fallback},s={...d,...input},p=normalizePlate(s,d),f=number(s.focalLengthMm,null,'焦距（mm）',-1e6,1e6,true);if(f!==null&&Math.abs(f)<1e-6)throw new Error('透镜焦距不能为零。');if(!['left','right'].includes(s.pbsHandedness))throw new Error('PBS 手性需为 left 或 right。');
    const result={elementType:type,configured:boolean(s.configured,false,'是否已确认光学配置'),inserted:boolean(s.inserted,false,'是否已安装光学件'),surfaceAngleDeg:number(s.surfaceAngleDeg,0,'光学平面角（°）',-3600,3600),pbsHandedness:s.pbsHandedness,fastAxisDeg:p.fastAxisDeg,retardanceDeg:p.retardanceDeg,designWavelengthNm:p.designWavelengthNm,focalLengthMm:f,clearApertureMm:number(s.clearApertureMm,25.4,'有效口径（mm）',1e-6,1e4),source:normalizeSource(input.source??{},d.source)};
    if(s.aom!==undefined){if(type!=='aom')throw Error('AOM配置只适用于aom类型。');result.aom=normalizeAom(s.aom);}
    if(s.lensPrescription!==undefined){if(type!=='lens')throw Error('实体透镜处方只适用于lens。');result.lensPrescription=normalizeLensPrescription(s.lensPrescription);if(result.clearApertureMm/2>=result.lensPrescription.frontRadiusMm)throw Error('透镜曲率半径小于通光半径。');}
    if(s.waveplates!==undefined){if(!Array.isArray(s.waveplates)||s.waveplates.length>8)throw new Error('一个器件可配置 0–8 片波片。');result.waveplates=s.waveplates.map(v=>normalizePlate(v));}if(s.mirror!==undefined)result.mirror=normalizeMirror(s.mirror);if(s.dichroic!==undefined)result.dichroic=normalizeDichroic(s.dichroic);if(s.coatingFaceIndex!==undefined){if(s.coatingFaceIndex!==null&&s.coatingFaceIndex!==0&&s.coatingFaceIndex!==1)throw new Error('镀膜面需为 0、1 或留空。');result.coatingFaceIndex=s.coatingFaceIndex;}return result;
  }
  function validateOptics(input,fallback){try{return{valid:true,value:normalizeOptics(input,fallback),errors:[]}}catch(e){return{valid:false,value:null,errors:[e.message]}}}
  function stokesFromSource(source){const s=normalizeSource(source);if(s.polarizationType==='unpolarized')return{s0:1,s1:0,s2:0,s3:0};const a=s.polarizationAngleDeg*RAD,e=(s.polarizationType==='circular-left'?45:s.polarizationType==='circular-right'?-45:s.polarizationType==='elliptical'?s.ellipticityDeg:0)*RAD;return{s0:1,s1:Math.cos(2*e)*Math.cos(2*a),s2:Math.cos(2*e)*Math.sin(2*a),s3:Math.sin(2*e)}}
  function cleanStokes(s){const r={s0:1,s1:s.s1||0,s2:s.s2||0,s3:s.s3||0},l=Math.hypot(r.s1,r.s2,r.s3);if(l>1){r.s1/=l;r.s2/=l;r.s3/=l}for(const k of ['s1','s2','s3'])if(Math.abs(r[k])<1e-14)r[k]=0;return r}
  function applyWaveplate(stokes,fastAxisDeg,retardanceDeg){const a=2*fastAxisDeg*RAD,d=retardanceDeg*RAD,n=[Math.cos(a),Math.sin(a),0],v=[stokes.s1,stokes.s2,stokes.s3],c=Math.cos(d),s=Math.sin(d),projection=n[0]*v[0]+n[1]*v[1];return cleanStokes({s1:v[0]*c+n[1]*v[2]*s+n[0]*projection*(1-c),s2:v[1]*c-n[0]*v[2]*s+n[1]*projection*(1-c),s3:v[2]*c+(n[0]*v[1]-n[1]*v[0])*s})}
  // exp(-i omega t), right-handed (P,S,k), S=+Z, P=S cross k.
  // Q=|Ep|²-|Es|², U=2 Re(Ep Es*), V=-2 Im(Ep Es*).
  // A fast-P retarder is diag(1, exp(i retardance)); the existing Rodrigues
  // rotation above therefore increases V from +U for positive retardance.
  // NIST SCATMECH documents the phasor/handed-basis convention (with its
  // components ordered S,P instead): https://pages.nist.gov/SCATMECH/docs/convent.htm
  function checkedStokes(stokes){
    if(!stokes||!['s1','s2','s3'].every(k=>finite(stokes[k])))throw new Error('入射 Stokes 参数无效。');
    const s0=stokes.s0===undefined?1:stokes.s0;if(!finite(s0)||s0<=0)throw new Error('Stokes 总强度必须大于零。');
    const s={s0:1,s1:stokes.s1/s0,s2:stokes.s2/s0,s3:stokes.s3/s0};if(Math.hypot(s.s1,s.s2,s.s3)>1+1e-9)throw new Error('Stokes 偏振度不能大于 1。');return cleanStokes(s);
  }
  function incidenceAngleDeg(direction,planeAngleDeg){const d=norm(direction),t=vec(planeAngleDeg);return Math.acos(clamp(Math.abs(cross(d,t)),0,1))/RAD;}
  function resolveMirrorResponse(mirror,wavelengthNm,aoi,mirrorCoating){
    number(wavelengthNm,null,'入射波长（nm）',1,1e6);number(aoi,null,'实际入射角（°）',0,90);
    if(!finite(wavelengthNm)||!finite(aoi))throw new Error('需要实际入射波长和入射角。');
    const base={wavelengthNm,incidenceAngleDeg:aoi};
    if(mirror===undefined||normalizeMirror(mirror).mode==='ideal')return{...base,ok:true,mode:'ideal',legacy:mirror===undefined,approximate:true,response:{reflectanceP:1,reflectanceS:1,phaseDifferenceDeg:180}};
    const matches=s=>Math.abs(s.wavelengthNm-wavelengthNm)<=1e-6&&Math.abs(s.incidenceAngleDeg-aoi)<=1e-6;
    let samples=mirror.samples.filter(matches),origin='manual';
    const sameModel=typeof mirror.model==='string'&&mirror.model.trim()&&typeof mirrorCoating?.model==='string'&&mirror.model.trim().toUpperCase()===mirrorCoating.model.trim().toUpperCase();
    if(!samples.length&&sameModel&&Array.isArray(mirrorCoating.samples)){samples=mirrorCoating.samples.filter(matches);origin='catalog';try{for(const sample of samples)normalizeMirror({mode:'data',samples:[sample]});}catch(error){return{...base,ok:false,origin,reason:'invalid_catalog_data',code:'mirror_catalog_invalid',message:'厂家曲线在此点包含超出物理范围或不完整的数值，请核对数据；不会自动截断或修正。'};}}
    if(!samples.length)return{...base,ok:false,reason:'missing_sample',code:'mirror_sample_mismatch',message:`缺少 ${Number(wavelengthNm.toFixed(6))} nm、入射角 ${Number(aoi.toFixed(6))}° 的镜面 Rp、Rs 与相位差；不会外推其他数据点。`};
    if(samples.some(s=>s.reflectanceP===null||s.reflectanceS===null||s.phaseDifferenceDeg===null))return{...base,ok:false,origin,response:{reflectanceP:samples[0].reflectanceP,reflectanceS:samples[0].reflectanceS,phaseDifferenceDeg:samples[0].phaseDifferenceDeg},reason:'missing_coefficients',code:'mirror_data_missing',message:'当前波长与入射角的镜面反射率或相位差尚未填写，不能按零相位继续传播。'};
    const sample=samples[0],same=s=>Math.abs(s.reflectanceP-sample.reflectanceP)<=1e-12&&Math.abs(s.reflectanceS-sample.reflectanceS)<=1e-12&&Math.abs(Math.sin((s.phaseDifferenceDeg-sample.phaseDifferenceDeg)*RAD/2))<=1e-12;
    if(!samples.every(same))return{...base,ok:false,reason:'conflicting_samples',code:'mirror_data_conflict',message:'同一波长与入射角存在相互矛盾的镜面数据点，请保留明确的一组。'};
    return{...base,ok:true,mode:'data',origin,approximate:false,response:{reflectanceP:sample.reflectanceP,reflectanceS:sample.reflectanceS,phaseDifferenceDeg:sample.phaseDifferenceDeg}};
  }
  function mirrorPhaseIndependent(stokes,rp,rs){return rp===0||rs===0||stokes.s2===0&&stokes.s3===0;}
  function mirrorResponseAt(mirror,beam,aoi,mirrorCoating){
    const result=resolveMirrorResponse(mirror,beam.wavelengthNm,aoi,mirrorCoating),r=result.response;
    if(!result.ok&&result.reason==='missing_coefficients'&&r?.phaseDifferenceDeg===null&&finite(r.reflectanceP)&&finite(r.reflectanceS)&&mirrorPhaseIndependent(checkedStokes(beam.stokes),r.reflectanceP,r.reflectanceS)){
      const reason=r.reflectanceP===0||r.reflectanceS===0?'single-polarization-reflection':'incoherent-input';
      return{wavelengthNm:result.wavelengthNm,incidenceAngleDeg:result.incidenceAngleDeg,ok:true,mode:'data',origin:result.origin,approximate:false,phaseIndependent:true,phaseIndependentReason:reason,response:r};
    }return result;
  }
  function mirrorResponseFor(element,beam,direction){return mirrorResponseAt(element.optics.mirror,beam,incidenceAngleDeg(direction,elementAngle(element)),element.mirrorCoating);}
  function dichroicResponseAt(dichroic,beam,aoi,coating){
    const wavelengthNm=number(beam.wavelengthNm,null,'入射波长',1,1e6),base={wavelengthNm,incidenceAngleDeg:number(aoi,null,'实际入射角',0,90)},missing=(code,message,extra={})=>({...base,ok:false,code,message,...extra});
    if(!finite(aoi)||!finite(wavelengthNm))throw new Error('需要实际入射波长和入射角。');
    const d=normalizeDichroic(dichroic||{mode:'data',samples:[]}),match=s=>Math.abs(s.wavelengthNm-wavelengthNm)<=1e-6&&Math.abs(s.incidenceAngleDeg-aoi)<=1e-6;
    let points=d.samples.filter(match),origin='manual';
    if(!points.length&&d.model?.trim()&&d.model.trim().toUpperCase()===coating?.model?.trim().toUpperCase()&&Array.isArray(coating.samples)){points=coating.samples.filter(match);origin='catalog';try{for(const sample of points)normalizeDichroic({mode:'data',samples:[sample]});}catch(error){return missing('dichroic_catalog_invalid','厂家双色镜数据点不完整或超出物理范围，请核对。');}}
    if(!points.length)return missing('dichroic_sample_mismatch',`缺少 ${Number(wavelengthNm.toFixed(6))} nm、入射角 ${Number(aoi.toFixed(6))}° 的双色镜数据；不会外推。`);
    if(points.length!==1)return missing('dichroic_data_conflict','同一波长与入射角的双色镜数据不唯一，请核对。');
    const response=copy(points[0]),s=checkedStokes(beam.stokes),amplitude=['reflectanceP','reflectanceS','transmittanceP','transmittanceS'];
    if(amplitude.some(k=>!finite(response[k])))return missing('dichroic_data_missing','双色镜反射率或透射率尚未填写，不能继续传播。',{response,origin});
    const reflectionPhaseIndependent=response.reflectionPhaseDifferenceDeg===null&&mirrorPhaseIndependent(s,response.reflectanceP,response.reflectanceS),transmissionPhaseIndependent=response.transmissionPhaseDifferenceDeg===null&&mirrorPhaseIndependent(s,response.transmittanceP,response.transmittanceS);
    if(response.reflectionPhaseDifferenceDeg===null&&!reflectionPhaseIndependent||response.transmissionPhaseDifferenceDeg===null&&!transmissionPhaseIndependent)return missing('dichroic_phase_missing','当前入射偏振需要双色镜反射和透射的 P/S 相位差；未知相位不会按零处理。',{response,origin});
    return{...base,ok:true,mode:'data',origin,response,reflectionPhaseIndependent,transmissionPhaseIndependent,phaseIndependent:reflectionPhaseIndependent||transmissionPhaseIndependent};
  }
  function dichroicResponseFor(element,beam,direction){
    const aoi=incidenceAngleDeg(direction,elementAngle(element)),r=dichroicResponseAt(element.optics.dichroic,beam,aoi,element.dichroicCoating),v=element.optics.dichroic?.zeroOrderPreview;
    if(r.code==='dichroic_sample_mismatch'&&v&&beam.aomOrders?.at(-1)?.order===0&&beam.powerIsRelative===true&&Math.abs(beam.wavelengthNm-v.wavelengthNm)<1e-6&&Math.abs(aoi-v.referenceAngleDeg)<=v.maxAngleDeviationDeg)return{...r,ok:true,mode:'geometry-only',output:v.output,nominalRouting:copy(v)};
    return r;
  }
  function applyDichroic(beam,response){
    normalizeDichroic({mode:'data',samples:[{wavelengthNm:beam.wavelengthNm,incidenceAngleDeg:response.incidenceAngleDeg??0,...response}]});
    const reflected=applyMirror(beam,{reflectanceP:response.reflectanceP,reflectanceS:response.reflectanceS,phaseDifferenceDeg:response.reflectionPhaseDifferenceDeg}),transmitted=applyMirror(beam,{reflectanceP:response.transmittanceP,reflectanceS:response.transmittanceS,phaseDifferenceDeg:response.transmissionPhaseDifferenceDeg});
    return{reflected,transmitted,absorbedPowerMw:Math.max(0,beam.powerMw-reflected.powerMw-transmitted.powerMw)};
  }
  function applyMirror(beam,response){
    const s=checkedStokes(beam.stokes),rp=number(response.reflectanceP,null,'P 反射率',0,1),rs=number(response.reflectanceS,null,'S 反射率',0,1),phase=number(response.phaseDifferenceDeg,null,'镜面相位差（°）',-36000,36000,true),phaseIndependent=response.phaseDifferenceDeg===null&&mirrorPhaseIndependent(s,rp,rs);
    if(!finite(rp)||!finite(rs)||!finite(phase)&&!phaseIndependent)throw new Error('此入射偏振的计算需要完整的 Rp、Rs 和相位差。');
    const power=(rp*(1+s.s1)+rs*(1-s.s1))/2,g=Math.sqrt(rp*rs);let u=0,v=0;
    if(phase!==null){const delta=phase*RAD,c=Math.cos(delta),sin=Math.sin(delta);u=g*(s.s2*c+s.s3*sin);v=g*(-s.s2*sin+s.s3*c);}
    const out=power>1e-15?cleanStokes({s1:(rp*(1+s.s1)-rs*(1-s.s1))/(2*power),s2:u/power,s3:v/power}):{s0:1,s1:0,s2:0,s3:0};
    return{...copy(beam),powerMw:beam.powerMw*power,stokes:out};
  }
  function waveplateReverse(element,direction){return dot(direction,vec(elementAngle(element)-90))<0;}
  function applyWaveplateSequence(stokes,plates,reverse=false){let output=checkedStokes(stokes);for(const p of reverse?[...plates].reverse():plates){if(p.inserted===false)continue;output=applyWaveplate(output,reverse?-p.fastAxisDeg:p.fastAxisDeg,p.retardanceDeg);}return output;}
  function solveTwoWaveplates({incomingStokes,plates,wavelengthNm,reverse=false,target,tolerance=1e-6}={}){
    // Fixed-input, local solve only. The caller must exclude self-dependent
    // return encounters: adjusting an earlier pass through these same plates
    // changes the incoming Stokes, requiring a full-scene feedback solve.
    const failure=(reason,message,extra={})=>({ok:false,reason,message,...extra});
    let incoming,actual,targetStokes;
    try{
      incoming=checkedStokes(incomingStokes);if(!finite(wavelengthNm)||wavelengthNm<1||wavelengthNm>1e6)throw new Error('请选择实际入射光束的波长。');
      if(!Array.isArray(plates)||plates.length!==2||plates.some(p=>!p||p.inserted!==true||!finite(p.retardanceDeg)||!finite(p.designWavelengthNm)))throw new Error('需要两片已安装且已填写实际延迟与设计波长的波片。');
      actual=plates.map(p=>normalizePlate(p));if(typeof reverse!=='boolean'||!finite(tolerance)||tolerance<1e-10||tolerance>1e-3)throw new Error('求解方向或误差限制无效。');
      if(!target||!['linear','circular-left','circular-right','elliptical','unpolarized'].includes(target.polarizationType))throw new Error('请选择明确的目标偏振类型。');
      targetStokes=stokesFromSource(target);
    }catch(error){return failure('invalid_input',error.message);}
    if(actual.some(p=>Math.abs(p.designWavelengthNm-wavelengthNm)>.01))return failure('wavelength_mismatch','波片延迟的数据波长与这次入射波长不同；请先填写实际波长下的延迟，不能用设计延迟推测色散。');
    const degree=Math.hypot(incoming.s1,incoming.s2,incoming.s3),targetDegree=Math.hypot(targetStokes.s1,targetStokes.s2,targetStokes.s3);
    if(Math.abs(degree-targetDegree)>tolerance)return failure('polarization_degree_mismatch','无损波片不能改变偏振度，这束光无法达到所选目标偏振。',{error:Math.abs(degree-targetDegree),targetStokes});
    const wrap=a=>((a%180)+180)%180,keys=['s1','s2','s3'];let evaluations=0;
    const evaluate=angles=>{evaluations++;const output=applyWaveplateSequence(incoming,actual.map((p,i)=>({...p,fastAxisDeg:angles[i]})),reverse),residual=keys.map(k=>output[k]-targetStokes[k]);return{angles:angles.map(wrap),output,residual,loss:residual.reduce((s,x)=>s+x*x,0)}};
    const seeds=[evaluate(actual.map(p=>p.fastAxisDeg))];for(let a=0;a<180;a+=15)for(let b=0;b<180;b+=15)seeds.push(evaluate([a,b]));seeds.sort((a,b)=>a.loss-b.loss);let best=seeds[0];
    for(const seed of seeds.slice(0,24)){
      let candidate=seed,lambda=1e-5;
      for(let iteration=0;iteration<70&&candidate.loss>tolerance*tolerance/100;iteration++){
        const h=.001,derivatives=[0,1].map(axis=>{const plus=[...candidate.angles],minus=[...candidate.angles];plus[axis]+=h;minus[axis]-=h;const p=evaluate(plus),m=evaluate(minus);return keys.map((_,j)=>(p.residual[j]-m.residual[j])/(2*h));});
        const j=derivatives[0],k=derivatives[1],a=j.reduce((s,x)=>s+x*x,lambda),b=j.reduce((s,x,n)=>s+x*k[n],0),d=k.reduce((s,x)=>s+x*x,lambda),r=j.reduce((s,x,n)=>s+x*candidate.residual[n],0),t=k.reduce((s,x,n)=>s+x*candidate.residual[n],0),det=a*d-b*b;
        if(!(det>1e-22))break;let step=[(-d*r+b*t)/det,(b*r-a*t)/det],length=Math.hypot(...step);if(length>30)step=step.map(x=>x*30/length);
        const moved=evaluate(candidate.angles.map((x,n)=>x+step[n]));if(moved.loss<candidate.loss){candidate=moved;lambda=Math.max(1e-12,lambda*.3);}else{lambda*=10;if(lambda>1e5)break;}
      }
      if(candidate.loss<best.loss)best=candidate;if(best.loss<=tolerance*tolerance/100)break;
    }
    // Verify the rounded, returned settings, not merely the optimizer's internal state.
    const angles=best.angles.map(a=>Number(wrap(a).toFixed(8))),verified=evaluate(angles),error=Math.sqrt(verified.loss),details={outputStokes:verified.output,targetStokes,error,evaluations,reverse};
    if(error>tolerance)return failure('unreachable','当前参数未找到满足目标误差要求的两片波片角度；未应用任何角度。',details);
    return{ok:true,anglesDeg:angles,...details};
  }
  function splitPBS(beam){const f=clamp((1+beam.stokes.s1)/2,0,1);return{transmitted:{...copy(beam),powerMw:beam.powerMw*f,stokes:{s0:1,s1:1,s2:0,s3:0}},reflected:{...copy(beam),powerMw:beam.powerMw*(1-f),stokes:{s0:1,s1:-1,s2:0,s3:0}},transmission:f,reflection:1-f}}
  const cdiv=(a,b)=>{const m=b.re*b.re+b.im*b.im;return{re:(a.re*b.re+a.im*b.im)/m,im:(a.im*b.re-a.re*b.im)/m}},cinv=q=>cdiv({re:1,im:0},q);
  function initialQ(source){const s=normalizeSource(source),w=s.beamDiameterMm/2,q=cinv({re:s.wavefrontRadiusMm===null?0:1/s.wavefrontRadiusMm,im:-s.beamQualityM2*s.wavelengthNm*1e-6/(Math.PI*w*w)});if(!finite(q.re)||!finite(q.im)||q.im<=0)throw new Error('光斑参数超出数值计算范围，请检查直径、波长和波前曲率。');return q}
  const propagateQ=(q,d)=>({re:q.re+d,im:q.im});
  function lensQ(q,f){if(!finite(f)||Math.abs(f)<1e-6)throw new Error('透镜焦距不能为零。');const inv=cinv(q);return cinv({re:inv.re-1/f,im:inv.im})}
  function gaussianAt(beam,d=0){const q=propagateQ(beam.q,d),lambda=beam.wavelengthNm*1e-6*(beam.beamQualityM2||1)/(beam.mediumIndex||1),inv=cinv(q),diameterMm=2*Math.sqrt(-lambda/(Math.PI*inv.im)),waistDiameterMm=2*Math.sqrt(lambda*q.im/Math.PI);return{...copy(beam),q,...(beam.qSagittal?{qSagittal:propagateQ(beam.qSagittal,d)}:{}),diameterMm,waistDiameterMm,wavefrontRadiusMm:Math.abs(inv.re)<1e-15?null:1/inv.re,focusDistanceMm:-q.re}}
  function createBeam(source,axisHeightMm=null){const s=normalizeSource(source);return{wavelengthNm:s.wavelengthNm,powerMw:s.powerMw,sourcePowerMw:s.powerMw,stokes:stokesFromSource(s),q:initialQ(s),qSagittal:initialQ(s),mediumIndex:1,beamQualityM2:s.beamQualityM2,axisHeightMm}}
  function reflect(direction,planeAngleDeg){const t=vec(planeAngleDeg);return norm(sub(scale(t,2*dot(direction,t)),direction))}
  function elementAngle(element){const o=element.optics;return(element.rotationDeg||0)+(o.elementType==='pbs'?(o.pbsHandedness==='right'?-o.surfaceAngleDeg:o.surfaceAngleDeg):o.surfaceAngleDeg)}
  function planeHit(origin,direction,element){const t=vec(elementAngle(element)),den=cross(direction,t);if(Math.abs(den)<EPS)return null;const distance=cross(sub(element.center,origin),t)/den,offset=cross(sub(element.center,origin),direction)/den;if(distance<=EPS||Math.abs(offset)>element.optics.clearApertureMm/2+EPS)return null;return{distance,offset,point:add(origin,scale(direction,distance)),element}}
  function exitDistance(origin,direction,bounds){let entry=-Infinity,exit=Infinity;for(const [axis,lo,hi]of[['x',bounds.xMin,bounds.xMax],['y',bounds.yMin,bounds.yMax]]){if(Math.abs(direction[axis])<=EPS){if(origin[axis]<lo-EPS||origin[axis]>hi+EPS)return 0;continue}const a=(lo-origin[axis])/direction[axis],b=(hi-origin[axis])/direction[axis];entry=Math.max(entry,Math.min(a,b));exit=Math.min(exit,Math.max(a,b))}return exit>=Math.max(entry,EPS)?exit:0}
  function insidePolygon(point,polygon){let inside=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[j],b=polygon[i],edge=sub(b,a),offset=sub(point,a);if(dot(edge,edge)<=EPS*EPS)continue;if(Math.abs(cross(edge,offset))<=EPS&&dot(offset,edge)>=-EPS&&dot(offset,edge)<=dot(edge,edge)+EPS)return true;if((a.y>point.y)!==(b.y>point.y)&&point.x<(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x)inside=!inside}return inside}
  function insideModule(point,module){return insidePolygon(point,module.polygon)&&!(module.cutouts||[]).some(loop=>insidePolygon(point,loop))}
  function modulesAt(scene,point){return(scene.modules||[]).filter(m=>insideModule(point,m)).map(m=>m.id)}
  function moduleEntry(origin,direction,module){
    const hits=[];
    for(const polygon of[module.polygon,...(module.cutouts||[])])for(let i=0;i<polygon.length;i++){
      const a=polygon[i],b=polygon[(i+1)%polygon.length],edge=sub(b,a),den=cross(direction,edge);if(Math.abs(den)<EPS)continue;
      const offset=sub(a,origin),distance=cross(offset,edge)/den,u=cross(offset,direction)/den;
      if(distance>EPS&&u>=-EPS&&u<=1+EPS)hits.push(distance);
    }
    hits.sort((a,b)=>a-b);
    for(let i=0;i<hits.length;i++){
      const distance=hits[i];if(i&&Math.abs(distance-hits[i-1])<EPS)continue;
      const delta=Math.min(1e-5,distance/2),before=add(origin,scale(direction,distance-delta)),after=add(origin,scale(direction,distance+delta));
      if(!insideModule(before,module)&&insideModule(after,module))return{distance,module,point:add(origin,scale(direction,distance))};
    }
    return null;
  }
  function normalizeModules(modules=[]){
    if(!Array.isArray(modules)||modules.length>1024)throw new Error('小板模块列表无效。');const ids=new Set();
    return modules.map(m=>{
      if(!m||typeof m.id!=='string'||!m.id||ids.has(m.id))throw new Error('小板模块 ID 需唯一。');ids.add(m.id);
      const polygon=m.polygon||(m.bounds?[{x:m.bounds.xMin,y:m.bounds.yMin},{x:m.bounds.xMax,y:m.bounds.yMin},{x:m.bounds.xMax,y:m.bounds.yMax},{x:m.bounds.xMin,y:m.bounds.yMax}]:null),cutouts=m.cutouts||[];
      if(!Array.isArray(cutouts)||cutouts.length>64)throw new Error('小板模块开窗列表无效。');
      let points=0;
      for(const loop of[polygon,...cutouts]){
        if(!Array.isArray(loop)||loop.length<3||loop.length>2048||loop.some(v=>!v||!finite(v.x)||!finite(v.y)))throw new Error('小板模块边界需为有效的世界坐标多边形。');
        points+=loop.length;const area=loop.reduce((sum,a,i)=>sum+cross(a,loop[(i+1)%loop.length]),0);
        if(Math.abs(area)<EPS)throw new Error('小板模块边界面积不能为零。');
      }
      if(points>8192)throw new Error('小板模块轮廓过于复杂。');
      return{id:m.id,name:m.name||m.id,polygon:copy(polygon),...(cutouts.length?{cutouts:copy(cutouts)}:{})};
    });
  }
  function assemblyMath(){const api=root.ZZLabOpticalAssemblyEngine||(typeof require==='function'?require('./optical-assembly-engine.js'):null);if(!api)throw new Error('三维光路模块尚未加载。');return api;}
  function sourcePortParameterIssue(config={}){
    const s=config.source||{},required=['wavelengthNm','powerMw','beamDiameterMm','beamQualityM2'];
    const complete=required.every(k=>finite(s[k]))&&POLS.includes(s.polarizationType)&&Object.hasOwn(s,'wavefrontRadiusMm')&&(s.wavefrontRadiusMm===null||finite(s.wavefrontRadiusMm))&&(!['linear','elliptical'].includes(s.polarizationType)||finite(s.polarizationAngleDeg))&&(s.polarizationType!=='elliptical'||finite(s.ellipticityDeg));
    return config.configured===true&&complete?null:{code:'source_port_data_missing',message:'请明确填写并确认本光口的光斑、M²、偏振和波前设置；不沿用主光口参数或通用默认值。',blocking:true};
  }
  function normalizeAssemblyElement(e){
    if(!e.opticalAssembly)return e;const A=assemblyMath(),geometry=A.normalizeAssembly(e.opticalAssembly),p=e.assemblyPlacement;
    if(!p||!['xMm','yMm','zMm','rotationDeg'].every(k=>finite(p[k])))throw new Error('复合器件需要明确的安装位置、高度和旋转角。');
    if(geometry.version===2&&(e.optics.elementType!=='coupler'||e.internalOptics?.[geometry.emissionNodeId]))throw new Error('v2总装由父级coupler控制唯一出光口；不能覆盖只读内部耦合口。');
    if(geometry.version>=3&&(e.optics.elementType!=='empty'||e.optics.source?.enabled))throw new Error('被动复合器件不能作为光源。');
    const internalOptics={},internalParameterEvidence={};for(const node of geometry.nodes){if(node.type==='coupler')continue;const saved=e.internalOptics?.[node.id]||node.defaults||{};if(geometry.version>=2&&saved.source?.enabled)throw new Error('v2内部元件不能自行发光；请设置父级耦合头光源。');internalParameterEvidence[node.id]=copy(e.internalParameterEvidence?.[node.id]??saved);internalOptics[node.id]=normalizeOptics({...saved,elementType:saved.elementType==='empty'?'empty':node.type==='objective'?'unsupported':node.type,...(node.type==='mirror'&&saved.mirror===undefined?{mirror:{mode:'data',samples:[]}}:{})},{});}
    return{...e,opticalAssembly:geometry,assemblyPlacement:copy(p),internalOptics,internalParameterEvidence};
  }
  function assemblyNodeOptics(element,node){return node?.type==='coupler'?element.optics:element.internalOptics[node?.id];}
  function assemblyHit(element,ray){
    const A=assemblyMath(),placement=element.assemblyPlacement;if(!finite(ray.beam.axisHeightMm))return null;
    const origin=A.worldToLocalPoint({x:ray.point.x,y:ray.point.y,z:ray.beam.axisHeightMm},placement),direction=A.worldToLocalDirection({...ray.direction,z:0},placement);let nearest=null;
    for(const node of element.opticalAssembly.nodes){const o=assemblyNodeOptics(element,node),selected=['objective','lens','waveplate','coupler'].includes(node.type)?0:(o.coatingFaceIndex??null),hit=A.rayHit(origin,direction,node,selected);if(hit&&(!nearest||hit.distanceMm<nearest.distance)){nearest={element,node,distance:hit.distanceMm,offset:hit.offsetMm,assemblyHit:hit,localDirection:direction,localBasisS:{x:0,y:0,z:1}};}}
    return nearest;
  }
  function sideProjection(element,local){const side=element.opticalAssembly.sideView||{},axis=side.projectionAxisMm,v=axis?{x:assemblyMath().dot3(local,axis),y:local.z}:assemblyMath().sidePoint(local);return{x:v.x-(side.xMin??side.boundsMm?.[0]??0),y:v.y-(side.zMin??side.boundsMm?.[1]??0)};}
  function queueAssemblyHit(session,element,ray,hit,node,direction,basisS,segmentId){
    const A=assemblyMath(),basis=A.incidenceBasis(direction,hit.normal,basisS),beam={...copy(ray.beam),stokes:A.rotateStokes(ray.beam.stokes,direction,basisS,basis.s)};
    const pending={...ray,id:`pending-${++session.counters.pending}`,kind:'assembly',instanceId:element.id,internalId:node.id,segmentId,point3D:copy(hit.point),direction3D:copy(direction),basisS3D:copy(basis.s),faceIndex:hit.faceIndex,normal3D:copy(hit.normal),incidenceAngleDeg:basis.angleDeg,offsetMm:hit.offsetMm,beam};
    if(node.type!=='objective'||!node.geometryConfirmed)session.pending.push(pending);else{complete(session,{...pending,lastInstanceId:element.id},'objective-mechanical-port',{assemblyId:element.id,internalId:node.id,point3D:A.localToWorldPoint(hit.point,element.assemblyPlacement)});warning(session,'objective_focus_unknown','光线到达已核实的物镜机械入口；尚无焦距、NA 与焦平面数据，未推测物镜聚焦或内部成像。',element.id);}const segment=session.segments.find(s=>s.id===segmentId);if(segment){segment.hitAssemblyId=element.id;segment.hitInternalId=node.id;segment.hitBeam3D=copy(beam);segment.incidenceAngleDeg=basis.angleDeg;segment.hitDirection3D=copy(direction);}
  }
  function assemblyPendingIssue(session,pending,element){
    const base={pendingId:pending.id,instanceId:element.id,internalId:pending.internalId,branchId:pending.branchId,sourceId:pending.sourceId,blocking:true},node=element.opticalAssembly.nodes.find(n=>n.id===pending.internalId),o=assemblyNodeOptics(element,node);
    if(!node||!o)return{...base,code:'assembly_node_missing',message:'复合器件内部元件已不存在。'};
    const unsupported=simulationIssue(element);if(unsupported)return{...base,...unsupported};
    if(element.opticalAssembly.version>=2&&element.opticalAssembly.verified!==true)return{...base,code:'assembly_geometry_unconfirmed',message:'总装注册几何尚未核实。'};
    if(!node.geometryConfirmed)return{...base,code:'assembly_geometry_unconfirmed',message:'此内部光学面的空间位置尚未核实。'};
    if(element.opticalAssembly.version>=2&&['lens','waveplate','coupler'].includes(node.type)&&Math.abs(pending.point3D.z-node.centerMm.z)>session.options.heightToleranceMm)return{...base,code:'height_mismatch',message:'入射光高与内部注册平面光轴不一致。'};
    if(node.type==='objective')return null;
    if(node.type==='coupler'){
      if(!o.inserted||!o.configured)return{...base,code:'assembly_coupler_unconfigured',message:'父级耦合头尚未确认装入，不能声明理想耦合接收。'};
      const projection=assemblyMath().dot3(pending.direction3D,node.normal);
      return projection>-Math.cos((node.halfAngleDeg??5)*RAD)+EPS?{...base,code:'coupler_direction_mismatch',message:'入射方向未朝向已登记的耦合口。'}:null;
    }
    if(!o.configured)return{...base,code:'optics_unconfigured',message:'请确认此内部元件已装入的光学件与镀膜参数。'};
    if(!o.inserted||o.elementType==='empty')return null;
    if(node.type==='lens'){
      const evidence=element.internalParameterEvidence?.[node.id]||{},projection=Math.abs(assemblyMath().dot3(pending.direction3D,node.normal));
      if(!finite(evidence.focalLengthMm)||Math.abs(evidence.focalLengthMm)<1e-6)return{...base,code:'lens_focal_length_missing',message:'内部透镜必须明确填写非零焦距。'};
      if(Math.abs(pending.direction3D.z)>1e-8||projection<Math.cos((node.halfAngleDeg??5)*RAD)-EPS)return{...base,code:'assembly_lens_direction',message:'内部薄透镜只支持已声明的水平近轴入射。'};
      return null;
    }
    if(node.type==='waveplate'){
      const projection=Math.abs(assemblyMath().dot3(pending.direction3D,node.normal));
      if(Math.abs(pending.direction3D.z)>1e-8||projection<Math.cos((node.halfAngleDeg??5)*RAD)-EPS)return{...base,code:'assembly_waveplate_direction',message:'波片入射超出已声明的水平近轴方向；未推测斜入射延迟。'};
      const evidence=element.internalParameterEvidence?.[node.id]||{},plates=Array.isArray(evidence.waveplates)?evidence.waveplates:[evidence];
      if(plates.length!==1||!['fastAxisDeg','retardanceDeg','designWavelengthNm'].every(k=>finite(plates[0][k])))return{...base,code:'interaction_waveplate_data_missing',message:'独立波片平面需要已确认的单片快轴、延迟与设计波长；不使用通用默认值。'};
      return null;
    }
    if(node.requiresClearApertureConfirmation===true){const aperture=element.internalParameterEvidence?.[node.id]?.clearApertureMm;if(!finite(aperture)||aperture<=0||aperture>node.radiusMm*2)return{...base,code:'assembly_aperture_unknown',message:'请填写此镜片已确认的有效反射净口；不能用镜片外径或镜架后开孔代替。'};}
    if(o.coatingFaceIndex===null||o.coatingFaceIndex===undefined)return{...base,code:'assembly_coating_face_missing',message:'CAD 只确认了镜片两侧机械平面；请在属性中选择实际镀膜面，不能用厚度中面代替。'};
    if(o.coatingFaceIndex!==pending.faceIndex)return{...base,code:'assembly_face_changed',message:'镀膜面改变后需重新追迹至实际表面。'};
    const response=node.type==='mirror'?mirrorResponseAt(o.mirror,pending.beam,pending.incidenceAngleDeg,node.mirrorCoating):dichroicResponseAt(o.dichroic,pending.beam,pending.incidenceAngleDeg,node.dichroicCoating);
    return response.ok?null:{...base,code:response.code,message:response.message};
  }
  function refreshAssemblyViews(session){
    const A=session.scene.elements.some(e=>e.opticalAssembly)?assemblyMath():null;if(!A)return session;const views={};
    for(const element of session.scene.elements.filter(e=>e.opticalAssembly)){
      const view={segments:[],pending:[],incoming:{},elements:[],issues:[],status:'idle'};views[element.id]=view;
      for(const node of element.opticalAssembly.nodes){view.elements.push({id:element.id+'::'+node.id,internalId:node.id,name:node.name||node.id,optics:copy(assemblyNodeOptics(element,node)),mirrorCoating:node.mirrorCoating,dichroicCoating:node.dichroicCoating});view.incoming[node.id]=[];}
      for(const s of session.segments){if(s.assemblyId!==element.id&&s.hitAssemblyId!==element.id)continue;const from=s.from3D?A.worldToLocalPoint(s.from3D,element.assemblyPlacement):A.worldToLocalPoint({...s.from,z:s.beam.axisHeightMm},element.assemblyPlacement),to=s.to3D?A.worldToLocalPoint(s.to3D,element.assemblyPlacement):A.worldToLocalPoint({...s.to,z:s.beam.axisHeightMm},element.assemblyPlacement);view.segments.push({...copy(s),from:sideProjection(element,from),to:sideProjection(element,to),fromLocal3D:from,toLocal3D:to});
        if(s.hitAssemblyId===element.id&&view.incoming[s.hitInternalId])view.incoming[s.hitInternalId].push({id:s.id,ordinal:view.incoming[s.hitInternalId].length+1,internalId:s.hitInternalId,sourceId:s.sourceId,branchId:s.branchId,pathMm:s.pathEndMm,beam:copy(s.hitBeam3D),direction:copy(s.hitDirection3D),incidenceAngleDeg:s.incidenceAngleDeg});
      }
      for(const p of session.pending.filter(p=>p.kind==='assembly'&&p.instanceId===element.id)){view.pending.push({...copy(p),point:sideProjection(element,p.point3D)});const issue=assemblyPendingIssue(session,p,element);if(issue)view.issues.push(issue);}
      for(const w of session.warnings.filter(w=>w.instanceId===element.id))if(!view.issues.some(i=>i.code===w.code))view.issues.push(copy(w));
      view.status=view.pending.length?(view.issues.some(i=>i.blocking)?'blocked':'pending'):view.segments.length?'complete':'idle';
    }session.assemblyViews=views;return session;
  }
  function finishAssemblySegment(session,element,ray,distance,hit){
    const A=assemblyMath(),toLocal=A.add3(ray.point3D,A.scale3(ray.direction3D,distance)),from3D=A.localToWorldPoint(ray.point3D,element.assemblyPlacement),to3D=A.localToWorldPoint(toLocal,element.assemblyPlacement),direction3D=A.localToWorldDirection(ray.direction3D,element.assemblyPlacement),segment={id:`segment-${++session.counters.segments}`,internalAssemblySegment:true,assemblyId:element.id,branchId:ray.branchId,sourceId:ray.sourceId,lineageKey:ray.lineageKey,from:{x:from3D.x,y:from3D.y},to:{x:to3D.x,y:to3D.y},from3D,to3D,direction:{x:direction3D.x,y:direction3D.y},direction3D,lengthMm:distance,pathStartMm:ray.pathMm,pathEndMm:ray.pathMm+distance,beam:copy(ray.beam),hitInstanceId:hit?element.id:null,activeModuleIds:copy(ray.activeModuleIds||[])};
    const z=-ray.beam.q.re;if(z>=EPS&&z<=distance+EPS){const focus3D=A.add3(from3D,A.scale3(direction3D,z));segment.focus={...focus3D,diameterMm:gaussianAt(ray.beam,z).diameterMm,distanceFromSourceMm:ray.pathMm+z};}
    session.segments.push(segment);return{...ray,point:{x:to3D.x,y:to3D.y},point3D:toLocal,pathMm:segment.pathEndMm,beam:{...ray.beam,axisHeightMm:to3D.z,q:propagateQ(ray.beam.q,distance),qSagittal:propagateQ(ray.beam.qSagittal||ray.beam.q,distance)},steps:ray.steps+1,segmentId:segment.id};
  }
  function extendAssembly(session,element,ray){
    const A=assemblyMath(),limits=session.options;if(ray.beam.powerMw<=limits.minPowerMw){complete(session,ray,'zero-power',{assemblyId:element.id,point3D:A.localToWorldPoint(ray.point3D,element.assemblyPlacement)});return;}
    if(ray.steps>=limits.maxSteps||session.segments.length>=limits.maxSegments||ray.pathMm>=limits.maxPathMm){warning(session,'trace_limit','三维光路已达到追迹上限，请检查反射环路。',element.id);complete(session,ray,'limit');return;}
    let nearest=null;for(const node of element.opticalAssembly.nodes){if(node.id===ray.lastInternalId)continue;const o=assemblyNodeOptics(element,node),hit=A.rayHit(ray.point3D,ray.direction3D,node,['objective','lens','waveplate','coupler'].includes(node.type)?0:(o.coatingFaceIndex??null));if(hit&&(!nearest||hit.distanceMm<nearest.hit.distanceMm))nearest={node,hit};}
    const exit=A.boxExit(ray.point3D,ray.direction3D,element.opticalAssembly.bounds),maxDistance=limits.maxPathMm-ray.pathMm,hitBeforeExit=nearest&&(!exit||nearest.hit.distanceMm<=exit.distanceMm+EPS),distance=Math.min(hitBeforeExit?nearest.hit.distanceMm:exit?.distanceMm??0,maxDistance);
    const next=distance>EPS?finishAssemblySegment(session,element,ray,distance,hitBeforeExit?nearest:null):ray;
    if(distance>=maxDistance-EPS){warning(session,'trace_limit','三维光路已达到总长度上限。',element.id);complete(session,next,'limit');return;}
    if(hitBeforeExit){queueAssemblyHit(session,element,next,nearest.hit,nearest.node,ray.direction3D,ray.basisS3D,next.segmentId);return;}
    const direction=A.localToWorldDirection(ray.direction3D,element.assemblyPlacement),basis=A.localToWorldDirection(ray.basisS3D,element.assemblyPlacement);
    if(Math.abs(direction.z)>1e-8){warning(session,'assembly_out_of_plane','光线从总装离开后仍沿三维倾斜方向传播；当前大板元件是水平光路，已停止，未伪造二维投影继续传播。',element.id);complete(session,next,'out-of-plane',{point3D:A.localToWorldPoint(next.point3D,element.assemblyPlacement),direction3D:direction});return;}
    const outgoing={...next,direction:norm(direction),beam:{...next.beam,stokes:A.rotateStokes(next.beam.stokes,direction,basis,{x:0,y:0,z:1})},lastInstanceId:element.id};for(const key of ['point3D','direction3D','basisS3D','lastInternalId','internalId','faceIndex','normal3D','incidenceAngleDeg','segmentId','id','kind','instanceId','offsetMm'])delete outgoing[key];
    extend(session,outgoing);
  }
  function advanceAssemblyRay(session,element,ray){
    const issue=assemblyPendingIssue(session,ray,element);if(issue){session.pending.push(ray);warning(session,issue.code,issue.message,element.id);return;}
    const A=assemblyMath(),node=element.opticalAssembly.nodes.find(n=>n.id===ray.internalId),o=assemblyNodeOptics(element,node),next={...ray,lastInstanceId:element.id,lastInternalId:node.id};for(const key of ['id','kind','instanceId','internalId','faceIndex','normal3D','incidenceAngleDeg','offsetMm','blockedIssue'])delete next[key];
    if(node.type==='objective'){complete(session,next,'objective-mechanical-port',{assemblyId:element.id,internalId:node.id,point3D:A.localToWorldPoint(ray.point3D,element.assemblyPlacement)});warning(session,'objective_focus_unknown','光线到达已核实的物镜机械入口；尚无焦距、NA 与焦平面数据，未推测物镜聚焦或内部成像。',element.id);return;}
    if(node.type==='coupler'){
      const direction=A.localToWorldDirection(ray.direction3D,element.assemblyPlacement),basis=A.localToWorldDirection(ray.basisS3D,element.assemblyPlacement),beam={...copy(ray.beam),stokes:A.rotateStokes(ray.beam.stokes,direction,basis,{x:0,y:0,z:1})};
      complete(session,{...next,beam,direction},'coupled',{assemblyId:element.id,internalId:node.id,point3D:A.localToWorldPoint(ray.point3D,element.assemblyPlacement)});warning(session,'ideal_coupling','按理想耦合接收终止，未计算实际模式匹配或耦合效率。',element.id);return;
    }
    if(!o.inserted||o.elementType==='empty'){extendAssembly(session,element,next);return;}
    if(ray.offsetMm+gaussianAt(ray.beam).diameterMm/2>Math.min(o.clearApertureMm/2,node.radiusMm,node.mechanicalClearRadiusMm??Infinity,node.faces[ray.faceIndex]?.radiusMm??Infinity))warning(session,'aperture_clipping','内部光学件有效口径可能截光；尚未计算截光衍射。',element.id);
    if(node.type==='lens'){
      const forward=node.normal,normal=A.dot3(ray.direction3D,forward)<0?A.scale3(forward,-1):forward,tangent={x:-forward.y,y:forward.x,z:0};
      const slope=A.dot3(ray.direction3D,tangent)/A.dot3(ray.direction3D,normal),offset=A.dot3(A.sub3(ray.point3D,node.centerMm),tangent);
      const direction=A.normalize3(A.add3(normal,A.scale3(tangent,slope-offset/o.focalLengthMm)));
      const stokes=A.rotateStokes(ray.beam.stokes,ray.direction3D,ray.basisS3D,{x:0,y:0,z:1});
      warning(session,'lens_thin_paraxial','内部透镜采用明确焦距的薄透镜近轴模型；机械基准不代表实测主平面。',element.id);
      extendAssembly(session,element,{...next,direction3D:direction,basisS3D:{x:0,y:0,z:1},beam:{...copy(ray.beam),q:lensQ(ray.beam.q,o.focalLengthMm),stokes}});return;
    }
    if(node.type==='waveplate'){
      const plate=o.waveplates?.[0]??o,reverse=A.dot3(ray.direction3D,node.normal)<0;
      if(ray.incidenceAngleDeg>1e-6)warning(session,'waveplate_paraxial_assumption','入射位于声明的近轴接受范围；仍采用给定延迟，未计算斜入射修正。',element.id);
      if(Math.abs(plate.designWavelengthNm-ray.beam.wavelengthNm)>.01)warning(session,'waveplate_wavelength_mismatch','波片设计波长不匹配；按给定延迟计算，未推测色散。',element.id);
      const stokes=A.rotateStokes(ray.beam.stokes,ray.direction3D,ray.basisS3D,{x:0,y:0,z:1});
      extendAssembly(session,element,{...next,basisS3D:{x:0,y:0,z:1},beam:{...copy(ray.beam),stokes:applyWaveplateSequence(stokes,[plate],reverse)}});return;
    }
    const response=node.type==='mirror'?mirrorResponseAt(o.mirror,ray.beam,ray.incidenceAngleDeg,node.mirrorCoating):dichroicResponseAt(o.dichroic,ray.beam,ray.incidenceAngleDeg,node.dichroicCoating);
    if(response.approximate)warning(session,'mirror_ideal_approximation','总装内部镜片使用明确选择的理想镜面近似，并非实测镀膜。',element.id);
    if(response.phaseIndependent)warning(session,node.type+'_phase_not_required','此入射光的输出不依赖未知相位；仅使用已知幅度系数计算，相位仍未标定。',element.id);
    if(node.type==='mirror'){extendAssembly(session,element,{...next,beam:applyMirror(ray.beam,response.response),direction3D:A.reflect3(ray.direction3D,ray.normal3D)});return;}
    const split=applyDichroic(ray.beam,response.response),identity=element.id+'::'+node.id;
    for(const output of[{label:'transmitted',beam:split.transmitted,direction3D:ray.direction3D},{label:'reflected',beam:split.reflected,direction3D:A.reflect3(ray.direction3D,ray.normal3D)}]){
      const branchPath=[...(ray.branchPath||[]),{instanceId:identity,encounter:(ray.branchPath||[]).filter(p=>p.instanceId===identity).length+1,output:output.label}],outgoing={...next,...output,parentBranchId:ray.branchId,branchPath,lineageKey:JSON.stringify([ray.sourceId,...branchPath])};
      if(output.beam.powerMw<=session.options.minPowerMw){complete(session,outgoing,'zero-power',{output:output.label});continue;}
      if(session.counters.branches>=session.options.maxBranches){warning(session,'branch_limit','双色镜分支数量已达到上限。',element.id);complete(session,outgoing,'branch-limit');continue;}
      extendAssembly(session,element,{...outgoing,branchId:`branch-${++session.counters.branches}`});
    }
  }
  function interactionLanguage(){const api=root.ZZLabOpticalInteractionLanguage||(typeof require==='function'?require('./optical-interaction-language.js'):null);if(!api)throw new Error('光学交互语言解释器尚未加载。');return api;}
  function interactionPhysics(){return{normalizeMirror,elementAngle,gaussianAt,mirrorResponseFor,applyMirror,reflect,splitPBS,applyWaveplateSequence,waveplateReverse,lensQ};}
  function normalizeInteractionElement(element,rawOptics={}){if(element.opticalInteraction===undefined)return element;if(element.opticalAssembly)throw new Error('交互语言v1仅支持共面光学步骤；三维整装继续使用已验证的内部面引擎。');const opticalInteraction=interactionLanguage().normalize(element.opticalInteraction,interactionPhysics());if(opticalInteraction.model==='source'&&element.optics.elementType!=='source')throw new Error('source交互声明只适用于已登记的source元件。');if(opticalInteraction.model==='planar'&&element.optics.elementType==='source')throw new Error('source元件请使用source声明；双向出入光使用coupler。');return{...element,opticalInteraction,interactionParameterEvidence:element.interactionParameterEvidence??copy(rawOptics)};}
  function interactionResult(element,ray,options){return interactionLanguage().evaluate(element.opticalInteraction,element,ray,options,interactionPhysics());}
  function advanceInteraction(result,element,ray){
    const computed=interactionResult(element,ray,result.options);
    if(computed.issue){result.pending.push(ray);warning(result,computed.issue.code,computed.issue.message,element.id);return;}
    for(const w of computed.warnings)warning(result,w.code,w.message,element.id);
    const branching=computed.outputs.length>1;
    for(const output of computed.outputs){
      const next={...ray,lastInstanceId:element.id,beam:output.beam,direction:output.direction};
      for(const key of['id','kind','moduleId','instanceId','offsetMm','segmentId','coincidentElementId','coincidentOffsetMm','coincidentBlockedIssue','blockedIssue'])delete next[key];
      if(branching){const branchPath=[...(ray.branchPath||[]),{instanceId:element.id,encounter:(ray.branchPath||[]).filter(p=>p.instanceId===element.id).length+1,output:computed.inputId+':'+output.label}];Object.assign(next,{parentBranchId:ray.branchId,branchPath,lineageKey:JSON.stringify([ray.sourceId,...branchPath])});if(result.counters.branches>=result.options.maxBranches){warning(result,'branch_limit','交互语言输出已达到光路分支上限。',element.id);complete(result,next,'branch-limit');continue;}next.branchId=`branch-${++result.counters.branches}`;}
      if(output.terminal)complete(result,next,output.terminal,{instanceId:element.id,...(output.reason?{message:output.reason}:{})});else extend(result,next);
    }
  }
  function normalizeScene(scene={}){const b=scene.bounds||{xMin:0,yMin:0,xMax:1000,yMax:1000};if(!['xMin','yMin','xMax','yMax'].every(k=>finite(b[k]))||b.xMax<=b.xMin||b.yMax<=b.yMin)throw new Error('光路画布边界无效。');const ids=new Set();return{bounds:copy(b),glassChamber:scene.glassChamber?copy(scene.glassChamber):null,modules:normalizeModules(scene.modules),elements:(scene.elements||[]).map(e=>{if(typeof e.id!=='string'||!e.id||ids.has(e.id))throw new Error('光学元件 ID 需唯一。');ids.add(e.id);const center=e.center||{x:e.xMm,y:e.yMm};if(!finite(center.x)||!finite(center.y))throw new Error('光学元件中心坐标无效。');return normalizeInteractionElement(normalizeAssemblyElement({...copy(e),center:copy(center),rotationDeg:number(e.rotationDeg,0,'元件旋转角',-3600,3600),optics:normalizeOptics(e.optics||{})}),e.optics||{})})}}
  function warning(session,code,message,instanceId){if(!session.warnings.some(w=>w.code===code&&w.instanceId===instanceId))session.warnings.push({code,message,...(instanceId?{instanceId}:{})})}
  function simulationIssue(element){if(element.opticalAssembly)return element.opticalAssembly.version>=2?element.simulationIssue||null:null;return element.simulationIssue||(!element.opticalInteraction&&element.optics.elementType==='unsupported'?{code:'optics_unsupported',message:'此器件尚未接入光学计算，光束暂停于此；可继续用于布局和采购。'}:null)}
  function complete(session,ray,reason,extra={}){session.completed.push({branchId:ray.branchId,sourceId:ray.sourceId,lineageKey:ray.lineageKey||JSON.stringify([ray.sourceId]),branchPath:copy(ray.branchPath||[]),instanceId:ray.lastInstanceId||null,point:copy(ray.point),pathMm:ray.pathMm,powerMw:ray.beam.powerMw,finalBeam:copy(ray.beam),direction:copy(ray.direction),...(ray.direction3D?{direction3D:assemblyMath().localToWorldDirection(ray.direction3D,session.scene.elements.find(e=>e.id===ray.lastInstanceId)?.assemblyPlacement||{})}:{}),activeModuleIds:ray.activeModuleIds||[],reason,...extra})}
  function finishSegment(session,ray,distance,hit){const to=add(ray.point,scale(ray.direction,distance)),segment={id:`segment-${++session.counters.segments}`,branchId:ray.branchId,sourceId:ray.sourceId,lineageKey:ray.lineageKey||JSON.stringify([ray.sourceId]),from:copy(ray.point),to,direction:copy(ray.direction),lengthMm:distance,pathStartMm:ray.pathMm,pathEndMm:ray.pathMm+distance,beam:copy(ray.beam),hitInstanceId:hit?.element?.id||null,hitModuleId:hit?.module?.id||null,activeModuleIds:copy(ray.activeModuleIds||[]),...(ray.lensInsideId?{lensMediumId:ray.lensInsideId}: {})};const z=-ray.beam.q.re;if(z>=EPS&&z<=distance+EPS){const waist=gaussianAt(ray.beam,z);segment.focus={...add(ray.point,scale(ray.direction,z)),diameterMm:waist.diameterMm,distanceFromSourceMm:ray.pathMm+z}}session.segments.push(segment);return{...ray,point:to,pathMm:segment.pathEndMm,beam:{...ray.beam,q:propagateQ(ray.beam.q,distance),qSagittal:propagateQ(ray.beam.qSagittal||ray.beam.q,distance)},steps:ray.steps+1,activeModuleIds:modulesAt(session.scene,add(to,scale(ray.direction,1e-5)))}}

  function scaleComplex(q,k){return{re:q.re*k,im:q.im*k};}
  function glassIntersection(session,ray){
    const g=session.scene.glassChamber;if(!g?.enabled)return null;
    const O=root.GlassOptics||(typeof require==='function'?require('./glass-chamber.js'):null);if(!O)throw Error('Glass audit optics not loaded');
    const c=O.chamber(g.center,g.settings),p=c.local(ray.point),zero=c.local({x:0,y:0}),dd=c.local(ray.direction),d={x:dd.x-zero.x,y:dd.y-zero.y},ng=O.silicaIndex(ray.beam.wavelengthNm),medium=ray.glassMedium||'outside',indices={outside:c.outsideIndex,glass:ng,vacuum:c.insideIndex};
    let hit,next,n;
    if(medium==='outside'){hit=O.boxHits(p,d,c.outer)[0];next='glass';n=hit?scale(hit.normal,-1):null;}
    else if(medium==='vacuum'){hit=O.boxHits(p,d,c.inner)[0];next='glass';n=hit?.normal;}
    else{hit=[...O.boxHits(p,d,c.outer).map(h=>({...h,boundary:'outer'})),...O.boxHits(p,d,c.inner).map(h=>({...h,boundary:'inner'}))].sort((a,b)=>a.t-b.t)[0];next=hit?.boundary==='inner'?'vacuum':'outside';n=hit?.boundary==='inner'?scale(hit.normal,-1):hit?.normal;}
    if(!hit)return null;let error=null;
    if(hit.corner)error='光线命中玻璃棱边，停止计算。';
    else if(hit.axis==='y'){if(c.endMode==='unknown')error='端窗朝向未确认，308路停止于外界面。';else if(c.endMode!=='both'&&hit.sign!==(c.endMode==='plus'?1:-1))error='转接板/石英管端未建为光学平窗，停止计算。';else if(Math.abs(hit.p.x)>23.5+EPS)error='端窗交点超出47 mm镀膜宽度。';}
    else if(Math.abs(hit.p.y)>58.5+EPS)error='侧窗交点超出117 mm镀膜长度。';
    const out=error?null:O.refract(d,n,indices[medium],indices[next]);if(!error&&!out)error='玻璃界面发生全反射，透射路径停止。';
    const origin=c.world({x:0,y:0}),worldVector=v=>sub(c.world(v),origin);
    return{distance:hit.t,axis:hit.axis,sign:hit.sign,error,next,n1:indices[medium],n2:indices[next],out:out?worldVector(out):null,normal:n?worldVector(n):null};
  }
  function extend(session,ray){
    const limits=session.options;if(ray.beam.powerMw<=limits.minPowerMw){complete(session,ray,'zero-power');return}if(ray.steps>=limits.maxSteps||session.segments.length>=limits.maxSegments||ray.pathMm>=limits.maxPathMm){warning(session,'trace_limit','光路已达到追迹上限，请检查是否形成反射环路。');complete(session,ray,'limit');return}
    const boundary=exitDistance(ray.point,ray.direction,session.scene.bounds);if(boundary<=EPS){complete(session,ray,'escaped');return}let nearest=null;const heightCandidates=[];
    for(const e of session.scene.elements){if((e.id===ray.lastInstanceId&&ray.lensInsideId!==e.id)||e.optics.elementType==='source')continue;const physical=e.optics.elementType==='lens'&&e.optics.inserted&&e.optics.lensPrescription;const h=physical?physicalLensHit(ray.point,ray.direction,e,ray.lensInsideId===e.id):e.opticalAssembly?assemblyHit(e,ray):planeHit(ray.point,ray.direction,e);if(physical&&ray.lensInsideId===e.id&&!h){warning(session,'lens_edge_exit','光线超出已核实透镜光学面，停止；未把侧边当作有效透射面。',e.id);complete(session,ray,'lens-edge-exit');return;}if(!h||h.distance>boundary+EPS)continue;const unsupported=simulationIssue(e);if(unsupported)h.blockedIssue=copy(unsupported);else if(!e.opticalAssembly&&e.axisHeightMm===null){h.blockedIssue={code:'axis_height_unknown',message:`${e.name||e.id} 的光轴高度未知，请核对出光口资料。`};heightCandidates.push(h);if(!limits.pauseOnHeightErrors&&!e.opticalInteraction)continue}if(!e.opticalAssembly&&!unsupported&&finite(ray.beam.axisHeightMm)&&finite(e.axisHeightMm)&&Math.abs(ray.beam.axisHeightMm-e.axisHeightMm)>(e.opticalInteraction?.heightToleranceMm??limits.heightToleranceMm)){h.blockedIssue={code:'height_mismatch',message:`${e.name||e.id} 的光轴高度与入射光不一致，请使用合适爬架矫正光高并对准光口。`};heightCandidates.push(h);if(!limits.pauseOnHeightErrors&&!e.opticalInteraction)continue}if(!nearest||h.distance<nearest.distance-EPS)nearest=h;}
    let gate=null;for(const module of session.scene.modules||[]){const hit=moduleEntry(ray.point,ray.direction,module);if(hit&&hit.distance<=boundary+EPS&&(!gate||hit.distance<gate.distance-EPS))gate=hit}

    const glass=glassIntersection(session,ray);
    if(glass && glass.distance < Math.min(nearest?.distance??boundary,gate?.distance??boundary)-EPS){
      const next=finishSegment(session,ray,glass.distance,null);session.segments.at(-1).glassMedium=ray.glassMedium||'outside';
      if(glass.error){warning(session,'glass_window_unconfirmed',glass.error);complete(session,next,'glass-boundary-unconfirmed',{message:glass.error});return;}
      const incoming=ray.direction,out=glass.out,ci=dot(incoming,glass.normal),cr=dot(out,glass.normal),ratio=glass.n2/glass.n1;
      next.beam.q=scaleComplex(next.beam.q,ratio*(cr/ci)**2);
      next.beam.qSagittal=scaleComplex(next.beam.qSagittal||next.beam.q,ratio);
      next.beam.mediumIndex=glass.n2;next.direction=out;next.glassMedium=glass.next;
      session.glassEvents=session.glassEvents||[];session.glassEvents.push({sourceId:ray.sourceId,branchId:ray.branchId,point:next.point,axis:glass.axis,sign:glass.sign,fromMedium:ray.glassMedium||'outside',toMedium:glass.next,n1:glass.n1,n2:glass.n2,incidenceDeg:Math.acos(clamp(ci,-1,1))/RAD,refractionDeg:Math.acos(clamp(cr,-1,1))/RAD});
      extend(session,next);return;
    }
    const first=gate&&(!nearest||gate.distance<=nearest.distance+EPS)?gate:nearest;for(const h of heightCandidates)if(h.distance<=(first?.distance??boundary)+EPS)warning(session,h.blockedIssue.code,h.blockedIssue.message,h.element.id);const maxDistance=limits.maxPathMm-ray.pathMm,distance=Math.min(first?.distance??boundary,maxDistance),next=finishSegment(session,ray,distance,first&&first.distance<=maxDistance?first:null);
    if(distance>=maxDistance-EPS){warning(session,'trace_limit','光路已达到总长度上限，请检查反射环路。');complete(session,next,'limit');return}if(!first){complete(session,next,'escaped');return}
    const id=`pending-${++session.counters.pending}`,segmentId=session.segments.at(-1).id;if(first.module){const coincident=nearest&&Math.abs(nearest.distance-first.distance)<=EPS?{coincidentElementId:nearest.element.id,coincidentOffsetMm:nearest.offset,coincidentBlockedIssue:nearest.blockedIssue||null,...(nearest.lensSurface?{coincidentLensSurface:nearest.lensSurface}:{}),...(nearest.assemblyHit?{coincidentAssemblyHit:copy(nearest.assemblyHit),coincidentInternalId:nearest.node.id,coincidentLocalDirection:copy(nearest.localDirection)}:{})}:{};session.pending.push({...next,id,kind:'module',moduleId:first.module.id,instanceId:null,segmentId,activeModuleIds:modulesAt(session.scene,add(next.point,scale(next.direction,-1e-5))),...coincident});return}
    if(nearest.assemblyHit){queueAssemblyHit(session,nearest.element,next,nearest.assemblyHit,nearest.node,nearest.localDirection,nearest.localBasisS,segmentId);return;}
    session.pending.push({...next,id,kind:'element',instanceId:nearest.element.id,offsetMm:nearest.offset,segmentId,...(nearest.lensSurface?{lensSurface:nearest.lensSurface}:{}),...(nearest.blockedIssue?{blockedIssue:nearest.blockedIssue}:{})});
  }
  function advanceModule(session,moduleId,pendingId){const result=copy(session),matches=p=>p.kind==='module'&&p.moduleId===moduleId&&(!pendingId||p.id===pendingId),selected=result.pending.filter(matches);result.pending=result.pending.filter(p=>!matches(p));for(const ray of selected){const next={...ray,activeModuleIds:[...new Set([...(ray.activeModuleIds||[]),moduleId])]},elementId=ray.coincidentElementId,offset=ray.coincidentOffsetMm;for(const key of['id','kind','moduleId','instanceId','segmentId','coincidentElementId','coincidentOffsetMm','coincidentBlockedIssue','coincidentAssemblyHit','coincidentInternalId','coincidentLocalDirection','blockedIssue'])delete next[key];if(elementId&&ray.coincidentAssemblyHit){const element=result.scene.elements.find(e=>e.id===elementId);queueAssemblyHit(result,element,next,ray.coincidentAssemblyHit,element.opticalAssembly.nodes.find(n=>n.id===ray.coincidentInternalId),ray.coincidentLocalDirection,{x:0,y:0,z:1},ray.segmentId);continue}if(elementId){result.pending.push({...next,id:`pending-${++result.counters.pending}`,kind:'element',instanceId:elementId,offsetMm:offset,segmentId:ray.segmentId,...(ray.coincidentLensSurface?{lensSurface:ray.coincidentLensSurface}:{}),...(ray.coincidentBlockedIssue?{blockedIssue:ray.coincidentBlockedIssue}:{})});continue}extend(result,next)}return refreshAssemblyViews(result)}
  function createSession(scene,sources,options={}){
    const result={version:1,scene:normalizeScene(scene),options:{maxSteps:256,maxSegments:2048,maxBranches:128,maxPathMm:1e6,minPowerMw:1e-12,heightToleranceMm:.1,pauseOnHeightErrors:false,...options},segments:[],pending:[],completed:[],warnings:[],counters:{branches:0,segments:0,pending:0},sourceIds:[]};
    for(const key of['maxSteps','maxSegments','maxBranches'])result.options[key]=Math.floor(number(result.options[key],128,key,1,key==='maxSegments'?20000:4096));result.options.maxPathMm=number(result.options.maxPathMm,1e6,'最大光程',1,1e8);result.options.minPowerMw=number(result.options.minPowerMw,1e-12,'最小功率',0,1e9);result.options.heightToleranceMm=number(result.options.heightToleranceMm,.1,'光轴高度容差',0,100);
    result.options.pauseOnHeightErrors=boolean(result.options.pauseOnHeightErrors,false,'错误高度暂停');
    const emitters=sources===undefined?result.scene.elements.filter(e=>['coupler','source'].includes(e.optics.elementType)&&(e.optics.source.enabled||e.opticalAssembly?.version===2&&e.blockedSourceRequested===true&&e.simulationIssue)).map(e=>({instanceId:e.id})):sources;if(!Array.isArray(emitters))throw new Error('光源列表无效。');result.sourceInputs=copy(emitters);
    for(const requested of emitters){const e=result.scene.elements.find(v=>v.id===requested.instanceId);if(!e||!['coupler','source'].includes(e.optics.elementType)){warning(result,'invalid_source','所选元件不是可出光的激光器或耦合头。',requested.instanceId);continue}const unavailable=simulationIssue(e);if(unavailable){warning(result,unavailable.code,unavailable.message,e.id);continue}if(e.axisHeightMm===null||e.axisHeightMm===undefined&&result.scene.elements.some(e=>e.opticalAssembly)){warning(result,'axis_height_unknown',`${e.name||e.id} 的出光高度未知，请核对出光口资料再出光。`,e.id);continue}if(result.counters.branches>=result.options.maxBranches){warning(result,'branch_limit','光源与分支数量已达到上限。');break}const s=normalizeSource(requested,e.optics.source),direction=vec(finite(e.sourceDirectionDeg)?e.sourceDirectionDeg:e.rotationDeg+s.directionAngleDeg),point=e.sourcePoint||e.center;if(e.opticalInteraction){const issue=interactionLanguage().emissionIssue(e.opticalInteraction,e,s,direction);if(issue){warning(result,issue.code,issue.message,e.id);if(issue.blocking)continue;}}if(e.opticalAssembly?.version===2){
      const A=assemblyMath(),port=e.opticalAssembly.nodes.find(n=>n.id===e.opticalAssembly.emissionNodeId),localDirection=A.worldToLocalDirection({...direction,z:0},e.assemblyPlacement),worldPoint=A.localToWorldPoint(port.centerMm,e.assemblyPlacement);
      if(e.opticalAssembly.verified!==true||!port.geometryConfirmed){warning(result,'assembly_geometry_unconfirmed','耦合口空间位置尚未核实，不能出光。',e.id);continue;}
      if(!finite(e.axisHeightMm)||Math.abs(e.axisHeightMm-worldPoint.z)>result.options.heightToleranceMm){warning(result,'axis_height_unknown','耦合口实际出光高度未知或不符合注册平面。',e.id);continue;}
      if(e.optics.elementType!=='coupler'||!e.optics.inserted||!e.optics.configured){warning(result,'assembly_source_unconfigured','请确认耦合头已安装并核对出光配置。',e.id);continue;}
      if(A.dot3(localDirection,port.normal)<Math.cos((port.halfAngleDeg??5)*RAD)-EPS){warning(result,'interaction_emission_direction','出光方向不符合总装耦合口名义正向。',e.id);continue;}
      result.sourceIds.push(e.id);extendAssembly(result,e,{branchId:`branch-${++result.counters.branches}`,sourceId:e.id,lineageKey:JSON.stringify([e.id]),branchPath:[],point:{x:worldPoint.x,y:worldPoint.y},point3D:copy(port.centerMm),direction,direction3D:localDirection,basisS3D:{x:0,y:0,z:1},beam:createBeam(s,worldPoint.z),pathMm:0,steps:0,lastInstanceId:e.id,lastInternalId:port.id,activeModuleIds:modulesAt(result.scene,worldPoint)});continue;
    }result.sourceIds.push(e.id);extend(result,{branchId:`branch-${++result.counters.branches}`,sourceId:e.id,lineageKey:JSON.stringify([e.id]),branchPath:[],point:copy(point),direction,beam:createBeam(s,e.axisHeightMm??null),pathMm:0,steps:0,lastInstanceId:e.id,activeModuleIds:modulesAt(result.scene,point)});}result.traceKey=sessionTraceKey(result);return refreshAssemblyViews(result);
  }
  function advance(session,instanceId,opticsOverride,pendingId){
    const result=copy(session),element=result.scene.elements.find(e=>e.id===instanceId);if(!element)return result;if(opticsOverride&&!result.pending.some(p=>p.kind==='assembly'&&p.instanceId===instanceId&&(!pendingId||p.id===pendingId))){if(element.opticalInteraction&&opticsOverride.elementType!==undefined&&opticsOverride.elementType!==element.optics.elementType)throw new Error('交互协议元件不能通过实例设置改变作用类型。');element.optics=normalizeOptics(opticsOverride,element.optics);if(element.opticalInteraction)element.interactionParameterEvidence={...element.interactionParameterEvidence,...copy(opticsOverride)};result.traceKey=sessionTraceKey(result);}const matches=p=>p.instanceId===instanceId&&(!pendingId||p.id===pendingId),selected=result.pending.filter(matches);result.pending=result.pending.filter(p=>!matches(p));
    for(const ray of selected){if(ray.kind==='assembly'){if(opticsOverride){const node=element.opticalAssembly.nodes.find(n=>n.id===ray.internalId);if(element.opticalAssembly.version>=2&&(node.type==='coupler'||opticsOverride.source?.enabled))throw new Error('v2内部配置不能覆盖父级耦合口或创建独立光源。');element.internalOptics[ray.internalId]=normalizeOptics(opticsOverride,element.internalOptics[ray.internalId]);element.internalParameterEvidence[ray.internalId]={...element.internalParameterEvidence[ray.internalId],...copy(opticsOverride)};result.traceKey=sessionTraceKey(result);}advanceAssemblyRay(result,element,ray);continue;}if(element.opticalInteraction){const unsupported=simulationIssue(element);if(unsupported){result.pending.push(ray);warning(result,unsupported.code,unsupported.message,instanceId);continue;}advanceInteraction(result,element,ray);continue;}const unsupported=simulationIssue(element);if(unsupported){result.pending.push(ray);warning(result,unsupported.code,unsupported.message,instanceId);continue}const o=element.optics,next={...ray,lastInstanceId:instanceId};for(const key of['id','kind','moduleId','instanceId','offsetMm','segmentId','coincidentElementId','coincidentOffsetMm','coincidentBlockedIssue','blockedIssue'])delete next[key];
      if(!o.inserted||o.elementType==='empty'){extend(result,next);continue}
      const diameter=gaussianAt(ray.beam).diameterMm;if(Math.abs(ray.offsetMm)+diameter/2>o.clearApertureMm/2)warning(result,'aperture_clipping',`${element.name||instanceId} 有效口径不足，光斑可能被截断；当前近轴模型不计算截光衍射或实际损失。`,instanceId);
      if(o.elementType==='aom'){advanceAom(result,element,ray,next);continue;}
      if(o.elementType==='coupler'){const out=vec(finite(element.sourceDirectionDeg)?element.sourceDirectionDeg:element.rotationDeg+o.source.directionAngleDeg);if(dot(ray.direction,out)>-Math.cos(5*RAD)){warning(result,'coupler_direction_mismatch',`${element.name||instanceId} 的入射方向未朝向光口，不能耦合。`,instanceId);extend(result,next)}else{complete(result,next,'coupled',{instanceId,point:copy(ray.point)});warning(result,'ideal_coupling','耦合头按理想接收端终止光线；未计算光纤模式匹配、数值孔径与耦合效率。',instanceId)}continue}
      if(o.elementType==='mirror'){const response=mirrorResponseFor(element,ray.beam,ray.direction);if(!response.ok){result.pending.push(ray);warning(result,response.code,response.message,instanceId);continue}if(response.phaseIndependent)warning(result,'mirror_phase_not_required',`${element.name||instanceId} 的相位差仍未知；当前这束光的输出不依赖该相位差，已仅用已知 Rp/Rs 计算。`,instanceId);if(response.approximate)warning(result,'mirror_ideal_approximation',`${element.name||instanceId} 使用理想反射镜近似（Rp=Rs=1、传播右手基底相位差180°），并非该镜片的实测镀膜数据。`,instanceId);next.direction=reflect(ray.direction,elementAngle(element));next.beam=applyMirror(next.beam,response.response);extend(result,next);continue}
      if(o.elementType==='pbs'||o.elementType==='dichroic'){let split;if(o.elementType==='dichroic'){const response=dichroicResponseFor(element,ray.beam,ray.direction);if(!response.ok){result.pending.push(ray);warning(result,response.code,response.message,instanceId);continue;}if(response.mode==='geometry-only'){const beam={...copy(next.beam),powerIsRelative:true,polarizationUnverified:true,nominalRouting:[...(next.beam.nominalRouting||[]),{instanceId,output:response.output,incidenceAngleDeg:response.incidenceAngleDeg,referenceAngleDeg:response.nominalRouting.referenceAngleDeg}]},branchPath=[...(ray.branchPath||[]),{instanceId,encounter:(ray.branchPath||[]).filter(p=>p.instanceId===instanceId).length+1,output:response.output}];warning(result,'zero_order_nominal_routing','零级按指定反射/透射方向作几何示意；未外推镀膜系数，功率与偏振未知。',instanceId);extend(result,{...next,beam,direction:response.output==='reflected'?reflect(ray.direction,elementAngle(element)):ray.direction,branchPath,lineageKey:JSON.stringify([ray.sourceId,...branchPath])});continue;}split=applyDichroic(ray.beam,response.response);}else split=splitPBS(ray.beam);const outputs=[{beam:split.transmitted,direction:ray.direction,label:'transmitted'},{beam:split.reflected,direction:reflect(ray.direction,elementAngle(element)),label:'reflected'}];for(const output of outputs){const branchPath=[...(ray.branchPath||[]),{instanceId,encounter:(ray.branchPath||[]).filter(p=>p.instanceId===instanceId).length+1,output:output.label}],outgoing={...next,beam:output.beam,direction:output.direction,parentBranchId:ray.branchId,branchPath,lineageKey:JSON.stringify([ray.sourceId,...branchPath])};if(output.beam.powerMw<=result.options.minPowerMw){complete(result,outgoing,'zero-power',{output:output.label});continue}if(result.counters.branches>=result.options.maxBranches){warning(result,'branch_limit','PBS 分支数量已达到上限，请检查重复分束或闭合光路。',instanceId);complete(result,outgoing,'branch-limit',{output:output.label});continue}extend(result,{...outgoing,branchId:`branch-${++result.counters.branches}`})}continue}
      if(o.elementType==='waveplate'){const forward=vec(elementAngle(element)-90),reverse=dot(ray.direction,forward)<0,configured=o.waveplates??[{inserted:true,fastAxisDeg:o.fastAxisDeg,retardanceDeg:o.retardanceDeg,designWavelengthNm:o.designWavelengthNm}],plates=reverse?[...configured].reverse():configured;for(const plate of plates){if(!plate.inserted)continue;if(Math.abs(plate.designWavelengthNm-ray.beam.wavelengthNm)>.01){warning(result,'waveplate_wavelength_mismatch',`${element.name||instanceId} 波片设计波长与光源不同；仍按填写的延迟角计算，未推测厂家色散，请输入该波长下的实测延迟。`,instanceId)}next.beam.stokes=applyWaveplateSequence(next.beam.stokes,[plate],reverse)}extend(result,next);continue}
      if(o.elementType==='lens'&&o.lensPrescription&&ray.lensSurface){advancePhysicalLens(result,element,ray,next);continue;}
      if(o.elementType==='lens'){if(o.focalLengthMm===null){warning(result,'lens_focal_length_missing',`${element.name||instanceId} 尚未填写焦距，当前按直通处理。`,instanceId);extend(result,next);continue}const tangent=vec(elementAngle(element)),normal={x:-tangent.y,y:tangent.x};if(dot(normal,ray.direction)<0){normal.x*=-1;normal.y*=-1}const axial=dot(ray.direction,normal),slope=dot(ray.direction,tangent)/axial;if(Math.abs(slope)>Math.tan(15*RAD))warning(result,'paraxial_limit',`${element.name||instanceId} 入射倾角超过 15°，薄透镜近轴模型精度不足。`,instanceId);next.direction=norm(add(normal,scale(tangent,slope-ray.offsetMm/o.focalLengthMm)));next.beam.qSagittal=lensQ(next.beam.qSagittal||next.beam.q,o.focalLengthMm);next.beam.q=lensQ(next.beam.q,o.focalLengthMm);extend(result,next);continue}
      extend(result,next);
    }return refreshAssemblyViews(result);
  }
  function stableJson(value){if(Array.isArray(value))return'['+value.map(stableJson).join(',')+']';if(value&&typeof value==='object')return'{'+Object.keys(value).filter(k=>value[k]!==undefined).sort().map(k=>JSON.stringify(k)+':'+stableJson(value[k])).join(',')+'}';return JSON.stringify(value)}
  function sessionTraceKey(session){const input=stableJson({scene:session.scene,sources:session.sourceInputs||[],options:session.options});let a=2166136261,b=3339675911;for(let i=0;i<input.length;i++){a=Math.imul(a^input.charCodeAt(i),16777619);b=Math.imul(b^input.charCodeAt(i),2246822519)}return`trace-v1-${input.length}-${(a>>>0).toString(16)}-${(b>>>0).toString(16)}`}
  function eventForPending(session,pendingId){const p=session.pending.find(p=>p.id===pendingId);if(!p)return null;return{kind:p.kind||'element',id:p.kind==='module'?p.moduleId:p.instanceId,...(p.internalId?{internalId:p.internalId}:{}),pendingId:p.id,branchId:p.branchId,sourceId:p.sourceId,lineageKey:p.lineageKey||JSON.stringify([p.sourceId]),branchPath:copy(p.branchPath||[]),pathMm:p.pathMm,traceKey:session.traceKey||sessionTraceKey(session)}}
  function replay(scene,events=[],config={}){let session=createSession(scene,config.sources,config.sessionOptions||{});const applied=[],history=[],issues=[],seen=new Set(),ordinals=new Map(),branchOrdinals=new Map();
    const collect=()=>{for(const p of session.pending){if(seen.has(p.id))continue;seen.add(p.id);const event=eventForPending(session,p.id),target=`${event.kind}:${event.id}:${event.internalId||''}`,ordinal=(ordinals.get(target)||0)+1;ordinals.set(target,ordinal);const branchTarget=`${target}:${event.lineageKey}`,branchOrdinal=(branchOrdinals.get(branchTarget)||0)+1;branchOrdinals.set(branchTarget,branchOrdinal);history.push({...event,instanceId:p.instanceId||null,moduleId:p.moduleId||null,arrivalEventIndex:applied.length,actionEventIndex:null,ordinalForInstance:ordinal,ordinalForBranch:branchOrdinal,status:'pending'})}};collect();
    if(!Array.isArray(events)||events.length>20000)return{session,events:applied,history,valid:false,issues:[{code:'history_invalid',message:'光路历史格式无效或过长。'}]};
    if(events.some(e=>!e||e.traceKey!==session.traceKey))return{session,events:applied,history,valid:false,issues:[{code:'history_scene_changed',message:'场景、光源或光学参数已经变化，旧光路历史已失效，请重新渲染。'}]};
    for(const event of events){const p=session.pending.find(p=>p.id===event.pendingId),current=p?eventForPending(session,p.id):null;if(!current||current.kind!==event.kind||current.id!==event.id||current.internalId!==event.internalId||current.branchId!==event.branchId||current.sourceId!==event.sourceId){issues.push({code:'history_event_mismatch',message:'光路历史与当前待处理的遭遇不一致，已停止重放。',instanceId:event.kind==='element'?event.id:null,moduleId:event.kind==='module'?event.id:null,pendingId:event.pendingId});break}const entry=history.find(v=>v.pendingId===p.id);entry.actionEventIndex=applied.length;entry.status='processed';session=advancePending(session,p.id);applied.push(copy(current));collect()}
    return{session,events:applied,history,valid:issues.length===0,issues};
  }
  function listEncounterHistory(scene,events=[],config={}){return replay(scene,events,config).history}
  function rewind(scene,events,pendingId,config={}){const full=replay(scene,events,config);if(!full.valid)return full;const target=full.history.find(e=>e.pendingId===(typeof pendingId==='object'?pendingId?.pendingId:pendingId));if(!target)return{...full,valid:false,issues:[{code:'history_encounter_missing',message:'这次器件遭遇已不在当前历史中。'}]};const result=replay(scene,full.events.slice(0,target.arrivalEventIndex),config);return{...result,rewoundTo:copy(target),discardedEvents:full.events.length-target.arrivalEventIndex}}
  function rebaseConfirmed(scene,events=[],config={}){const previous=config.previousSession,sessionOptions=config.sessionOptions||previous?.options||{},nextConfig={sources:config.sources,sessionOptions};let session=createSession(scene,nextConfig.sources,sessionOptions);if(!events.length)return{...replay(scene,[],nextConfig),retainedEvents:0,discardedEvents:0,rebased:true};if(!previous)return{...replay(scene,[],nextConfig),valid:false,issues:[{code:'history_previous_scene_missing',message:'缺少旧场景，无法验证并更新原光路。',blocking:true}],retainedEvents:0,discardedEvents:events.length,rebased:true};
    const old=replay(previous.scene,events,{sources:previous.sourceInputs,sessionOptions:previous.options});if(!old.valid)return{...replay(scene,[],nextConfig),valid:false,issues:old.issues,retainedEvents:0,discardedEvents:events.length,rebased:true};
    const retained=[],issues=[],blockedRoutes=new Set(),seen=new Set(),counts=new Map(),encounters=new Map();
    const collect=()=>{for(const p of session.pending){if(seen.has(p.id))continue;seen.add(p.id);const ev=eventForPending(session,p.id),key=`${ev.kind}:${ev.id}:${ev.internalId||''}:${ev.lineageKey}`,ordinal=(counts.get(key)||0)+1;counts.set(key,ordinal);encounters.set(p.id,ordinal)}};collect();
    const routePrefix=(a,b)=>a.length<=b.length&&a.every((entry,i)=>entry.instanceId===b[i].instanceId&&entry.encounter===b[i].encounter&&entry.output===b[i].output);
    const report=issue=>{if(!issues.some(i=>i.code===issue.code&&i.lineageKey===issue.lineageKey&&i.instanceId===issue.instanceId&&i.moduleId===issue.moduleId))issues.push(issue)};
    for(let index=0;index<old.events.length;index++){const event=old.events[index],arrival=old.history.find(h=>h.actionEventIndex===index),route=event.lineageKey;if(blockedRoutes.has(route))continue;if(!session.sourceIds.includes(event.sourceId)){report({code:'source_disabled',message:'原光源已关闭或不可出光，已移除它原来的传播路径。',instanceId:event.sourceId,sourceId:event.sourceId,lineageKey:route,blocking:false});continue}
      const vanished=session.completed.some(c=>c.sourceId===event.sourceId&&c.reason==='zero-power'&&routePrefix(c.branchPath||[],event.branchPath||[]));if(vanished){report({code:'branch_disappeared',message:'分光比例改变后，这条原分支已没有功率，已移除其后续光路。',sourceId:event.sourceId,lineageKey:route,blocking:false});continue}
      const candidates=session.pending.filter(p=>p.lineageKey===route&&p.sourceId===event.sourceId),pending=candidates.find(p=>{const now=eventForPending(session,p.id);return now.kind===event.kind&&now.id===event.id&&now.internalId===event.internalId&&encounters.get(p.id)===arrival.ordinalForBranch});
      if(!pending){blockedRoutes.add(route);const current=candidates[0];report({code:'path_disconnected',message:current?'移动或参数改变后，原路径先遇到了不同的器件或模块，已停在当前实际位置。':'移动或参数改变后，光束已无法继续到达原来的器件，原路径在此中断。',instanceId:current?.instanceId||(event.kind==='element'?event.id:null),moduleId:current?.moduleId||(event.kind==='module'?event.id:null),expectedInstanceId:event.kind==='element'?event.id:null,expectedModuleId:event.kind==='module'?event.id:null,pendingId:current?.id||null,sourceId:event.sourceId,lineageKey:route,blocking:true});continue}
      const issue=pendingIssue(session,pending);if(issue){blockedRoutes.add(route);report({...issue,lineageKey:route});continue}retained.push(eventForPending(session,pending.id));session=advancePending(session,pending.id);collect();
    }
    const oldRoutes=new Set(old.history.map(h=>h.lineageKey));for(const p of session.pending)if(!oldRoutes.has(p.lineageKey))report({code:'new_branch',message:'分光设置产生了一条新路径，将按当前器件设置继续渲染。',instanceId:p.instanceId||null,moduleId:p.moduleId||null,pendingId:p.id,sourceId:p.sourceId,lineageKey:p.lineageKey,blocking:false});
    const rebuilt=replay(scene,retained,nextConfig);return{...rebuilt,issues:[...rebuilt.issues,...issues],valid:rebuilt.valid&&!issues.some(i=>i.blocking),retainedEvents:retained.length,discardedEvents:old.events.length-retained.length,rebased:true};
  }
  function pendingIssue(session,pending){const base={pendingId:pending.id,instanceId:pending.instanceId||null,moduleId:pending.moduleId||null,branchId:pending.branchId,sourceId:pending.sourceId,blocking:true};if(pending.kind==='module')return null;const e=session.scene.elements.find(e=>e.id===pending.instanceId);if(!e)return{...base,code:'element_missing',message:'这个光学元件已不存在。'};if(pending.kind==='assembly')return assemblyPendingIssue(session,pending,e);const unsupported=simulationIssue(e);if(unsupported)return{...base,...unsupported};if(pending.blockedIssue)return{...base,...pending.blockedIssue};if(e.axisHeightMm===null)return{...base,code:'axis_height_unknown',message:'光轴高度未知，请核对出光口资料。'};if(finite(pending.beam.axisHeightMm)&&finite(e.axisHeightMm)&&Math.abs(pending.beam.axisHeightMm-e.axisHeightMm)>(e.opticalInteraction?.heightToleranceMm??session.options.heightToleranceMm))return{...base,code:'height_mismatch',message:'光源与该器件的光轴高度不一致，请使用合适爬架矫正光高并对准光口。'};if(e.opticalInteraction){const computed=interactionResult(e,pending,session.options);return computed.issue?{...base,...computed.issue}:null;}const o=e.optics;if((!o.inserted||o.elementType==='empty')&&!o.configured)return{...base,code:'optics_unconfigured',message:'请确认装入光学件，或明确选择空架直通。'};if(!o.inserted||o.elementType==='empty')return null;if(o.elementType==='aom'){const issue=aomIssue(e,pending);if(issue)return{...base,...issue};}if(o.elementType==='mirror'){const response=mirrorResponseFor(e,pending.beam,pending.direction);if(!response.ok)return{...base,code:response.code,message:response.message};}if(o.elementType==='dichroic'){const response=dichroicResponseFor(e,pending.beam,pending.direction);if(!response.ok)return{...base,code:response.code,message:response.message};}if(o.elementType==='lens'&&o.focalLengthMm===null)return{...base,code:'lens_focal_length_missing',message:'已安装透镜，但尚未填写焦距。'};if(o.elementType==='coupler'){const out=vec(finite(e.sourceDirectionDeg)?e.sourceDirectionDeg:e.rotationDeg+o.source.directionAngleDeg);if(dot(pending.direction,out)>-Math.cos(5*RAD))return{...base,code:'coupler_direction_mismatch',message:'入射方向没有朝向耦合头光口，请调整方向。'}}return null}
  function autoAdvance(session,options={}){let next=copy(session);const events=[],issues=[],started=Date.now(),maxEvents=Math.floor(number(options.maxEvents,16,'自动批次事件数',1,256)),maxMilliseconds=number(options.maxMilliseconds,12,'自动批次时间（ms）',1,1000),blockedWarnings=new Set(['axis_height_unknown','height_mismatch','invalid_source','trace_limit','branch_limit','assembly_out_of_plane','interaction_emission_direction','interaction_emission_wavelength','assembly_geometry_unconfirmed','assembly_source_unconfigured','optical_datum_unknown','optical_aperture_unknown','optics_unsupported','source_port_data_missing','source_port_geometry_unknown']);
    while(events.length<maxEvents&&Date.now()-started<maxMilliseconds){const pending=next.pending.find(p=>!pendingIssue(next,p));if(!pending)break;const event=eventForPending(next,pending.id);next=advancePending(next,pending.id);events.push(event)}
    for(const p of next.pending){const issue=pendingIssue(next,p);if(issue)issues.push(issue)}for(const w of next.warnings||[]){if(blockedWarnings.has(w.code)&&!issues.some(i=>i.code===w.code&&i.instanceId===w.instanceId))issues.push({...w,blocking:true})}
    const canContinue=next.pending.some(p=>!pendingIssue(next,p)),done=next.pending.length===0&&!issues.some(i=>i.blocking);return{session:next,events,issues,done,blocked:!canContinue&&!done,canContinue};
  }
  function advancePending(session,pendingId,opticsOverride){const pending=session.pending.find(p=>p.id===pendingId);if(!pending)return copy(session);return pending.kind==='module'?advanceModule(session,pending.moduleId,pendingId):advance(session,pending.instanceId,opticsOverride,pendingId)}
  function beamAt(segment,t=0){const fraction=clamp(finite(t)?t:0,0,1),d=segment.lengthMm*fraction,point3D=segment.from3D&&segment.to3D?Object.fromEntries(['x','y','z'].map(k=>[k,segment.from3D[k]+fraction*(segment.to3D[k]-segment.from3D[k])])):null;return{...gaussianAt(segment.beam,d),...(point3D?{point3D,axisHeightMm:point3D.z}:{}),point:add(segment.from,scale(sub(segment.to,segment.from),fraction)),distanceFromSourceMm:segment.pathStartMm+d,sourceId:segment.sourceId,branchId:segment.branchId,segmentId:segment.id}}
  function probe(session,point,toleranceMm=5){if(!point||!finite(point.x)||!finite(point.y))return[];const result=[];for(const segment of session.segments){if(segment.internalAssemblySegment)continue;const v=sub(segment.to,segment.from),len2=dot(v,v),t=len2>EPS?clamp(dot(sub(point,segment.from),v)/len2,0,1):0,p=add(segment.from,scale(v,t)),distanceToBeamMm=Math.hypot(point.x-p.x,point.y-p.y);if(distanceToBeamMm<=toleranceMm+EPS)result.push({...beamAt(segment,t),distanceToBeamMm,t})}return result.sort((a,b)=>a.distanceToBeamMm-b.distanceToBeamMm||a.distanceFromSourceMm-b.distanceFromSourceMm)}
  return{version:1,TYPES,POLS,normalizeLensPrescription,silicaLensIndex,physicalLensHit,refractLensSurface,refractLensQ,defaults,normalizeOptics,normalizeSource,validateOptics,sourcePortParameterIssue,stokesFromSource,applyWaveplate,applyWaveplateSequence,waveplateReverse,solveTwoWaveplates,normalizeMirror,normalizeDichroic,incidenceAngleDeg,resolveMirrorResponse,mirrorResponseAt,mirrorResponseFor,applyMirror,dichroicResponseAt,dichroicResponseFor,applyDichroic,splitPBS,initialQ,propagateQ,lensQ,gaussianAt,createBeam,reflect,elementAngle,planeHit,insidePolygon,createSession,eventForPending,replay,listEncounterHistory,rewind,rebaseConfirmed,pendingIssue,autoAdvance,advance,advancePending,advanceModule,enterModule:advanceModule,beamAt,probe,modelDescription:'大板采用二维中心线；已核实复合总装采用真实三维交点、偏振基底与几何路程，水平出射返回大板光路。物镜机械入口终止，不推测未提供的焦平面；双色镜为选定表面的薄面系数模型，未猜测基片折射。其余采用理想 PBS、按给定 Rp/Rs/相位差计算的镜面、无损波片和薄透镜近轴 Gaussian 模型。光斑为 1/e² 强度直径；M²>1 为等效二阶矩近似。无镜面数据的旧工程使用明确标出的理想近似；数据镜面仅使用相同波长和入射角的完整数据点，不外推。未模拟未给出的色散、干涉、非高斯衍射或实际光纤耦合效率；显示几何路程而非折射率加权光程。'};
});
