/* ZZLab optical interaction language v1. Pure data, finite whitelist, no eval. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ZZLabOpticalInteractionLanguage=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const FORMAT='zzlab-optical-interaction',VERSION=1,RAD=Math.PI/180,EPS=1e-7;
  const copy=v=>JSON.parse(JSON.stringify(v)),finite=v=>typeof v==='number'&&Number.isFinite(v);
  function fail(message){throw new Error('光学交互语言：'+message);}
  function shape(value,allowed,required=[]){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!allowed.includes(k))||required.some(k=>!Object.prototype.hasOwnProperty.call(value,k)))fail('缺少字段或存在不支持的字段。');}
  function numeric(v,lo,hi,label){if(!finite(v)||v<lo||v>hi)fail(label+'超出范围或不是有限数值。');return v;}
  function text(v,max,label){if(typeof v!=='string'||!v.trim()||Array.from(v).length>max||/[\u0000-\u001f\u007f]/.test(v))fail(label+'无效。');return v;}
  function condition(v,extra=[],required=[]){
    shape(v,['direction','wavelengthNm',...extra],required);const out={};
    if(v.direction!==undefined){const d=v.direction;shape(d,['angleDeg','halfAngleDeg','bidirectional'],['angleDeg','halfAngleDeg','bidirectional']);if(typeof d.bidirectional!=='boolean')fail('bidirectional 必须为布尔值。');out.direction={angleDeg:numeric(d.angleDeg,-3600,3600,'方向角'),halfAngleDeg:numeric(d.halfAngleDeg,0,90,'方向半角'),bidirectional:d.bidirectional};}
    if(v.wavelengthNm!==undefined){const w=v.wavelengthNm;shape(w,['min','max','onMismatch'],['min','max','onMismatch']);numeric(w.min,1,1e6,'最小波长');numeric(w.max,1,1e6,'最大波长');if(w.min>w.max||!['block','warn'].includes(w.onMismatch))fail('波长区间或策略无效。');out.wavelengthNm=copy(w);}
    return out;
  }
  function normalize(input,physics){
    shape(input,['format','version','model','heightToleranceMm','inputs','onNoMatch','emission'],['format','version','model']);
    if(input.format!==FORMAT||input.version!==VERSION||!['planar','source'].includes(input.model))fail('不支持的格式、版本或模型。');
    const out={format:FORMAT,version:VERSION,model:input.model};
    if(input.heightToleranceMm!==undefined)out.heightToleranceMm=numeric(input.heightToleranceMm,0,100,'光高容差');
    if(input.emission!==undefined)out.emission=condition(input.emission);
    if(input.model==='source'){
      if(input.emission===undefined||input.inputs!==undefined||input.onNoMatch!==undefined)fail('source 需要 emission，不能包含 inputs/onNoMatch。');return out;
    }
    if(input.emission!==undefined)fail('planar 不能包含 emission。');
    if(!['block','pass'].includes(input.onNoMatch)||!Array.isArray(input.inputs)||input.inputs.length<1||input.inputs.length>16)fail('planar 需要 onNoMatch 和 1–16 个输入规则。');
    out.onNoMatch=input.onNoMatch;const ids=new Set();
    out.inputs=input.inputs.map(row=>{
      const c=condition(row,['id','steps'],['id','steps']),id=text(row.id,80,'输入规则编号');if(ids.has(id)||['__proto__','constructor','prototype'].includes(id))fail('输入规则编号重复或保留。');ids.add(id);
      if(!Array.isArray(row.steps)||row.steps.length<1||row.steps.length>8)fail('每个输入规则需要 1–8 个步骤。');
      return{id,...c,steps:row.steps.map(step=>{
        const fields={pass:[],pbs:[],mirror:['mirror'],waveplate:['waveplates'],lens:['focalLengthMm'],coupler:['halfAngleDeg'],attenuate:['transmission'],absorb:['reason'],block:['reason']};
        if(!step||!Object.hasOwn(fields,step.op))fail('不支持的操作。');shape(step,['op',...fields[step.op]],['op',...(['attenuate'].includes(step.op)?['transmission']:step.op==='block'?['reason']:[])]);const s={op:step.op};
        if(step.reason!==undefined)s.reason=text(step.reason,500,'原因');
        if(step.mirror!==undefined){if(!physics?.normalizeMirror)fail('镜面验证器不可用。');s.mirror=physics.normalizeMirror(step.mirror);}
        if(step.waveplates!==undefined){if(!Array.isArray(step.waveplates)||step.waveplates.length<1||step.waveplates.length>8)fail('波片数组需要 1–8 片。');s.waveplates=step.waveplates.map(p=>{shape(p,['inserted','fastAxisDeg','retardanceDeg','designWavelengthNm'],['inserted']);if(typeof p.inserted!=='boolean')fail('波片 inserted 必须为布尔值。');const q={inserted:p.inserted};for(const[k,lo,hi]of[['fastAxisDeg',-3600,3600],['retardanceDeg',-36000,36000],['designWavelengthNm',1,1e6]])if(p[k]!==undefined)q[k]=numeric(p[k],lo,hi,k);return q;});}
        if(step.focalLengthMm!==undefined){numeric(step.focalLengthMm,-1e6,1e6,'焦距');if(Math.abs(step.focalLengthMm)<1e-6)fail('焦距不能为零。');s.focalLengthMm=step.focalLengthMm;}
        if(step.halfAngleDeg!==undefined)s.halfAngleDeg=numeric(step.halfAngleDeg,0,90,'耦合半角');
        if(step.transmission!==undefined)s.transmission=numeric(step.transmission,0,1,'功率透过率');
        return s;
      })};
    });return out;
  }
  const vec=a=>({x:Math.cos(a*RAD),y:Math.sin(a*RAD)}),dot=(a,b)=>a.x*b.x+a.y*b.y;
  function angleDifference(a,b){return Math.abs(((a-b+180)%360+360)%360-180);}
  function directionMatches(rule,direction,rotationDeg=0){if(!rule)return true;const angle=Math.atan2(direction.y,direction.x)/RAD-rotationDeg,d=angleDifference(angle,rule.angleDeg);return Math.min(d,rule.bidirectional?180-d:Infinity)<=rule.halfAngleDeg+EPS;}
  function wavelengthIssue(rule,beam){if(!rule||beam.wavelengthNm>=rule.min-EPS&&beam.wavelengthNm<=rule.max+EPS)return null;return{code:'interaction_wavelength_mismatch',message:`波长 ${beam.wavelengthNm} nm 不在交互规则 ${rule.min}–${rule.max} nm 范围内。`,blocking:rule.onMismatch==='block'};}
  function emissionIssue(def,element,source,direction){if(!finite(element.axisHeightMm))return{code:'axis_height_unknown',message:'光源实际出光高度未知；交互声明不能代替已核实的光高。',blocking:true};const rule=def.emission;if(!rule)return null;if(!directionMatches(rule.direction,direction,element.rotationDeg||0))return{code:'interaction_emission_direction',message:'出光方向不符合元件声明的端口方向。',blocking:true};const issue=wavelengthIssue(rule.wavelengthNm,source);return issue?.blocking?{...issue,code:'interaction_emission_wavelength'}:issue;}
  function evaluate(def,element,ray,options,api){
    const block=(code,message)=>({issue:{code,message,blocking:true},warnings:[],outputs:[]});
    if(def.model!=='planar')return block('interaction_source_input','该交互声明为光源，不支持入射作用。');
    const o=element.optics;
    if(!finite(element.axisHeightMm)||!finite(ray.beam.axisHeightMm))return block('axis_height_unknown','光源或器件的真实光轴高度未知，不能执行交互语言。');
    if(Math.abs(element.axisHeightMm-ray.beam.axisHeightMm)>(def.heightToleranceMm??options.heightToleranceMm??.1))return block('height_mismatch','入射光高不满足该器件的端口高度条件。');
    const straight=()=>({beam:copy(ray.beam),direction:copy(ray.direction),label:'transmitted'});
    if(!o.inserted){if(!o.configured)return block('optics_unconfigured','请确认已装光学片或明确选择空架直通。');return{issue:null,warnings:[],outputs:[straight()]};}
    const matches=def.inputs.filter(row=>directionMatches(row.direction,ray.direction,element.rotationDeg||0));
    if(matches.length>1)return block('interaction_ambiguous_input','多个输入方向规则同时匹配；请使端口规则互斥。');
    if(!matches.length)return def.onNoMatch==='pass'?{issue:null,warnings:[],outputs:[straight()]}:block('interaction_no_input','入射方向没有匹配该元件的输入端口。');
    const rule=matches[0],warnings=[],wavelength=wavelengthIssue(rule.wavelengthNm,ray.beam);
    if(wavelength?.blocking)return block(wavelength.code,wavelength.message);if(wavelength)warnings.push(wavelength);
    const diameter=api.gaussianAt(ray.beam).diameterMm;
    if(Math.abs(ray.offsetMm||0)+diameter/2>o.clearApertureMm/2)warnings.push({code:'aperture_clipping',message:'有效通光口径不足；仍按近轴光束传播，不推测截光损耗或衍射。'});
    let outputs=[straight()];
    for(let index=0;index<rule.steps.length;index++){
      const step=rule.steps[index],next=[];
      for(const incoming of outputs){
        if(incoming.terminal){next.push(incoming);continue;}const v=copy(incoming),angle=api.elementAngle(element),beam=v.beam;
        if(step.op==='block')return block('interaction_declared_block',step.reason);
        if(step.op==='absorb'){v.terminal='absorbed';v.reason=step.reason||'按声明吸收并终止';}
        else if(step.op==='attenuate')beam.powerMw*=step.transmission;
        else if(step.op==='coupler'){
          const out=vec(Number.isFinite(element.sourceDirectionDeg)?element.sourceDirectionDeg:(element.rotationDeg||0)+o.source.directionAngleDeg);
          if(dot(v.direction,out)>-Math.cos((step.halfAngleDeg??5)*RAD)+EPS)return block('coupler_direction_mismatch','入射方向未朝向耦合头接收光口。');v.terminal='coupled';warnings.push({code:'ideal_coupling',message:'按理想耦合接收终止，未计算实际模式匹配和耦合效率。'});
        }else if(step.op==='mirror'){
          if(step.mirror===undefined&&o.mirror===undefined)return block('interaction_mirror_data_missing','镜面步骤需要已声明的数据模式或主动选择的理想模式；不自动继承旧式隐含理想镜。');
          const target={...element,optics:{...o,mirror:step.mirror??o.mirror}},r=api.mirrorResponseFor(target,beam,v.direction);
          if(!r.ok)return block(r.code,r.message);v.beam=api.applyMirror(beam,r.response);v.direction=api.reflect(v.direction,angle);v.label+=':reflected';
          if(r.approximate)warnings.push({code:'mirror_ideal_approximation',message:'此步骤使用显式理想镜面近似，非实测镀膜。'});
          if(r.phaseIndependent)warnings.push({code:'mirror_phase_not_required',message:'相位仍未知，但本次入射的输出不依赖该相位。'});
        }else if(step.op==='pbs'){
          const split=api.splitPBS(beam);next.push({...copy(v),beam:split.transmitted,label:v.label+':transmitted'},{...copy(v),beam:split.reflected,direction:api.reflect(v.direction,angle),label:v.label+':reflected'});continue;
        }else if(step.op==='waveplate'){
          const evidence=element.interactionParameterEvidence||{};if(step.waveplates===undefined&&(!o.configured||!(Array.isArray(evidence.waveplates)?evidence.waveplates.every(p=>p.inserted===false||['fastAxisDeg','retardanceDeg','designWavelengthNm'].every(k=>finite(p[k]))):['fastAxisDeg','retardanceDeg','designWavelengthNm'].every(k=>finite(evidence[k])))))return block('interaction_waveplate_data_missing','波片步骤需要已确认的完整实例参数；通用默认值不能代替实际快轴、延迟和设计波长。');
          const plates=step.waveplates??o.waveplates??[{inserted:true,fastAxisDeg:o.fastAxisDeg,retardanceDeg:o.retardanceDeg,designWavelengthNm:o.designWavelengthNm}];
          if(plates.some(p=>p.inserted&&(!finite(p.fastAxisDeg)||!finite(p.retardanceDeg)||!finite(p.designWavelengthNm))))return block('interaction_waveplate_data_missing','显式波片步骤缺少快轴角、延迟角或设计波长；请填写确认值，不自动补测量参数。');
          if(plates.some(p=>p.inserted&&Math.abs(p.designWavelengthNm-beam.wavelengthNm)>.01))warnings.push({code:'waveplate_wavelength_mismatch',message:'波片设计波长不匹配，仍使用已声明延迟；未推测色散。'});
          beam.stokes=api.applyWaveplateSequence(beam.stokes,plates,api.waveplateReverse(element,v.direction));
        }else if(step.op==='lens'){
          const f=step.focalLengthMm??o.focalLengthMm;if(!finite(f)||Math.abs(f)<1e-6)return block('lens_focal_length_missing','透镜步骤尚无有效焦距。');
          const tangent=vec(angle),normal={x:-tangent.y,y:tangent.x};if(dot(normal,v.direction)<0){normal.x*=-1;normal.y*=-1;}const axial=dot(v.direction,normal);if(Math.abs(axial)<EPS)return block('interaction_grazing_lens','掠入射不支持薄透镜近轴计算。');
          const slope=dot(v.direction,tangent)/axial;if(Math.abs(slope)>Math.tan(15*RAD))warnings.push({code:'paraxial_limit',message:'透镜入射倾角超过15°，近轴模型精度不足。'});
          const s=slope-(ray.offsetMm||0)/f,dx=normal.x+tangent.x*s,dy=normal.y+tangent.y*s,length=Math.hypot(dx,dy);v.direction={x:dx/length,y:dy/length};beam.q=api.lensQ(beam.q,f);
        }
        next.push(v);
      }
      outputs=next;if(outputs.length>16)return block('interaction_output_limit','单次作用超过16个输出分支，已停止。');
    }
    let total=0;
    for(const v of outputs){const b=v.beam;if(!finite(b.powerMw)||b.powerMw<0||!finite(b.q?.re)||!finite(b.q?.im)||b.q.im<=0||!finite(v.direction.x)||!finite(v.direction.y)||Math.abs(Math.hypot(v.direction.x,v.direction.y)-1)>1e-7||!b.stokes||!['s0','s1','s2','s3'].every(k=>finite(b.stokes[k]))||Math.abs(b.stokes.s0-1)>1e-7||Math.hypot(b.stokes.s1,b.stokes.s2,b.stokes.s3)>1+1e-7)return block('interaction_invalid_output','输出光束出现非物理数值。');total+=b.powerMw;}
    if(total>ray.beam.powerMw+Math.max(1e-10,ray.beam.powerMw*1e-10))return block('interaction_energy_invalid','无源交互输出功率超过入射功率。');
    return{issue:null,warnings,outputs,inputId:rule.id};
  }
  return{FORMAT,VERSION,normalize,directionMatches,emissionIssue,evaluate};
});
