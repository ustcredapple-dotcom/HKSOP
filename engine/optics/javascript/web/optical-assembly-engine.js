/* Pure 3-D geometry and polarization-basis helpers. No scene or tracing state. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ZZLabOpticalAssemblyEngine = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  const EPS = 1e-7, ANGULAR_EPS = 1e-12, DEG = Math.PI / 180;
  const finite = (v, label) => {
    if (typeof v !== 'number' || !Number.isFinite(v)) throw new TypeError(`${label} must be a finite number`);
    return v;
  };
  const clean = v => Math.abs(v) < 1e-14 ? 0 : v;
  function vec3(value, label = 'vector') {
    if (!value || typeof value !== 'object') throw new TypeError(`${label} must be a 3-D vector`);
    if (Array.isArray(value)) {
      if (value.length !== 3) throw new TypeError(`${label} must contain exactly three coordinates`);
      return {x:finite(value[0], `${label}.x`), y:finite(value[1], `${label}.y`), z:finite(value[2], `${label}.z`)};
    }
    return {x:finite(value.x, `${label}.x`), y:finite(value.y, `${label}.y`), z:finite(value.z, `${label}.z`)};
  }
  function add3(a, b) { a=vec3(a); b=vec3(b); return {x:a.x+b.x,y:a.y+b.y,z:a.z+b.z}; }
  function sub3(a, b) { a=vec3(a); b=vec3(b); return {x:a.x-b.x,y:a.y-b.y,z:a.z-b.z}; }
  function scale3(a, k) { a=vec3(a); finite(k,'scale'); return {x:a.x*k,y:a.y*k,z:a.z*k}; }
  function dot3(a, b) { a=vec3(a); b=vec3(b); return a.x*b.x+a.y*b.y+a.z*b.z; }
  function cross3(a, b) { a=vec3(a); b=vec3(b); return {x:a.y*b.z-a.z*b.y,y:a.z*b.x-a.x*b.z,z:a.x*b.y-a.y*b.x}; }
  function norm3(a) { a=vec3(a); return Math.hypot(a.x,a.y,a.z); }
  function normalize3(a) {
    a=vec3(a); const length=norm3(a);
    if (!Number.isFinite(length) || length < ANGULAR_EPS) throw new TypeError('Cannot normalize a zero or overflowing vector');
    return {x:clean(a.x/length),y:clean(a.y/length),z:clean(a.z/length)};
  }
  function positive(value,label) {
    finite(value,label);
    if (value <= 0) throw new TypeError(`${label} must be positive`);
    return value;
  }
  function normalizeBounds(input) {
    if (!input || typeof input !== 'object') throw new TypeError('3-D bounds are required');
    const min=vec3(input.min,'bounds.min'),max=vec3(input.max,'bounds.max');
    if (['x','y','z'].some(k=>min[k]>=max[k])) throw new TypeError('Each 3-D bound maximum must exceed its minimum');
    return {min,max};
  }
  function normalizeAssembly(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('Assembly must be an object');
    const version=input.version===undefined?1:input.version;
    if (![1,2,3,4].includes(version)) throw new TypeError('Unsupported optical assembly version');
    if(version===1&&input.emissionNodeId!==undefined)throw new TypeError('emissionNodeId requires optical assembly version 2');
    if (!Array.isArray(input.nodes) || input.nodes.length > 256) throw new TypeError('Assembly nodes must be an array of at most 256 nodes');
    const ids=new Set();
    const nodes=input.nodes.map((node,index)=>{
      if (!node || typeof node !== 'object') throw new TypeError(`Invalid assembly node ${index}`);
      if (typeof node.id !== 'string' || !node.id.trim() || node.id.length > 128 || ids.has(node.id)) throw new TypeError('Assembly node ids must be nonempty and unique');
      ids.add(node.id);
      if (!(version===4?['lens','mirror','dichroic','objective','waveplate']:version>=2?['mirror','dichroic','objective','waveplate','coupler']:['mirror','dichroic','objective']).includes(node.type)) throw new TypeError(`Unsupported assembly node type: ${node.type}`);
      if (node.geometryConfirmed !== undefined && typeof node.geometryConfirmed !== 'boolean') throw new TypeError('geometryConfirmed must be boolean');
      if(version>=2&&typeof node.geometryConfirmed!=='boolean')throw new TypeError('v2 node geometryConfirmed must be explicit');
      const centerMm=vec3(node.centerMm,`${node.id}.centerMm`),normal=normalize3(node.normal);
      const radiusMm=positive(node.radiusMm,`${node.id}.radiusMm`);
      if(node.mechanicalClearRadiusMm!==undefined&&(positive(node.mechanicalClearRadiusMm,'mechanicalClearRadiusMm')>radiusMm+EPS))throw new TypeError('Mechanical clear radius cannot exceed the registered optic outer radius');
      if (!Array.isArray(node.faces) || node.faces.length > 16) throw new TypeError(`Node ${node.id} faces must be an array of at most 16 faces`);
      const faces=node.faces.map((face,i)=>{
        if (!face || typeof face !== 'object') throw new TypeError(`Invalid face ${node.id}.${i}`);
        return {...face,centerMm:vec3(face.centerMm,`${node.id}.faces.${i}.centerMm`),normal:normalize3(face.normal),
          radiusMm:face.radiusMm===undefined?radiusMm:positive(face.radiusMm,`${node.id}.faces.${i}.radiusMm`)};
      });
      if(version>=2&&['lens','waveplate','coupler'].includes(node.type)){
        if(Math.abs(normal.z)>EPS||faces.length!==1||norm3(sub3(centerMm,faces[0].centerMm))>EPS||Math.abs(dot3(normal,faces[0].normal)-1)>EPS)throw new TypeError('v2 waveplate/coupler requires one registered thin plane and a horizontal nominal forward normal');
        if(node.halfAngleDeg!==undefined&&(typeof node.halfAngleDeg!=='number'||!Number.isFinite(node.halfAngleDeg)||node.halfAngleDeg<0||node.halfAngleDeg>15))throw new TypeError('v2 port halfAngleDeg must be between 0 and 15 degrees');
      }
      return {...node,centerMm,normal,radiusMm,faces,geometryConfirmed:node.geometryConfirmed===true};
    });
    if(version>=2){
      if(typeof input.verified!=='boolean')throw new TypeError('v2 assembly verified must be explicit');
      const port=nodes.find(n=>n.id===input.emissionNodeId);
      if(version>=3&&(input.emissionNodeId!==undefined||nodes.some(n=>n.type==='coupler')))throw new TypeError('Passive assembly cannot declare an emitter');
      if(version===2&&(!port||port.type!=='coupler'||nodes.filter(n=>n.type==='coupler').length!==1))throw new TypeError('v2 assembly requires emissionNodeId referencing its single coupler port');
      if((input.internalElements||[]).some(n=>['source','coupler'].includes(n.type)))throw new TypeError('v2 coupler port is read-only; source settings belong to the parent instance');
      const internals=input.internalElements||[],seen=new Set(),slots=new Set();
      if(!Array.isArray(internals)||internals.length>16)throw new TypeError('v2 internalElements needs at most 16 registered settings');
      for(const row of internals){const n=nodes.find(n=>n.id===row.id);if(!n||n.type!==row.type||seen.has(row.id)||row.opticalDefaults?.source?.enabled)throw new TypeError('v2 internal settings must match registered non-emitting nodes');seen.add(row.id);if(['lens','waveplate'].includes(row.type)){if(typeof row.slotId!=='string'||!row.slotId.trim()||slots.has(row.slotId))throw new TypeError('v2 waveplates require independent slots');slots.add(row.slotId);}}
      if(nodes.some(n=>['lens','waveplate'].includes(n.type)&&!seen.has(n.id)))throw new TypeError('v2 waveplate node requires registered internal settings');
    }
    return {...input,nodes,bounds:normalizeBounds(input.bounds)};
  }
  function reflect3(direction,normal) {
    const d=normalize3(direction),n=normalize3(normal);
    return normalize3(sub3(d,scale3(n,2*dot3(d,n))));
  }
  function rayHit(origin,direction,node,faceIndex=null) {
    const o=vec3(origin),d=normalize3(direction);
    if (!node || !Array.isArray(node.faces)) throw new TypeError('Ray target requires explicit mechanical faces');
    if (faceIndex!==null && (!Number.isInteger(faceIndex) || faceIndex<0 || faceIndex>=node.faces.length)) throw new TypeError('Invalid selected face index');
    const candidates=faceIndex===null?node.faces.map((face,index)=>({face,index})):[{face:node.faces[faceIndex],index:faceIndex}];
    let nearest=null;
    for (const {face,index} of candidates) {
      const center=vec3(face.centerMm),n=normalize3(face.normal),den=dot3(d,n);
      if (Math.abs(den)<ANGULAR_EPS) continue;
      const distanceMm=dot3(sub3(center,o),n)/den;
      if (distanceMm<=EPS) continue;
      const point=add3(o,scale3(d,distanceMm)),delta=sub3(point,center);
      // Remove the tiny normal residual before testing the circular aperture.
      const inPlane=sub3(delta,scale3(n,dot3(delta,n))),offsetMm=norm3(inPlane);
      const radius=Math.min(positive(face.radiusMm===undefined?node.radiusMm:face.radiusMm,'Face radius'),node.mechanicalClearRadiusMm??Infinity);
      if (offsetMm>radius+EPS) continue;
      const hit={distanceMm,point,offsetMm,faceIndex:index,normal:n,requiresFaceSelection:faceIndex===null};
      if (!nearest || distanceMm<nearest.distanceMm) nearest=hit;
    }
    return nearest;
  }
  function placementValues(placement={}) {
    return {
      x:placement.xMm===undefined?0:finite(placement.xMm,'placement.xMm'),
      y:placement.yMm===undefined?0:finite(placement.yMm,'placement.yMm'),
      z:placement.zMm===undefined?0:finite(placement.zMm,'placement.zMm'),
      angle:(placement.rotationDeg===undefined?0:finite(placement.rotationDeg,'placement.rotationDeg'))*DEG
    };
  }
  function rotateZ(vector,angle) {
    const v=vec3(vector),c=Math.cos(angle),s=Math.sin(angle);
    return {x:clean(c*v.x-s*v.y),y:clean(s*v.x+c*v.y),z:v.z};
  }
  function localToWorldPoint(point,placement={}) {
    const p=placementValues(placement);
    return add3(rotateZ(point,p.angle),p);
  }
  function worldToLocalPoint(point,placement={}) {
    const p=placementValues(placement);
    return rotateZ(sub3(point,p),-p.angle);
  }
  function localToWorldDirection(direction,placement={}) { return rotateZ(direction,placementValues(placement).angle); }
  function worldToLocalDirection(direction,placement={}) { return rotateZ(direction,-placementValues(placement).angle); }
  function transverse(vector,direction,label='Polarization reference') {
    const v=vec3(vector),d=normalize3(direction),p=sub3(v,scale3(d,dot3(v,d)));
    if (norm3(p)<ANGULAR_EPS) throw new TypeError(`${label} is parallel to propagation`);
    return normalize3(p);
  }
  function fallbackS(direction) {
    const d=normalize3(direction),axes=[{x:1,y:0,z:0},{x:0,y:1,z:0},{x:0,y:0,z:1}];
    axes.sort((a,b)=>Math.abs(dot3(a,d))-Math.abs(dot3(b,d)));
    return transverse(axes[0],d);
  }
  function incidenceBasis(direction,normal,referenceS) {
    const d=normalize3(direction),n=normalize3(normal);
    let reference=null;
    if (referenceS!==undefined && referenceS!==null) {
      const raw=vec3(referenceS),projected=sub3(raw,scale3(d,dot3(raw,d)));
      if (norm3(projected)>=ANGULAR_EPS) reference=normalize3(projected);
    }
    let s=cross3(n,d);
    if (norm3(s)<ANGULAR_EPS) s=reference||fallbackS(d);
    else {
      s=normalize3(s);
      if (reference && dot3(s,reference)<0) s=scale3(s,-1);
    }
    return {s,p:normalize3(cross3(s,d)),angleDeg:Math.acos(Math.min(1,Math.abs(dot3(d,n))))/DEG};
  }
  function rotateStokes(stokes,direction,fromS,toS) {
    if (!stokes || typeof stokes!=='object') throw new TypeError('Stokes vector required');
    const d=normalize3(direction),a=transverse(fromS,d),b=transverse(toS,d);
    const oldP=cross3(a,d),newP=cross3(b,d);
    // Both frames use (P=S×k,S,k). Coordinate transform is
    // E'_p=c E_p+s E_s; E'_s=-s E_p+c E_s (proper basis rotation).
    // Therefore only Q/U rotate. A handedness flip here would be incorrect.
    const c=dot3(newP,oldP),s=dot3(newP,a),cos2=c*c-s*s,sin2=2*c*s;
    const s0=stokes.s0===undefined?1:finite(stokes.s0,'stokes.s0'),s1=finite(stokes.s1,'stokes.s1'),s2=finite(stokes.s2,'stokes.s2'),s3=finite(stokes.s3,'stokes.s3');
    return {...stokes,s0,s1:clean(cos2*s1+sin2*s2),s2:clean(-sin2*s1+cos2*s2),s3};
  }
  function boxExit(point,direction,bounds) {
    const o=vec3(point),d=normalize3(direction),b=normalizeBounds(bounds);
    let near=-Infinity,far=Infinity;
    for (const k of ['x','y','z']) {
      if (Math.abs(d[k])<ANGULAR_EPS) {
        if (o[k]<b.min[k]-EPS || o[k]>b.max[k]+EPS) return null;
      } else {
        const t1=(b.min[k]-o[k])/d[k],t2=(b.max[k]-o[k])/d[k];
        near=Math.max(near,Math.min(t1,t2));far=Math.min(far,Math.max(t1,t2));
        if (far<near-EPS) return null;
      }
    }
    if (!Number.isFinite(far) || far<=EPS) return null;
    return {distanceMm:far,point:add3(o,scale3(d,far))};
  }
  function sidePoint(point) { const p=vec3(point); return {x:p.x,y:p.z}; }
  return Object.freeze({EPS,vec3,add3,sub3,scale3,dot3,cross3,norm3,normalize3,
    normalizeAssembly,rayHit,reflect3,localToWorldPoint,worldToLocalPoint,
    localToWorldDirection,worldToLocalDirection,incidenceBasis,rotateStokes,boxExit,sidePoint});
});
