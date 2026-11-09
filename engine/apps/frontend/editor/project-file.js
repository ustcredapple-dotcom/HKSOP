/* Portable project files: data only, never a source of catalog assets or manufacturing policy. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ZZLabProjectFile = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const FORMAT = 'zzlab-optics-project', VERSION = 1, EXTENSION = '.zzoptics.json';
  const MAX_BYTES = 8 * 1024 * 1024, MAX_INSTANCES = 500, MAX_ENTRIES = 2000;
  const MAX_COLLISION_OVERRIDES = 10000;
  const STAGE_CAPABILITY = 'zzlab-stage-motion-v2', COLLISION_CAPABILITY = 'zzlab-collision-overrides-v1';
  const MANUAL_SOURCE_CAPABILITY = 'zzlab-manual-source-mount-v1';
  const LEGACY_MANUAL_CATALOG_VERSION = '2026-10-06.11-periscope-r3-rf180';
  const SUPPORTED_CAPABILITIES = [STAGE_CAPABILITY, COLLISION_CAPABILITY, 'zzlab-metric-supports-v1', 'zzlab-glass-chamber-v1', MANUAL_SOURCE_CAPABILITY, 'zzlab-physical-lens-v1', 'zzlab-aom-diffraction-v1', 'zzlab-zero-order-routing-v1'];
  const FORBIDDEN = new Set(['__proto__', 'prototype', 'constructor']);
  const own = (o, key) => Object.prototype.hasOwnProperty.call(o, key);
  const supplied = (o, key, fallback) => own(o, key) ? o[key] : fallback;
  function legacyManualProject(source, catalog) {
    const requirements = source.requires === undefined ? [] : source.requires;
    const instances = source.layout?.instances;
    if (source.catalogVersion !== LEGACY_MANUAL_CATALOG_VERSION || !Array.isArray(requirements) || requirements.includes(MANUAL_SOURCE_CAPABILITY) || !Array.isArray(instances)) return false;
    if (instances.some(i => !i || typeof i !== 'object' || Array.isArray(i) || own(i, 'manualMount'))) return false;
    const manualIds = new Set((catalog?.kits || []).filter(k => k.layout?.manualMountingPolicy).map(k => k.id));
    return instances.some(i => manualIds.has(i.kitId));
  }
  class ProjectFileError extends Error {
    constructor(code, message, path = '') { super(message); this.name = 'ProjectFileError'; this.code = code; this.path = path; }
  }
  function fail(code, message, path) { throw new ProjectFileError(code, message, path); }
  function bytes(text) {
    let size = 0;
    for (const ch of text) { const n = ch.codePointAt(0); size += n <= 0x7f ? 1 : n <= 0x7ff ? 2 : n <= 0xffff ? 3 : 4; }
    return size;
  }
  function object(value, path) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail('invalid_shape', `${path} 应为对象。`, path);
    return value;
  }
  function keys(value, allowed, path, required = []) {
    object(value, path);
    const names = new Set(allowed);
    for (const key of Object.keys(value)) if (!names.has(key)) fail('unknown_field', `${path} 含不支持的字段：${key}。`, `${path}.${key}`);
    for (const key of required) if (!own(value, key)) fail('missing_field', `${path} 缺少 ${key}。`, `${path}.${key}`);
    return value;
  }
  function list(value, path, limit = MAX_ENTRIES) {
    if (!Array.isArray(value) || value.length > limit) fail('invalid_shape', `${path} 应为最多 ${limit} 项的数组。`, path);
    return value;
  }
  function text(value, path, max = 256, required = false) {
    if (typeof value !== 'string' || value.length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value) || (required && !value.trim())) fail('invalid_text', `${path} 的文字为空、过长或含无效字符。`, path);
    return value;
  }
  function id(value, path) {
    text(value, path, 80, true);
    if (value !== value.trim() || FORBIDDEN.has(value)) fail('invalid_id', `${path} 的编号无效。`, path);
    return value;
  }
  function number(value, path, low = -1e7, high = 1e7) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < low || value > high) fail('invalid_number', `${path} 必须为 ${low} 至 ${high} 的有限数字。`, path);
    return value;
  }
  function integer(value, path, low = 1, high = 9999) {
    number(value, path, low, high);
    if (!Number.isInteger(value)) fail('invalid_number', `${path} 必须为整数。`, path);
    return value;
  }
  function collisionOverrides(value, instances) {
    const path = 'layout.collisionOverrides', seen = new Set();
    const result = list(value, path, MAX_COLLISION_OVERRIDES).map((row, index) => {
      const p = `${path}.${index}`;
      keys(row, ['instanceIds'], p, ['instanceIds']);
      const pair = list(row.instanceIds, p + '.instanceIds', 2);
      if (pair.length !== 2) fail('invalid_collision_override', '碰撞豁免必须指定两个不同的器件实例。', p);
      const ids = pair.map((value, i) => id(value, `${p}.instanceIds.${i}`)).sort();
      if (ids[0] === ids[1]) fail('invalid_collision_override', '碰撞豁免必须指定两个不同的器件实例。', p);
      if (ids.some(value => !instances.has(value))) fail('unknown_instance', '碰撞豁免引用了不存在的器件实例。', p);
      const identity = JSON.stringify(ids);
      if (seen.has(identity)) fail('duplicate_collision_override', '同一对器件的碰撞豁免不能重复。', p);
      seen.add(identity);
      return { instanceIds: ids };
    });
    return result.sort((a, b) => a.instanceIds[0] < b.instanceIds[0] ? -1 : a.instanceIds[0] > b.instanceIds[0] ? 1 : a.instanceIds[1] < b.instanceIds[1] ? -1 : a.instanceIds[1] > b.instanceIds[1] ? 1 : 0);
  }
  function elevationFields(source, path) {
    const result = {};
    if (own(source, 'elevationMm')) {
      const value = number(source.elevationMm, path + '.elevationMm', 0, 1000);
      if (Math.abs(value * 1000 - Math.round(value * 1000)) > 1e-6) fail('invalid_number', '垫高高度请使用 0.001 mm 的倍数。', path + '.elevationMm');
      result.elevationMm = Math.round(value * 1000) / 1000;
    }
    if (own(source, 'elevationSupportCount')) result.elevationSupportCount = integer(source.elevationSupportCount, path + '.elevationSupportCount', 1, 128);
    return result;
  }
  function postSelectionFields(source,path,kit,catalog){
    if(!own(source,'universalPostSelection'))return{};
    const p=path+'.universalPostSelection',selection=object(source.universalPostSelection,p),posts=new Map((catalog.universalPostSeries?.posts||[]).map(row=>[row.componentId,row])),originals=(kit.components||[]).filter(row=>posts.has(row.componentId));
    if(Object.keys(selection).length>32)fail('invalid_post_selection','换柱最多支持32项。',p);
    const result={};for(const [original,replacement] of Object.entries(selection)){
      id(original,p);id(replacement,p);if(!originals.some(row=>row.componentId===original)||!posts.has(replacement))fail('invalid_post_selection','换柱选择未对应当前套件的原柱或登记目标柱。',p);result[original]=replacement;
    }
    const deltas=originals.map(row=>posts.get(result[row.componentId]||row.componentId).heightMm-posts.get(row.componentId).heightMm);
    if(deltas.some(delta=>Math.abs(delta-deltas[0])>1e-5))fail('invalid_post_selection','同一套件的所有支撑柱必须改变相同高度。',p);
    return{universalPostSelection:result};
  }
  function laserAdapterFields(source, path) {
    if (!own(source, 'laserAdapter')) return {};
    const p = path + '.laserAdapter', a = source.laserAdapter;
    keys(a, ['enabled', 'thicknessMm', 'mountingOriginXMm', 'mountingOriginYMm', 'mountingDatumConfirmed'], p, ['enabled', 'thicknessMm']);
    if (source.kitId !== 'laser-308nm' || a.enabled !== true) fail('invalid_adapter', '光轴对齐垫板仅用于 308 nm 激光器；停用时请移除设置。', p);
    const precise = (value, name, low, high) => {
      number(value, p + '.' + name, low, high);
      if (Math.abs(value * 1000 - Math.round(value * 1000)) > 1e-6) fail('invalid_number', '垫板尺寸请使用 0.001 mm 的倍数。', p + '.' + name);
      return Math.round(value * 10) / 10;
    };
    const result = { enabled: true, thicknessMm: precise(a.thicknessMm, 'thicknessMm', 8.5, 50) };
    for (const key of ['mountingOriginXMm', 'mountingOriginYMm']) if (own(a, key)) result[key] = precise(a[key], key, -500, 500);
    if (own(a, 'mountingDatumConfirmed')) {
      if (typeof a.mountingDatumConfirmed !== 'boolean') fail('invalid_adapter', '安装孔基准确认状态必须为布尔值。', p + '.mountingDatumConfirmed');
      result.mountingDatumConfirmed = a.mountingDatumConfirmed;
    }
    return { laserAdapter: result };
  }
  function opticsFields(instance, path) {
    if (!own(instance, 'optics')) return {};
    const o = instance.optics, p = path + '.optics';
    keys(o, ['elementType', 'inserted', 'configured', 'surfaceAngleDeg', 'pbsHandedness', 'fastAxisDeg', 'retardanceDeg', 'designWavelengthNm', 'focalLengthMm', 'clearApertureMm', 'source', 'waveplates', 'mirror', 'dichroic', 'lensPrescription', 'aom'], p, ['elementType', 'inserted']);
    const boolean = (value, name) => {
      if (typeof value !== 'boolean') fail('invalid_optics', `${name} 必须为布尔值。`, name);
      return value;
    };
    const ranges = { surfaceAngleDeg: [-3600, 3600], fastAxisDeg: [-3600, 3600], retardanceDeg: [-36000, 36000],
      designWavelengthNm: [1, 1e6], clearApertureMm: [1e-6, 1e4], wavelengthNm: [1, 1e6], powerMw: [0, 1e9],
      beamDiameterMm: [1e-6, 1e4], polarizationAngleDeg: [-3600, 3600], ellipticityDeg: [-45, 45],
      beamQualityM2: [1, 100], directionAngleDeg: [-3600, 3600] };
    const copyNumbers = (source, result, fields, prefix) => {
      for (const key of fields) if (own(source, key)) result[key] = number(source[key], prefix + '.' + key, ...ranges[key]);
    };
    const nullableNonzero = (value, name, maximum) => {
      if (value === null) return null;
      number(value, name, -maximum, maximum);
      if (Math.abs(value) < 1e-6) fail('invalid_optics', `${name} 不得为零或接近零。`, name);
      return value;
    };
    const result = { elementType: choice(o.elementType, ['empty', 'mirror', 'dichroic', 'pbs', 'waveplate', 'lens', 'coupler', 'source', 'unsupported', 'aom'], p + '.elementType'), inserted: boolean(o.inserted, p + '.inserted') };
    if (own(o, 'configured')) result.configured = boolean(o.configured, p + '.configured');
    copyNumbers(o, result, ['surfaceAngleDeg', 'fastAxisDeg', 'retardanceDeg', 'designWavelengthNm', 'clearApertureMm'], p);
    if (own(o, 'pbsHandedness')) result.pbsHandedness = choice(o.pbsHandedness, ['left', 'right'], p + '.pbsHandedness');
    if (own(o, 'focalLengthMm')) result.focalLengthMm = nullableNonzero(o.focalLengthMm, p + '.focalLengthMm', 1e6);

    if(own(o,'aom')){
      const a=o.aom,n=p+'.aom',fields=['version','angleMrad','referenceWavelengthNm','rfMHz','awayLocalDeg','powerMode','nominalDatumAccepted'];keys(a,fields,n,fields);
      if(o.elementType!=='aom'||a.version!==1||a.powerMode!=='geometry-only'||a.nominalDatumAccepted!==true)fail('invalid_optics','AOM名义几何配置无效。',n);
      result.aom={version:1,angleMrad:number(a.angleMrad,n+'.angleMrad',.000001,100),referenceWavelengthNm:number(a.referenceWavelengthNm,n+'.referenceWavelengthNm',1,1e6),rfMHz:number(a.rfMHz,n+'.rfMHz',.001,10000),awayLocalDeg:number(a.awayLocalDeg,n+'.awayLocalDeg',-3600,3600),powerMode:'geometry-only',nominalDatumAccepted:true};
    }
    if(own(o,'lensPrescription')){
      const v=o.lensPrescription,n=p+'.lensPrescription',fields=['version','kind','material','model','frontRadiusMm','thicknessMm','frontVertexOffsetMm'];keys(v,fields,n,fields);
      if(result.elementType!=='lens'||v.version!==1||v.kind!=='plano-convex'||v.material!=='fused_silica')fail('invalid_optics','不支持的实体透镜处方。',n);
      result.lensPrescription={version:1,kind:v.kind,material:v.material,model:text(v.model,n+'.model',160),frontRadiusMm:number(v.frontRadiusMm,n+'.frontRadiusMm',1e-3,1e6),thicknessMm:number(v.thicknessMm,n+'.thicknessMm',1e-4,1e3),frontVertexOffsetMm:number(v.frontVertexOffsetMm,n+'.frontVertexOffsetMm',-1e4,1e4)};
    }
    if (own(o, 'mirror')) {
      const m = o.mirror, name = p + '.mirror';
      keys(m, ['mode', 'model', 'samples'], name, ['mode', 'samples']);
      result.mirror = { mode: choice(m.mode, ['ideal', 'data'], name + '.mode') };
      if (own(m, 'model')) result.mirror.model = text(m.model, name + '.model', 160);
      if (own(m, 'samples')) {
        const ranges = { wavelengthNm: [1, 1e6], incidenceAngleDeg: [0, 90], reflectanceP: [0, 1], reflectanceS: [0, 1], phaseDifferenceDeg: [-36000, 36000] }, seen = new Set();
        result.mirror.samples = list(m.samples, name + '.samples', 256).map((sample, index) => {
          const point = name + '.samples.' + index, fields = Object.keys(ranges), row = {};
          keys(sample, fields, point, fields);
          for (const key of fields) row[key] = sample[key] === null && ['reflectanceP', 'reflectanceS', 'phaseDifferenceDeg'].includes(key) ? null : number(sample[key], point + '.' + key, ...ranges[key]);
          const identity = `${row.wavelengthNm}:${row.incidenceAngleDeg}`;
          if (seen.has(identity)) fail('invalid_optics', '反射镜系数表不能在同一波长及入射角重复登记。', point);
          seen.add(identity);
          return row;
        });
      }
    }
    if (own(o, 'dichroic')) {
      const m=o.dichroic,name=p+'.dichroic';keys(m,['mode','model','samples','zeroOrderPreview'],name,['mode','samples']);
      result.dichroic={mode:choice(m.mode,['data'],name+'.mode')};
      if(own(m,'model'))result.dichroic.model=text(m.model,name+'.model',160);
      if(own(m,'zeroOrderPreview')){const v=m.zeroOrderPreview,n=name+'.zeroOrderPreview';keys(v,['version','wavelengthNm','referenceAngleDeg','maxAngleDeviationDeg','output'],n,['version','wavelengthNm','referenceAngleDeg','maxAngleDeviationDeg','output']);if(v.version!==1)fail('invalid_optics','不支持的零级几何预览版本。',n);result.dichroic.zeroOrderPreview={version:1,wavelengthNm:number(v.wavelengthNm,n+'.wavelengthNm',1,1e6),referenceAngleDeg:number(v.referenceAngleDeg,n+'.referenceAngleDeg',0,90),maxAngleDeviationDeg:number(v.maxAngleDeviationDeg,n+'.maxAngleDeviationDeg',.000001,5),output:choice(v.output,['reflected','transmitted'],n+'.output')};}
      const ranges={wavelengthNm:[1,1e6],incidenceAngleDeg:[0,90],reflectanceP:[0,1],reflectanceS:[0,1],transmittanceP:[0,1],transmittanceS:[0,1],reflectionPhaseDifferenceDeg:[-36000,36000],transmissionPhaseDifferenceDeg:[-36000,36000]},seen=new Set();
      result.dichroic.samples=list(m.samples,name+'.samples',256).map((sample,index)=>{
        const point=name+'.samples.'+index,fields=Object.keys(ranges),row={};keys(sample,fields,point,fields);
        for(const key of fields)row[key]=sample[key]===null&&!['wavelengthNm','incidenceAngleDeg'].includes(key)?null:number(sample[key],point+'.'+key,...ranges[key]);
        for(const pol of ['P','S'])if(row['reflectance'+pol]!==null&&row['transmittance'+pol]!==null&&row['reflectance'+pol]+row['transmittance'+pol]>1+1e-9)fail('invalid_optics','双色镜同偏振反射率与透射率之和不能大于1。',point);
        const identity=`${row.wavelengthNm}:${row.incidenceAngleDeg}`;if(seen.has(identity))fail('invalid_optics','双色镜系数表不能在同一波长及入射角重复登记。',point);seen.add(identity);return row;
      });
    }
    if (own(o, 'waveplates')) result.waveplates = list(o.waveplates, p + '.waveplates', 8).map((plate, index) => {
      const name = p + '.waveplates.' + index;
      keys(plate, ['inserted', 'fastAxisDeg', 'retardanceDeg', 'designWavelengthNm'], name, ['inserted']);
      const item = { inserted: boolean(plate.inserted, name + '.inserted') };
      copyNumbers(plate, item, ['fastAxisDeg', 'retardanceDeg', 'designWavelengthNm'], name);
      return item;
    });
    if (own(o, 'source')) {
      const s = o.source, name = p + '.source';
      keys(s, ['enabled', 'wavelengthNm', 'powerMw', 'beamDiameterMm', 'polarizationType', 'polarizationAngleDeg', 'ellipticityDeg', 'wavefrontRadiusMm', 'beamQualityM2', 'directionAngleDeg'], name, ['enabled']);
      result.source = { enabled: boolean(s.enabled, name + '.enabled') };
      copyNumbers(s, result.source, ['wavelengthNm', 'powerMw', 'beamDiameterMm', 'polarizationAngleDeg', 'ellipticityDeg', 'beamQualityM2', 'directionAngleDeg'], name);
      if (own(s, 'polarizationType')) result.source.polarizationType = choice(s.polarizationType, ['linear', 'circular-left', 'circular-right', 'elliptical', 'unpolarized'], name + '.polarizationType');
      if (own(s, 'wavefrontRadiusMm')) result.source.wavefrontRadiusMm = nullableNonzero(s.wavefrontRadiusMm, name + '.wavefrontRadiusMm', 1e12);
    }
    return { optics: result };
  }
  function internalOpticsFields(instance, path, kit) {
    if(!own(instance,'internalOptics'))return {};
    const value=object(instance.internalOptics,path+'.internalOptics'),elements=kit?.layout?.opticalAssembly?.internalElements;
    if(Object.keys(value).length>16||!Array.isArray(elements))fail('invalid_optics','内部光学配置只适用于已登记整装，最多16个内部光学面。',path);
    const known=new Map(elements.map(element=>[element.id,element])),result={};
    for(const [identity,config] of Object.entries(value)){
      id(identity,path+'.internalOptics.id');
      if(!known.has(identity))fail('invalid_optics','内部光学面编号未在当前整装目录中登记。',path+'.internalOptics.'+identity);
      object(config,path+'.internalOptics.'+identity);
      const raw={...config};delete raw.coatingFaceIndex;
      const clean=opticsFields({optics:raw},path+'.internalOptics.'+identity).optics;
      if(own(config,'coatingFaceIndex')){
        const face=config.coatingFaceIndex;
        if(!['mirror','dichroic'].includes(clean.elementType)||!(face===null||face===0||face===1))fail('invalid_optics','内部镜片镀膜面只能为0、1或待确认空值。',path);
        clean.coatingFaceIndex=face;
      }
      if(clean.elementType!==known.get(identity).type||['source','coupler'].includes(clean.elementType)||clean.source?.enabled)fail('invalid_optics','内部光学面类型必须与源整装一致，且不能启用独立光源。',path+'.internalOptics.'+identity);
      if(kit.layout.opticalAssembly.version>=2&&clean.elementType==='waveplate'){const plates=config.waveplates||[config];if(plates.length!==1||clean.configured&&clean.inserted&&!['fastAxisDeg','retardanceDeg','designWavelengthNm'].every(k=>own(plates[0],k)))fail('invalid_optics','v2每个独立波片平面需要单片配置；已确认插片须有完整快轴、延迟和设计波长。',path+'.internalOptics.'+identity);}
      result[identity]=clean;
    }
    return {internalOptics:result};
  }
  function sourcePortFields(instance,path,kit){
    if(!own(instance,'sourcePorts'))return{};
    const p=path+'.sourcePorts',layout=kit?.layout||{},sourceKit=layout.opticalType==='source'||!own(layout,'opticalType')&&kit?.category==='laser';
    if(!sourceKit||layout.opticalAssembly&&typeof layout.opticalAssembly==='object')fail('invalid_optics','独立光源口仅适用于父级激光源套件。',p);
    const ports=layout.opticalPortsMm,value=object(instance.sourcePorts,p),known=new Map(),seen=new Set();
    if(!Array.isArray(ports)||ports.length<2||ports.length>17||Object.keys(value).length>16)fail('invalid_optics','独立光源口需要目录登记，最多16项。',p);
    const safeId=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(value)&&!FORBIDDEN.has(value);
    for(let index=0;index<ports.length;index++){
      const port=ports[index];
      if(!port||typeof port!=='object'||Array.isArray(port)||!safeId(port.id)||seen.has(port.id))fail('invalid_optics','目录光源口编号必须为唯一安全ID。',p);
      seen.add(port.id);if(index===0)continue;
      if(port.role!=='source'||port.sourceVersion!==1||typeof port.geometryConfirmed!=='boolean')fail('invalid_optics','额外光源口缺少role、版本或名义几何确认状态。',p);
      for(const key of ['xMm','yMm','beamHeightMm','directionX','directionY'])if(typeof port[key]!=='number'||!Number.isFinite(port[key])||Math.abs(port[key])>1e4||key==='beamHeightMm'&&port[key]<0)fail('invalid_optics','额外光源口固定几何无效。',p);
      if(Math.hypot(port.directionX,port.directionY)<1e-9)fail('invalid_optics','额外光源口水平出光方向不能为零。',p);
      known.set(port.id,port);
    }
    const result={};
    for(const [identity,config]of Object.entries(value)){
      if(!safeId(identity)||!known.has(identity))fail('invalid_optics','光源口编号未登记、属于主口或不安全。',p+'.'+identity);
      const name=p+'.'+identity;keys(config,['configured','source'],name,['configured','source']);
      if(typeof config.configured!=='boolean')fail('invalid_optics','独立光源确认状态必须为布尔值。',name);
      keys(config.source,['enabled','wavelengthNm','powerMw','beamDiameterMm','beamQualityM2','polarizationType','polarizationAngleDeg','ellipticityDeg','wavefrontRadiusMm'],name+'.source',['enabled']);
      const clean=opticsFields({optics:{elementType:'source',inserted:true,source:config.source}},name).optics.source;
      if(config.configured){
        const required=['wavelengthNm','powerMw','beamDiameterMm','beamQualityM2','polarizationType','wavefrontRadiusMm'];
        if(['linear','elliptical'].includes(clean.polarizationType))required.push('polarizationAngleDeg');
        if(clean.polarizationType==='elliptical')required.push('ellipticityDeg');
        if(!required.every(key=>own(clean,key)))fail('invalid_optics','确认独立光源前须明示波长、功率、束径、M²、偏振及波前；空波前表示用户接受束腰假设。',name);
      }
      result[identity]={configured:config.configured,source:clean};
    }
    return{sourcePorts:result};
  }
  function choice(value, values, path) {
    if (!values.includes(value)) fail('invalid_value', `${path} 的选项无效。`, path);
    return value;
  }
  function safeTree(value) {
    let nodes = 0;
    const seen = new Set();
    function walk(v, path, depth) {
      if (++nodes > 100000 || depth > 32) fail('too_complex', '工程文件的结构过于复杂。', path);
      if (v === null || typeof v === 'boolean' || typeof v === 'string') return;
      if (typeof v === 'number') { if (!Number.isFinite(v)) fail('invalid_number', '工程文件含非有限数字。', path); return; }
      if (typeof v !== 'object') fail('invalid_shape', '工程文件只接受 JSON 数据。', path);
      if (seen.has(v)) fail('invalid_shape', '工程文件不能包含循环引用。', path);
      const prototype = Object.getPrototypeOf(v);
      if (prototype !== null && prototype !== (Array.isArray(v) ? Array.prototype : Object.prototype)) fail('unsafe_shape', '工程文件包含非普通数据对象。', path);
      if (Object.getOwnPropertySymbols(v).length) fail('unsafe_shape', '工程文件不接受符号字段。', path);
      seen.add(v);
      const descriptors = Object.getOwnPropertyDescriptors(v);
      if (Array.isArray(v)) {
        if (v.length > 100000) fail('too_complex', '工程数组过长。', path);
        for (let i = 0; i < v.length; i++) if (!own(descriptors, String(i))) fail('invalid_shape', '工程数组不能有空位。', path);
      }
      for (const [key, descriptor] of Object.entries(descriptors)) {
        if (Array.isArray(v) && key === 'length') continue;
        if (FORBIDDEN.has(key)) fail('unsafe_key', '工程文件含不安全的字段。', `${path}.${key}`);
        if (own(descriptor, 'get') || own(descriptor, 'set') || !descriptor.enumerable) fail('unsafe_shape', '工程文件不接受访问器或隐藏字段。', `${path}.${key}`);
        if (Array.isArray(v) && (!/^(0|[1-9]\d*)$/.test(key) || Number(key) >= v.length)) fail('unsafe_shape', '工程数组含额外字段。', `${path}.${key}`);
        walk(descriptor.value, `${path}.${key}`, depth + 1);
      }
      seen.delete(v);
    }
    walk(value, 'project', 0);
  }
  function read(input) {
    let value = input;
    if (typeof input === 'string') {
      if (bytes(input) > MAX_BYTES) fail('file_too_large', '工程文件不能超过 8 MiB。');
      const json = input.replace(/^\uFEFF/, '');
      try { value = JSON.parse(json); }
      catch { fail('invalid_json', '文件不是有效的 JSON 工程。'); }
      rejectDuplicateKeys(json);
    }
    safeTree(value);
    if (bytes(JSON.stringify(value)) > MAX_BYTES) fail('file_too_large', '工程文件不能超过 8 MiB。');
    return value;
  }
  function rejectDuplicateKeys(json) {
    // JSON.parse keeps only the last duplicate object key. Detect duplicates
    // separately so conflicting saved selections are never silently discarded.
    let cursor = 0, nodes = 0;
    const whitespace = () => { while (/\s/.test(json[cursor] || '') && cursor < json.length) cursor++; };
    function stringToken(decode) {
      const start = cursor++;
      while (cursor < json.length) {
        if (json[cursor] === '\\') cursor += 2;
        else if (json[cursor++] === '"') return decode ? JSON.parse(json.slice(start, cursor)) : undefined;
      }
    }
    function value(depth) {
      if (++nodes > 100000 || depth > 32) fail('too_complex', '工程文件的结构过于复杂。');
      whitespace();
      if (json[cursor] === '{') {
        cursor++; whitespace(); const seen = new Set();
        if (json[cursor] === '}') { cursor++; return; }
        while (cursor < json.length) {
          const key = stringToken(true);
          if (seen.has(key)) fail('duplicate_key', '工程文件包含重复字段，不能确定应保留哪一份内容。', key);
          seen.add(key); whitespace(); cursor++; value(depth + 1); whitespace();
          if (json[cursor++] === '}') return;
          whitespace();
        }
      } else if (json[cursor] === '[') {
        cursor++; whitespace();
        if (json[cursor] === ']') { cursor++; return; }
        while (cursor < json.length) { value(depth + 1); whitespace(); if (json[cursor++] === ']') return; }
      } else if (json[cursor] === '"') stringToken(false);
      else while (cursor < json.length && !/[\s,\]}]/.test(json[cursor])) cursor++;
    }
    value(0);
  }
  const clone = value => JSON.parse(JSON.stringify(value));
  function registeredBoard(source, validateBoard, catalog) {
    const path = 'layout.board';
    keys(source, ['registeredBoardId','registeredBoardRevision','widthMm','heightMm','thicknessMm','pitchMm','edgeOffsetMm','holeType','holeDiameterMm','thread','mountingHoles','fixedOptics'], path, ['registeredBoardId','registeredBoardRevision']);
    const boardId=id(source.registeredBoardId,path+'.registeredBoardId'),revision=text(source.registeredBoardRevision,path+'.registeredBoardRevision',160,true);
    const record=(catalog?.registeredBoards||[]).find(row=>row.id===boardId);
    if(!record)fail('unknown_registered_board','工程引用的面包板未登记，请更新元件库。',path);
    if(record.revision!==revision)fail('registered_board_changed','面包板来源版本已更新；请从当前元件库重新加入，不能沿用旧孔位。',path);
    const b={registeredBoardId:boardId,registeredBoardRevision:revision,holeType:'M6_through',thread:'M6x1.0',holeDiameterMm:5};
    for(const [key,low,high] of [['widthMm',1,3000],['heightMm',1,3000],['thicknessMm',.1,100],['pitchMm',1,100],['edgeOffsetMm',0,100]])b[key]=number(record[key],path+'.'+key,low,high);
    for(const key of ['widthMm','heightMm','thicknessMm','pitchMm','edgeOffsetMm','holeType','holeDiameterMm','thread'])if(own(source,key)&&source[key]!==b[key])fail('registered_board_fixed_geometry','登记板型的外形、厚度及孔位固定，不能通过工程文件更改。',path+'.'+key);
    const allowed=record.customMountingHoles===true?record.holesMm.filter(h=>h.type==='thread'&&h.thread==='M6x1.0').map(h=>h.id):(record.mountingHoleIds||[]),available=new Set(allowed),seen=new Set();
    for(const hole of list(supplied(source,'mountingHoles',(record.mountingHoleIds||[]).map(holeId=>({holeId}))),path+'.mountingHoles',2500)){
      keys(hole,['holeId'],path+'.mountingHoles',['holeId']);
      const hid=text(hole.holeId,path+'.mountingHoles.holeId',160,true);
      if(!available.has(hid)||seen.has(hid))fail('invalid_mounting_holes','固定孔只能选源板已登记的孔，不能新增或重复。',path+'.mountingHoles');
      seen.add(hid);
    }
    b.mountingHoles=allowed.filter(holeId=>seen.has(holeId)).map(holeId=>({holeId}));
    const fixedApi=globalThis.ZZLabFixedBoardOptics||(typeof require==='function'?require('./fixed-board-optics.js'):null);Object.assign(b,fixedApi.normalizeState(source,catalog));
    if(validateBoard!==undefined){if(typeof validateBoard!=='function')fail('invalid_options','validateBoard 必须是校验函数。');let accepted;try{accepted=validateBoard(clone(b))}catch{fail('invalid_board','登记面包板未通过当前页面校验。',path)}if(!accepted)fail('invalid_board','登记面包板未通过当前页面校验。',path)}
    return b;
  }
  function board(source, validateBoard, catalog) {
    const path = 'layout.board';
    object(source,path);
    if(own(source,'registeredBoardId')||own(source,'registeredBoardRevision'))return registeredBoard(source,validateBoard,catalog);
    keys(source, ['widthMm', 'heightMm', 'pitchMm', 'edgeOffsetMm', 'thicknessMm', 'holeType', 'holeDiameterMm', 'thread', 'mountingHoles'], path, ['widthMm', 'heightMm']);
    const b = {
      widthMm: number(source.widthMm, path + '.widthMm', 25, 3000), heightMm: number(source.heightMm, path + '.heightMm', 25, 3000),
      pitchMm: number(supplied(source, 'pitchMm', 12.5), path + '.pitchMm', 1, 100), edgeOffsetMm: number(supplied(source, 'edgeOffsetMm', 12.5), path + '.edgeOffsetMm', 0, 100),
      thicknessMm: number(supplied(source, 'thicknessMm', 12.5), path + '.thicknessMm', 3, 50), holeType: choice(supplied(source, 'holeType', 'M6_through'), ['M6_through', 'plain_through'], path + '.holeType')
    };
    let nominal;
    if (b.holeType === 'M6_through') {
      b.thread = choice(supplied(source, 'thread', 'M6x1.0'), ['M6x1.0'], path + '.thread');
      b.holeDiameterMm = number(supplied(source, 'holeDiameterMm', 5), path + '.holeDiameterMm', 5, 5); nominal = 6;
    } else {
      if (own(source, 'thread') && source.thread !== null && source.thread !== '') fail('invalid_board', '普通通孔不能同时指定螺纹。', path + '.thread');
      b.thread = null; b.holeDiameterMm = number(supplied(source, 'holeDiameterMm', 6.4), path + '.holeDiameterMm', 1, 20); nominal = b.holeDiameterMm;
    }
    if (b.pitchMm < nominal + 2 || b.edgeOffsetMm < nominal / 2 + 2 || b.edgeOffsetMm > b.pitchMm || Math.min(b.widthMm, b.heightMm) < b.edgeOffsetMm * 2) fail('invalid_board', '面包板孔距或边距不符合当前孔方案。', path);
    const nx = Math.floor((b.widthMm - b.edgeOffsetMm * 2) / b.pitchMm + 1e-9) + 1;
    const ny = Math.floor((b.heightMm - b.edgeOffsetMm * 2) / b.pitchMm + 1e-9) + 1;
    if (nx * ny > 2500) fail('invalid_board', '面包板孔数超过 2500，请调整尺寸或孔距。', path);
    const expert = globalThis.ZZLAB_LOCAL_EXPERT === true;
    const holes = list(supplied(source, 'mountingHoles', []), path + '.mountingHoles', expert ? 2500 : 8);
    if (!expert && ![0, 4, 8].includes(holes.length)) fail('invalid_board', '安装沉孔必须为空、4个或8个。', path + '.mountingHoles');
    b.mountingHoles = holes.map((h, i) => {
      const hp = `${path}.mountingHoles.${i}`; keys(h, ['columnIndex', 'rowIndex'], hp, ['columnIndex', 'rowIndex']);
      return { columnIndex: integer(h.columnIndex, hp + '.columnIndex', 0, 1000000), rowIndex: integer(h.rowIndex, hp + '.rowIndex', 0, 1000000) };
    });
    const holeIds = new Set(b.mountingHoles.map(h => `${h.columnIndex},${h.rowIndex}`));
    if (holeIds.size !== holes.length) fail('invalid_board', '安装沉孔不能重复。', path + '.mountingHoles');
    // Saved holes may become physically invalid after resizing the board.
    // Preserve these editable drafts; editor/backend handle production validity.
    if (validateBoard !== undefined) {
      if (typeof validateBoard !== 'function') fail('invalid_options', 'validateBoard 必须是校验函数。');
      let accepted;
      try { accepted = validateBoard(clone(b)); } catch { fail('invalid_board', '面包板参数未通过当前页面校验。', path); }
      if (!accepted) fail('invalid_board', '面包板参数未通过当前页面校验。', path);
    }
    return b;
  }
  function environment(options) {
    if (!options?.catalog || !Array.isArray(options.catalog.kits)) fail('catalog_required', '打开工程前需要加载套件目录。');
    const kits = new Map(options.catalog.kits.map(kit => [kit.id, kit]));
    const getKit = (value, path) => { id(value, path); if (!kits.has(value)) fail('unknown_kit', `当前目录没有套件 ${value}，工程尚未导入。`, path); return kits.get(value); };
    return { kits, getKit, options };
  }
  function stamp(value, path) {
    text(value, path, 40, true);
    if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?(?:Z|[+-]\d\d:\d\d)$/.test(value) || !Number.isFinite(Date.parse(value))) fail('invalid_metadata', '工程时间格式无效。', path);
    return value;
  }
  function metadata(source, mode, options) {
    const now = options.now === undefined ? new Date().toISOString() : stamp(options.now, 'options.now');
    const m = source === undefined ? {} : source;
    keys(m, ['name', 'notes', 'createdAt', 'updatedAt', 'moduleElevation', 'opticalAxisTargetMm'], 'metadata', mode === 'project' ? ['name', 'notes', 'createdAt', 'updatedAt'] : []);
    const result = { name: text(supplied(m, 'name', '未命名光路工程'), 'metadata.name', 160, true), notes: text(supplied(m, 'notes', ''), 'metadata.notes', 20000),
      createdAt: stamp(supplied(m, 'createdAt', now), 'metadata.createdAt'), updatedAt: stamp(mode === 'create' ? now : supplied(m, 'updatedAt', now), 'metadata.updatedAt') };
    if (own(m, 'opticalAxisTargetMm')) { const h=m.opticalAxisTargetMm; if(typeof h!=='number'||!Number.isFinite(h)||h<12.5||h>1000||Math.abs(h*1000-Math.round(h*1000))>1e-8)fail('invalid_project','整体光高需为12.5–1000 mm，精确到0.001 mm。'); result.opticalAxisTargetMm=h; }
    if (own(m, 'moduleElevation')) { keys(m.moduleElevation, ['elevationMm', 'elevationSupportCount'], 'metadata.moduleElevation'); result.moduleElevation = elevationFields(m.moduleElevation, 'metadata.moduleElevation'); }
    return result;
  }
  function normalize(source, mode, options) {
    const { kits, getKit } = environment(options);
    const legacyManualUpgrade = legacyManualProject(source, options.catalog);
    const metric=typeof module==='object'&&module.exports?require('./metric-migration.js'):globalThis.ZZLabMetricMigration;
    source=metric.migrate(source,options.catalog).project;
    const wrapped = own(source, 'layout');
    const allowed = ['format', 'version', 'metadata', 'catalogVersion', 'layout', 'optical', 'extras', 'moduleQuantities', 'ui', 'catalogReferenced', 'opticalRendering', 'requires'];
    if (mode === 'legacy') allowed.push('mountingSelection', 'layoutValidation', 'boardSpecification', 'items', 'board', 'instances');
    keys(source, allowed, 'project');
    if (wrapped && (own(source, 'board') || own(source, 'instances'))) fail('conflicting_layout', '文件重复提供了两份布局，不能确定应打开哪一份。');
    if (mode === 'project') for (const field of ['metadata', 'catalogVersion', 'layout', 'optical', 'extras', 'moduleQuantities', 'ui']) if (!own(source, field)) fail('missing_field', `工程缺少 ${field}。`, field);
    const rawLayout = wrapped ? source.layout : { board: source.board, instances: source.instances };
    keys(rawLayout, ['board', 'instances', 'subBoards', 'baseMode', 'collisionOverrides', 'glassChamber'], 'layout', ['board', 'instances']);
    const layout = { board: board(rawLayout.board, options.validateBoard, options.catalog), instances: [] }, instances = new Map(), referenced = new Set();

    if(own(rawLayout,'glassChamber')){
      const g=rawLayout.glassChamber,p='layout.glassChamber';keys(g,['enabled','center','settings'],p,['enabled','center','settings']);
      if(g.enabled!==true)fail('invalid_glass','玻璃腔须显式启用；关闭时移除该字段。',p);
      keys(g.center,['x','y'],p+'.center',['x','y']);const center={x:number(g.center.x,p+'.center.x',-10000,10000),y:number(g.center.y,p+'.center.y',-10000,10000)};
      const fields=['width','length','height','wall','offsetX','offsetY','rotation','endMode','outsideIndex','insideIndex'];keys(g.settings,fields,p+'.settings',fields);const settings={};
      for(const k of ['width','length','height'])settings[k]=number(g.settings[k],p+'.settings.'+k,1,1000);
      settings.wall=number(g.settings.wall,p+'.settings.wall',.001,499);if(settings.wall*2>=Math.min(settings.width,settings.length,settings.height))fail('invalid_glass','壁厚超过腔体尺寸。',p);
      for(const k of ['offsetX','offsetY','rotation'])settings[k]=number(g.settings[k],p+'.settings.'+k,-10000,10000);
      for(const k of ['outsideIndex','insideIndex'])settings[k]=number(g.settings[k],p+'.settings.'+k,1,2);
      settings.endMode=choice(g.settings.endMode,['unknown','plus','minus','both'],p+'.settings.endMode');
      if(!rawLayout.subBoards)fail('invalid_glass','当前玻璃腔功能只支持完整多板工程。',p);
      layout.glassChamber={enabled:true,center,settings};
    }
    if(own(rawLayout,'baseMode'))layout.baseMode=choice(rawLayout.baseMode,['breadboard','table'],'layout.baseMode');
    const stageBoardIds=new Set((options.catalog.stageModules||[]).map(m=>m.runtime?.topBoardId));if(stageBoardIds.has(layout.board.registeredBoardId))fail('missing_stage_motion','位移顶板必须连同其完整位移模块导入，不能作为静态根板。','layout.board');
    const boardIds=new Set();
    if(own(rawLayout,'subBoards')){
      if(layout.baseMode!=='table'&&(![12.5,25].includes(layout.board.pitchMm)||layout.board.holeType!=='M6_through'))fail('invalid_board','承载大板须为12.5或25 mm孔距的M6螺纹板。');
      layout.subBoards=list(rawLayout.subBoards,'layout.subBoards',24).map((p,index)=>{
        const path=`layout.subBoards.${index}`;keys(p,['id','name','board','xMm','yMm','rotationDeg','elevationMm','elevationSupportCount','stageMotion'],path,['id','name','board','xMm','yMm','rotationDeg']);
        const pid=id(p.id,path+'.id');if(pid==='base'||boardIds.has(pid))fail('invalid_id','小面包板编号重复或保留。');boardIds.add(pid);
        const normalized={id:pid,name:text(p.name,path+'.name',160,true),board:board(p.board,options.validateBoard,options.catalog),xMm:number(p.xMm,path+'.xMm',-5000,10000),yMm:number(p.yMm,path+'.yMm',-5000,10000),rotationDeg:choice(p.rotationDeg,[0,90,180,270],path+'.rotationDeg'),...elevationFields(p,path)};
        if(!own(p,'stageMotion')&&stageBoardIds.has(normalized.board.registeredBoardId))fail('missing_stage_motion','位移顶板缺少完整模块的运动信息。',path);
        if(own(p,'stageMotion')){const stages=typeof module==='object'&&module.exports?require('./moving-stages.js'):globalThis.ZZLabMovingStages;try{normalized.stageMotion=stages.normalizeMotion(p.stageMotion,normalized.board,options.catalog)}catch(error){fail('invalid_stage_motion',error.message,path+'.stageMotion')}}
        return normalized;
      });
    }
    for (const [index, item] of list(rawLayout.instances, 'layout.instances', MAX_INSTANCES).entries()) {
      const path = `layout.instances.${index}`;
      keys(item, ['id', 'kitId', 'xMm', 'yMm', 'rotationDeg', 'boardId', 'elevationMm', 'elevationSupportCount', 'laserAdapter', 'optics', 'internalOptics', 'sourcePorts', 'manualMount', 'universalPostSelection'], path, mode === 'legacy' ? ['id', 'kitId', 'xMm', 'yMm'] : ['id', 'kitId', 'xMm', 'yMm', 'rotationDeg']);
      const iid = id(item.id, path + '.id');
      if (iid.includes('::') || iid.startsWith('module:')) fail('invalid_id', '实例编号不能与光学选配编号冲突。', path + '.id');
      if (instances.has(iid)) fail('duplicate_id', '画布实例编号不能重复。', path + '.id');
      const itemKit=getKit(item.kitId, path + '.kitId'); referenced.add(item.kitId);
      const normalized = { id: iid, kitId: item.kitId, xMm: number(item.xMm, path + '.xMm'), yMm: number(item.yMm, path + '.yMm'), rotationDeg: choice(supplied(item, 'rotationDeg', mode === 'legacy' ? 0 : undefined), [0, 90, 180, 270], path + '.rotationDeg') };
      if(own(item,'boardId')){if(!boardIds.has(item.boardId))fail('unknown_board','器件引用的小板不存在。');normalized.boardId=item.boardId}
      Object.assign(normalized, elevationFields(item, path), laserAdapterFields(item, path), opticsFields(item, path), internalOpticsFields(item,path,itemKit), sourcePortFields(item,path,itemKit), (typeof module==='object'&&module.exports?require('./manual-source-mount.js'):globalThis.ZZLabManualSourceMount).normalize(item,itemKit), postSelectionFields(item,path,itemKit,options.catalog));
      layout.instances.push(normalized); instances.set(iid, normalized);
    }
    if (own(rawLayout, 'collisionOverrides')) layout.collisionOverrides = collisionOverrides(rawLayout.collisionOverrides, instances);
    function slotFor(kid, sid, path) {
      const kit = getKit(kid, path); id(sid, path);
      const slot = (kit.opticalSlots || []).find(s => s.id === sid);
      if (!slot) fail('unknown_slot', `套件 ${kid} 没有选配位置 ${sid}。`, path);
      return slot;
    }
    function opticalTarget(key) {
      text(key, 'optical.key', 180, true);
      const split = key.lastIndexOf('::');
      if (split < 1) fail('invalid_optical_target', '光学选配目标格式无效。', key);
      const target = key.slice(0, split), sid = key.slice(split + 2);
      let kid;
      if (target.startsWith('module:')) {
        kid = target.slice(7);
        if (getKit(kid, key).layout?.placementAllowed !== false) fail('invalid_optical_target', '该选配目标不是独立模块。', key);
      } else {
        if (!instances.has(target)) fail('unknown_instance', '光学选配引用了不存在的实例。', key);
        kid = instances.get(target).kitId;
      }
      referenced.add(kid); return slotFor(kid, sid, key);
    }
    function selection(value, slot, path) {
      keys(value, ['model', 'wavelength', 'opticalType', 'kind', 'name', 'notes', 'unit', 'quantity', 'inserted', 'supplier'], path);
      const result = {};
      for (const [key, val] of Object.entries(value)) {
        if (key === 'inserted') { if (typeof val !== 'boolean') fail('invalid_optics', '光学片安装状态必须为布尔值。', path); result[key] = val; }
        else if (key === 'quantity') { result[key] = integer(val, path + '.' + key); if (val !== (slot.quantity || 1)) fail('invalid_optical_quantity', '光学选配数量与目录不一致。', path); }
        else if (key === 'kind') result[key] = choice(val, ['', 'lubang', 'standard'], path + '.' + key);
        else if (key === 'opticalType') { result[key] = choice(val, ['', 'half-wave', 'quarter-wave'], path + '.' + key); if (val && slot.type !== 'waveplate') fail('invalid_optical_type', '只有波片可指定半波片或四分之一波片。', path); }
        else result[key] = text(val, path + '.' + key, ({ wavelength: 80, notes: 2000, unit: 24 })[key] || 256);
      }
      return result;
    }
    const optical = {}, extras = [], extraIds = new Set(), migratedTargets = new Set();
    const rawOptical = object(supplied(source, 'optical', {}), 'optical');
    if (Object.keys(rawOptical).length > MAX_ENTRIES) fail('too_many_items', '光学选配超过 2000 项。');
    for (const [key, value] of Object.entries(rawOptical)) optical[key] = selection(value, opticalTarget(key), 'optical.' + key);
    const extraFields = ['id', 'kitId', 'kind', 'name', 'model', 'quantity', 'unit', 'notes', 'instanceId', 'slotId', 'wavelength', 'opticalType', 'inserted', 'supplier'];
    for (const [index, e] of list(supplied(source, 'extras', []), 'extras').entries()) {
      const path = `extras.${index}`; keys(e, extraFields, path, ['id', 'kitId', 'kind', 'name', 'quantity', 'unit']);
      id(e.id, path + '.id'); if (extraIds.has(e.id)) fail('duplicate_id', '补充器件编号不能重复。', path + '.id'); extraIds.add(e.id);
      const item = { id: e.id, kitId: e.kitId, kind: choice(e.kind, ['lubang', 'standard'], path + '.kind'), name: text(e.name, path + '.name', 256, true), quantity: integer(e.quantity, path + '.quantity'), unit: text(e.unit, path + '.unit', 24, true) };
      if (e.kitId !== null) { getKit(e.kitId, path + '.kitId'); referenced.add(e.kitId); }
      for (const field of ['model', 'notes', 'wavelength', 'opticalType', 'supplier']) if (own(e, field)) item[field] = text(e[field], path + '.' + field, field === 'notes' ? 2000 : field === 'wavelength' ? 80 : 256);
      if (own(e, 'inserted')) { if (typeof e.inserted !== 'boolean') fail('invalid_optics', '光学片安装状态必须为布尔值。', path); item.inserted = e.inserted; }
      if (own(e, 'instanceId')) {
        id(e.instanceId, path + '.instanceId'); const instance = instances.get(e.instanceId);
        if (!instance || instance.kitId !== e.kitId) fail('unknown_instance', '补充器件未关联到对应套件的有效实例。', path + '.instanceId');
        item.instanceId = e.instanceId;
      }
      if (own(e, 'slotId')) {
        if (e.kitId === null) fail('invalid_optical_target', '光学选配必须指定套件。', path);
        const slot = slotFor(e.kitId, e.slotId, path + '.slotId'); item.slotId = e.slotId;
        const fields = Object.fromEntries(Object.entries(item).filter(([key]) => ['model', 'wavelength', 'opticalType', 'kind', 'name', 'notes', 'unit', 'quantity', 'inserted', 'supplier'].includes(key)));
        const value = selection(fields, slot, path);
        const targets = e.instanceId ? [e.instanceId] : kits.get(e.kitId).layout?.placementAllowed === false ? [`module:${e.kitId}`] : layout.instances.filter(i => i.kitId === e.kitId).map(i => i.id);
        if (targets.length) {
          for (const target of targets) {
            const key = `${target}::${e.slotId}`;
            if (migratedTargets.has(key)) fail('duplicate_optical', '同一位置的光学选配重复。', path); migratedTargets.add(key);
            const current = optical[key] || {};
            for (const field of Object.keys(value)) if (own(current, field) && current[field] !== value[field]) fail('conflicting_optical', '工程中同一位置的光学选配内容互相冲突。', path);
            optical[key] = { ...current, ...value };
          }
          continue;
        }
        // An inactive kit-scoped optical extra remains a kit template; it is not discarded.
      } else if (own(e, 'wavelength') || own(e, 'opticalType') || own(e, 'inserted')) fail('invalid_optical_target', '波长、波片类型和安装状态必须对应光学选配位置。', path);
      extras.push(item);
    }
    if (Object.keys(optical).length > MAX_ENTRIES) fail('too_many_items', '光学选配超过 2000 项。');
    let moduleInput = list(supplied(source, 'moduleQuantities', []), 'moduleQuantities');
    if (mode === 'legacy' && own(source, 'items')) {
      const old = list(source.items, 'items');
      if (old.length) {
        if (moduleInput.length) fail('conflicting_modules', '工程重复提供模块数量。');
        moduleInput = old.map((row, i) => { keys(row, ['kitId', 'quantity'], `items.${i}`, ['kitId', 'quantity']); return [row.kitId, row.quantity]; });
      }
    }
    const moduleIds = new Set(), moduleQuantities = list(moduleInput, 'moduleQuantities').map((pair, index) => {
      const path = `moduleQuantities.${index}`; if (!Array.isArray(pair) || pair.length !== 2) fail('invalid_shape', '模块数量应为 [套件编号, 数量]。', path);
      if (getKit(pair[0], path).layout?.placementAllowed !== false) fail('invalid_module', '整套数量只用于独立模块。', path);
      if (moduleIds.has(pair[0])) fail('duplicate_id', '独立模块数量不能重复。', path); moduleIds.add(pair[0]); referenced.add(pair[0]);
      return [pair[0], integer(pair[1], path + '.quantity')];
    });
    const rawUI = supplied(source, 'ui', {}); keys(rawUI, ['mountingSelection', 'view', 'selectedIds'], 'ui');
    if (mode === 'legacy' && own(source, 'mountingSelection') && own(rawUI, 'mountingSelection')) {
      keys(source.mountingSelection, ['rowParity', 'columnParity'], 'mountingSelection', ['rowParity', 'columnParity']);
      object(rawUI.mountingSelection, 'ui.mountingSelection');
      if (['rowParity', 'columnParity'].some(field => source.mountingSelection[field] !== rawUI.mountingSelection[field])) fail('conflicting_ui', '文件内的安装孔行列选项相互冲突。');
    }
    const mounting = supplied(rawUI, 'mountingSelection', mode === 'legacy' ? supplied(source, 'mountingSelection', { rowParity: 'any', columnParity: 'any' }) : { rowParity: 'any', columnParity: 'any' });
    keys(mounting, ['rowParity', 'columnParity'], 'ui.mountingSelection', ['rowParity', 'columnParity']);
    const ui = { mountingSelection: { rowParity: choice(mounting.rowParity, ['any', 'odd', 'even'], 'ui.mountingSelection.rowParity'), columnParity: choice(mounting.columnParity, ['any', 'odd', 'even'], 'ui.mountingSelection.columnParity') }, view: null, selectedIds: [] };
    if (rawUI.view !== null && rawUI.view !== undefined) {
      keys(rawUI.view, ['x', 'y', 'w', 'h'], 'ui.view', ['x', 'y', 'w', 'h']);
      ui.view = Object.fromEntries(['x', 'y', 'w', 'h'].map(field => [field, number(rawUI.view[field], 'ui.view.' + field, field === 'w' || field === 'h' ? 0.001 : -1e7, 1e7)]));
    }
    const selected = new Set();
    for (const iid of list(supplied(rawUI, 'selectedIds', []), 'ui.selectedIds', MAX_INSTANCES)) {
      id(iid, 'ui.selectedIds'); if (!instances.has(iid)) fail('unknown_instance', '选中状态引用了不存在的实例。', 'ui.selectedIds');
      if (selected.has(iid)) fail('duplicate_id', '选中实例不能重复。', 'ui.selectedIds'); selected.add(iid); ui.selectedIds.push(iid);
    }
    if (own(source, 'catalogReferenced')) for (const ref of list(source.catalogReferenced, 'catalogReferenced')) { keys(ref, ['id', 'name'], 'catalogReferenced', ['id', 'name']); getKit(ref.id, 'catalogReferenced.id'); text(ref.name, 'catalogReferenced.name', 256, true); }
    const requirements = own(source, 'requires') ? list(source.requires, 'requires', 8) : [];
    if (requirements.some(v => !SUPPORTED_CAPABILITIES.includes(v)) || new Set(requirements).size !== requirements.length) fail('unsupported_capability', '工程要求的交互能力不受支持。', 'requires');
    const needed = [layout.instances.some(i=>i.optics?.dichroic?.zeroOrderPreview) ? 'zzlab-zero-order-routing-v1' : null, layout.instances.some(i=>i.optics?.elementType==='aom') ? 'zzlab-aom-diffraction-v1' : null, layout.glassChamber ? 'zzlab-glass-chamber-v1' : null, layout.subBoards?.some(p => p.stageMotion) ? STAGE_CAPABILITY : null, layout.collisionOverrides?.length ? COLLISION_CAPABILITY : null, layout.instances.some(i=>own(i,'manualMount')||options.catalog.kits.some(k=>k.id===i.kitId&&k.layout?.manualMountingPolicy)) ? MANUAL_SOURCE_CAPABILITY : null].filter(Boolean);
    for (const capability of needed) if (mode !== 'create' && !requirements.includes(capability) && !(capability === MANUAL_SOURCE_CAPABILITY && legacyManualUpgrade)) fail('missing_capability', `工程必须声明 ${capability}。`, 'requires');
    const normalizedRequirements = SUPPORTED_CAPABILITIES.filter(value => requirements.includes(value) || needed.includes(value));
    const result = { format: FORMAT, version: VERSION, ...(normalizedRequirements.length ? { requires: normalizedRequirements } : {}), metadata: metadata(source.metadata, mode, options), catalogVersion: text(legacyManualUpgrade ? options.catalog.version : supplied(source, 'catalogVersion', options.catalog.version || ''), 'catalogVersion', 128), layout, optical, extras, moduleQuantities, ui,
      catalogReferenced: [...referenced].sort().map(kid => ({ id: kid, name: text(kits.get(kid).name || kid, 'catalog.name', 256, true) })) };
    if (own(source, 'opticalRendering')) {
      const fields = ['generated', 'visible', 'autoRestore'];
      keys(source.opticalRendering, fields, 'opticalRendering', fields);
      result.opticalRendering = {};
      for (const key of fields) {
        if (typeof source.opticalRendering[key] !== 'boolean') fail('invalid_optics', '光路恢复与显示偏好必须为布尔值。', 'opticalRendering.' + key);
        result.opticalRendering[key] = source.opticalRendering[key];
      }
    }
    if (bytes(JSON.stringify(result)) > MAX_BYTES) fail('file_too_large', '工程文件不能超过 8 MiB。');
    return result;
  }
  function create(input, options = {}) {
    const value = read(input); object(value, 'project');
    if (own(value, 'format') && value.format !== FORMAT) fail('unsupported_format', '不是支持的 ZZLab 工程格式。');
    if (own(value, 'version') && value.version !== VERSION) fail('unsupported_version', '工程版本暂不支持。');
    return normalize(value, 'create', options);
  }
  function parse(input, options = {}) {
    const value = read(input); object(value, 'project');
    const legacy = !own(value, 'format');
    if (!legacy && value.format !== FORMAT) fail('unsupported_format', '不是支持的 ZZLab 工程格式。');
    if (!legacy && value.version !== VERSION) fail('unsupported_version', '工程版本暂不支持，请使用兼容版本打开。');
    if (legacy && own(value, 'version') && value.version !== 2) fail('unsupported_version', '旧布局文件版本暂不支持。');
    const project = normalize(value, legacy ? 'legacy' : 'project', options), warnings = [];
    if (value.catalogVersion && options.catalog?.version && value.catalogVersion !== options.catalog.version) warnings.push('工程来自不同版本的套件目录；材料、模型和采购组成将使用当前目录重新核对。');
    if (legacyManualProject(value, options.catalog)) warnings.push('旧935实例的位置和出光设置已载入；实际板面光高仍需人工安装确认。重新保存后工程将要求手动安装能力。');
    return { project, legacy, warnings };
  }
  return Object.freeze({ FORMAT, VERSION, EXTENSION, MAX_BYTES, MAX_INSTANCES, MAX_COLLISION_OVERRIDES, ProjectFileError, create, parse });
});
