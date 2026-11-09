(function(root){'use strict';
 const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k),finite=v=>typeof v==='number'&&Number.isFinite(v);
 function reference(g){const p=g?.manualMountingPolicy,r=g?.sourceAlignmentReference;if(p===undefined&&r===undefined)return null;
  if(!p||p.version!==1||p.mode!=='user-support-and-clamp'||Object.keys(p).some(k=>!['version','mode','targetAxisHeightMm'].includes(k))||own(p,'targetAxisHeightMm')&&(!finite(p.targetAxisHeightMm)||p.targetAxisHeightMm<0||p.targetAxisHeightMm>10000))throw Error('人工光源安装协议无效。');
  if(g.opticalType!=='source'||g.opticalAssembly||g.mountingConfirmed!==false||!Array.isArray(g.mountingHoleOffsetsMm)||g.mountingHoleOffsetsMm.length||g.opticalAxisHeightMm!=null||g.opticalDatumVerified!==false)throw Error('人工支撑光源需保留未知板面高度和未验证安装孔状态。');
  const port=g.opticalPortsMm?.length===1?g.opticalPortsMm[0]:null;
  if(!r||r.version!==1||Object.keys(r).some(k=>!['version','portId'].includes(k))||!port||r.portId!==port.id||!['xMm','yMm','directionX','directionY'].every(k=>finite(port[k]))||Math.hypot(port.directionX,port.directionY)<1e-9)throw Error('人工光源需要固定唯一主光口XY参考。');return port;
 }
 function normalize(instance,kit){const port=reference(kit?.layout);if(port&&(instance.laserAdapter?.enabled===true||(instance.elevationMm??0)!==0||own(instance,'universalPostSelection')))throw Error('人工支撑不叠加自动底座、换柱或器件抬高。');if(!own(instance,'manualMount'))return{};if(kit?.category!=='laser'||!port)throw Error('此元件不接受人工光源安装声明。');const v=instance.manualMount;
  if(!v||typeof v!=='object'||Array.isArray(v)||!['version','confirmed','nominalOutputReferenceAccepted'].every(k=>own(v,k))||Object.keys(v).some(k=>!['version','confirmed','nominalOutputReferenceAccepted','axisHeightMm'].includes(k))||v.version!==1||typeof v.confirmed!=='boolean'||typeof v.nominalOutputReferenceAccepted!=='boolean')throw Error('人工安装仅允许版本、两项确认和用户声明轴高。');
  const value={version:1,confirmed:v.confirmed,nominalOutputReferenceAccepted:v.nominalOutputReferenceAccepted};if(own(v,'axisHeightMm')){if(!finite(v.axisHeightMm)||v.axisHeightMm<0||v.axisHeightMm>10000)throw Error('手调光轴高需明确填写板面起0–10000mm的有限数字。');value.axisHeightMm=Math.round(v.axisHeightMm*1e6)/1e6;}
  if(value.confirmed&&(!own(value,'axisHeightMm')||!value.nominalOutputReferenceAccepted))throw Error('确认前需填写手调光高并接受名义出光参考平面。');return{manualMount:value};
 }
 function acceptedHeight(instance,g){if(!reference(g))return null;const v=instance?.manualMount;return v?.version===1&&v.confirmed===true&&v.nominalOutputReferenceAccepted===true&&finite(v.axisHeightMm)&&v.axisHeightMm>=0&&v.axisHeightMm<=10000?v.axisHeightMm:null;}
 function offsets(g,angle){const p=reference(g);if(!p)return null;const a=angle*Math.PI/180,c=Math.round(Math.cos(a)),s=Math.round(Math.sin(a));return[{xMm:c*p.xMm-s*p.yMm,yMm:s*p.xMm+c*p.yMm}];}
 const api={reference,normalize,acceptedHeight,offsets};root.ZZLabManualSourceMount=api;if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
