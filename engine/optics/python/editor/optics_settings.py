"""Data-only ray-rendering parameters shared by layouts, projects and cart snapshots.

The catalog remains the authority for geometry, assets and purchase parts. These
settings describe optical simulation parameters and never replace a BOM row.
Missing settings stay absent so older projects retain their original data.
"""
from __future__ import annotations

import math
import re

from bom import APIError

ELEMENT_TYPES = {"empty", "mirror", "dichroic", "pbs", "waveplate", "lens", "coupler", "source", "unsupported", "aom"}
POLARIZATION_TYPES = {"linear", "circular-left", "circular-right", "elliptical", "unpolarized"}
OPTICS_FIELDS = {"elementType", "inserted", "configured", "surfaceAngleDeg", "pbsHandedness", "fastAxisDeg",
                 "retardanceDeg", "designWavelengthNm", "focalLengthMm", "clearApertureMm", "source", "waveplates", "mirror", "dichroic", "aom"}
SOURCE_FIELDS = {"enabled", "wavelengthNm", "powerMw", "beamDiameterMm", "polarizationType",
                 "polarizationAngleDeg", "ellipticityDeg", "wavefrontRadiusMm", "beamQualityM2", "directionAngleDeg"}
SOURCE_PORT_FIELDS = SOURCE_FIELDS - {"directionAngleDeg"}
SOURCE_PORT_REQUIRED = {"wavelengthNm", "powerMw", "beamDiameterMm", "beamQualityM2", "polarizationType", "wavefrontRadiusMm"}
SOURCE_PORT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
WAVEPLATE_FIELDS = {"inserted", "fastAxisDeg", "retardanceDeg", "designWavelengthNm"}
MIRROR_FIELDS = {"mode", "model", "samples"}
MIRROR_SAMPLE_RANGES = {"wavelengthNm": (1, 1e6), "incidenceAngleDeg": (0, 90),
                        "reflectanceP": (0, 1), "reflectanceS": (0, 1),
                        "phaseDifferenceDeg": (-36000, 36000)}
DICHROIC_SAMPLE_RANGES = {"wavelengthNm": (1, 1e6), "incidenceAngleDeg": (0, 90),
    "reflectanceP": (0, 1), "reflectanceS": (0, 1), "transmittanceP": (0, 1), "transmittanceS": (0, 1),
    "reflectionPhaseDifferenceDeg": (-36000, 36000), "transmissionPhaseDifferenceDeg": (-36000, 36000)}
RANGES = {"surfaceAngleDeg": (-3600, 3600), "fastAxisDeg": (-3600, 3600),
          "retardanceDeg": (-36000, 36000), "designWavelengthNm": (1, 1e6),
          "clearApertureMm": (1e-6, 1e4), "wavelengthNm": (1, 1e6), "powerMw": (0, 1e9),
          "beamDiameterMm": (1e-6, 1e4), "polarizationAngleDeg": (-3600, 3600),
          "ellipticityDeg": (-45, 45), "beamQualityM2": (1, 100), "directionAngleDeg": (-3600, 3600)}


def invalid(label):
    raise APIError("invalid_optics", f"光路渲染参数无效：{label}。")


def shape(value, allowed, required, label):
    if not isinstance(value, dict) or set(value) - allowed or not required <= set(value):
        invalid(f"{label}缺少必要字段或包含未知字段")


def numeric(value, key):
    lower, upper = RANGES[key]
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        invalid(f"{key} 必须是 {lower:g} 至 {upper:g} 的有限数字")
    return value


def nullable_nonzero(value, key, maximum):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 1e-6 <= abs(value) <= maximum:
        invalid(f"{key} 必须为空值或绝对值在 0.000001 至 {maximum:g} 之间的有限数字")
    return value


def boolean(value, key):
    if type(value) is not bool:
        invalid(f"{key} 必须为布尔值")
    return value


def waveplate(value):
    shape(value, WAVEPLATE_FIELDS, {"inserted"}, "波片")
    return {key: boolean(val, key) if key == "inserted" else numeric(val, key) for key, val in value.items()}


def mirror(value):
    shape(value, MIRROR_FIELDS, {"mode", "samples"}, "反射镜镀膜")
    if value["mode"] not in ("ideal", "data"):
        invalid("反射镜计算模式应为 ideal 或 data")
    result = {"mode": value["mode"]}
    if "model" in value:
        if (not isinstance(value["model"], str) or len(value["model"]) > 160
                or any(ord(ch) < 32 and ch not in '\t\n\r' or ord(ch) == 127 for ch in value["model"])):
            invalid("反射镜系数绑定型号应为最多160字的字符串")
        result["model"] = value["model"]
    if "samples" in value:
        if not isinstance(value["samples"], list) or len(value["samples"]) > 256:
            invalid("反射镜系数表应为最多256项的数组")
        samples, seen = [], set()
        for sample in value["samples"]:
            shape(sample, set(MIRROR_SAMPLE_RANGES), set(MIRROR_SAMPLE_RANGES), "反射镜系数点")
            row = {}
            for key, (lower, upper) in MIRROR_SAMPLE_RANGES.items():
                val = sample[key]
                if val is None and key in ("reflectanceP", "reflectanceS", "phaseDifferenceDeg"):
                    row[key] = None
                elif type(val) not in (int, float) or not math.isfinite(val) or not lower <= val <= upper:
                    invalid(f"反射镜 {key} 必须是 {lower:g} 至 {upper:g} 的有限数字")
                else:
                    row[key] = val
            point = (row["wavelengthNm"], row["incidenceAngleDeg"])
            if point in seen:
                invalid("反射镜系数表不能在同一波长及入射角重复登记")
            seen.add(point)
            samples.append(row)
        result["samples"] = samples
    return result


def dichroic(value):
    """Exact measured data only; unavailable polarization coefficients stay null."""
    shape(value, MIRROR_FIELDS | {"zeroOrderPreview"}, {"mode", "samples"}, "双色镜镀膜")
    if value['mode'] != 'data': invalid('双色镜计算模式应为 data')
    result={'mode':'data'}
    if 'zeroOrderPreview' in value:
        v=value['zeroOrderPreview']; fields={'version','wavelengthNm','referenceAngleDeg','maxAngleDeviationDeg','output'}
        shape(v,fields,fields,'零级几何预览')
        if type(v['version']) is not int or v['version']!=1 or v['output'] not in ('reflected','transmitted'):invalid('不支持的零级几何预览版本或方向')
        for k,lo,hi in [('wavelengthNm',1,1e6),('referenceAngleDeg',0,90),('maxAngleDeviationDeg',.000001,5)]:
            if type(v[k]) not in (int,float) or not math.isfinite(v[k]) or not lo<=v[k]<=hi:invalid('零级几何预览参数超出范围')
        result['zeroOrderPreview']=dict(v)
    if 'model' in value:
        label=value['model']
        if not isinstance(label,str) or len(label)>160 or any(ord(ch)<32 and ch not in '\t\n\r' or ord(ch)==127 for ch in label):
            invalid('双色镜系数绑定型号应为最多160字的字符串')
        result['model']=label
    if not isinstance(value['samples'],list) or len(value['samples'])>256: invalid('双色镜系数表应为最多256项的数组')
    result['samples']=[];seen=set()
    for sample in value['samples']:
        shape(sample,set(DICHROIC_SAMPLE_RANGES),set(DICHROIC_SAMPLE_RANGES),'双色镜系数点')
        row={}
        for key,(lower,upper) in DICHROIC_SAMPLE_RANGES.items():
            val=sample[key]
            if val is None and key not in ('wavelengthNm','incidenceAngleDeg'):row[key]=None
            elif type(val) not in (int,float) or not math.isfinite(val) or not lower<=val<=upper:invalid(f'双色镜 {key} 超出有限数字范围')
            else:row[key]=val
        for polarization in ('P','S'):
            r,t=row['reflectance'+polarization],row['transmittance'+polarization]
            if r is not None and t is not None and r+t>1+1e-9:invalid('双色镜同偏振反射率与透射率之和不能大于1')
        point=(row['wavelengthNm'],row['incidenceAngleDeg'])
        if point in seen:invalid('双色镜系数表不能在同一波长及入射角重复登记')
        seen.add(point);result['samples'].append(row)
    return result


def aom(value):
    fields = {"version", "angleMrad", "referenceWavelengthNm", "rfMHz", "awayLocalDeg", "powerMode", "nominalDatumAccepted"}
    shape(value, fields, fields, "AOM")
    if type(value["version"]) is not int or value["version"] != 1 or value["powerMode"] != "geometry-only" or value["nominalDatumAccepted"] is not True: invalid("AOM名义几何配置无效")
    for key, (lo, hi) in {"angleMrad": (1e-6,100), "referenceWavelengthNm": (1,1e6), "rfMHz": (.001,10000), "awayLocalDeg": (-3600,3600)}.items():
        v=value[key]
        if type(v) not in (int,float) or not math.isfinite(v) or not lo <= v <= hi: invalid("AOM参数无效："+key)
    return dict(value)


def normalize_optics(value):
    """Return a fresh, nested-data-independent optics object; do not fill defaults."""
    shape(value, OPTICS_FIELDS, {"elementType", "inserted"}, "器件")
    if not isinstance(value["elementType"], str) or value["elementType"] not in ELEMENT_TYPES:
        invalid("光学元件类型未登记")
    result = {"elementType": value["elementType"], "inserted": boolean(value["inserted"], "inserted")}
    if "aom" in value:
        if value["elementType"] != "aom": invalid("AOM配置只适用于aom类型")
        result["aom"] = aom(value["aom"])
    if "configured" in value:
        result["configured"] = boolean(value["configured"], "configured")
    for key in OPTICS_FIELDS & RANGES.keys():
        if key in value:
            result[key] = numeric(value[key], key)
    if "pbsHandedness" in value:
        if value["pbsHandedness"] not in ("left", "right"):
            invalid("PBS 晶体朝向应为 left 或 right")
        result["pbsHandedness"] = value["pbsHandedness"]
    if "focalLengthMm" in value:
        result["focalLengthMm"] = nullable_nonzero(value["focalLengthMm"], "focalLengthMm", 1e6)
    if "waveplates" in value:
        if not isinstance(value["waveplates"], list) or len(value["waveplates"]) > 8:
            invalid("波片应为最多 8 项的数组")
        result["waveplates"] = [waveplate(item) for item in value["waveplates"]]
    if "mirror" in value:
        result["mirror"] = mirror(value["mirror"])
    if "dichroic" in value:
        result["dichroic"] = dichroic(value["dichroic"])
    if "source" in value:
        raw = value["source"]
        shape(raw, SOURCE_FIELDS, {"enabled"}, "光源")
        source = {"enabled": boolean(raw["enabled"], "source.enabled")}
        for key in SOURCE_FIELDS & RANGES.keys():
            if key in raw:
                source[key] = numeric(raw[key], key)
        if "polarizationType" in raw:
            if not isinstance(raw["polarizationType"], str) or raw["polarizationType"] not in POLARIZATION_TYPES:
                invalid("出光偏振类型未登记")
            source["polarizationType"] = raw["polarizationType"]
        if "wavefrontRadiusMm" in raw:
            source["wavefrontRadiusMm"] = nullable_nonzero(raw["wavefrontRadiusMm"], "wavefrontRadiusMm", 1e12)
        result["source"] = source
    return result


def normalize_fields(instance):
    return {"optics": normalize_optics(instance["optics"])} if "optics" in instance else {}


def normalize_internal_fields(instance, kit):
    """Only catalog-declared internal surfaces may carry local optical settings."""
    if 'internalOptics' not in instance:
        return {}
    value=instance['internalOptics']
    assembly=kit.get('layout',{}).get('opticalAssembly')
    if not isinstance(value,dict) or len(value)>16 or not isinstance(assembly,dict) or not isinstance(assembly.get('internalElements'),list):
        invalid('内部光学配置只适用于已登记整装，最多16个内部光学面')
    known={element['id']:element for element in assembly['internalElements'] if isinstance(element,dict) and isinstance(element.get('id'),str)}
    result={}
    for identity,config in value.items():
        if (not isinstance(identity,str) or not 1<=len(identity)<=80 or identity.strip()!=identity or
                identity in ('__proto__','prototype','constructor') or any(ord(c)<32 for c in identity) or identity not in known):
            invalid('内部光学面编号未在当前整装目录中登记')
        if not isinstance(config,dict):invalid('内部光学参数必须为对象')
        clean=normalize_optics({key:val for key,val in config.items() if key!='coatingFaceIndex'})
        if 'coatingFaceIndex' in config:
            face=config['coatingFaceIndex']
            if clean['elementType'] not in ('mirror','dichroic') or not (face is None or type(face) is int and face in (0,1)):
                invalid('内部镜片镀膜面只能为0、1或待确认空值')
            clean['coatingFaceIndex']=face
        if clean['elementType']!=known[identity].get('type') or clean['elementType'] in ('source','coupler'):
            invalid('内部光学面类型必须与源整装目录一致')
        if clean.get('source',{}).get('enabled'):
            invalid('内部反射或透射面不能启用独立光源')
        if assembly.get('version',1) >= 2 and clean['elementType'] == 'waveplate':
            plates = config.get('waveplates', [config])
            if len(plates) != 1:
                invalid('v2每个波片平面只能配置一片，另一片使用独立平面')
            if clean.get('configured') and clean.get('inserted') and not all(key in plates[0] for key in ('fastAxisDeg', 'retardanceDeg', 'designWavelengthNm')):
                invalid('已确认并插入的v2波片需要完整快轴、延迟和设计波长')
        result[identity]=clean
    return {'internalOptics':result}


def validate_kit_source_ports(kit):
    """Validate additive v1 source-port definitions; legacy primary ports remain unchanged.

    Geometry/report/defaults belong only to the catalog.  False geometryConfirmed
    is an explicit unresolved datum, not permission to invent an instance pose.
    Return the extra port map for callers; never mutate the kit.
    """
    layout=kit.get('layout',{})
    ports=layout.get('opticalPortsMm')
    if ports is None or isinstance(ports,list) and len(ports)<=1:
        return {}
    if not isinstance(ports,list) or len(ports)>17:
        invalid('独立光源口需登记主口及最多16个额外光源口')
    is_source=layout.get('opticalType')=='source' or 'opticalType' not in layout and kit.get('category')=='laser'
    if not is_source or isinstance(layout.get('opticalAssembly'),dict):
        invalid('额外光源口仅适用于激光源套件，不能用于耦合口或内部整装')
    seen=set();result={}
    for index,port in enumerate(ports):
        if not isinstance(port,dict):invalid('目录光源口必须为对象')
        identity=port.get('id')
        if not isinstance(identity,str) or not SOURCE_PORT_ID.fullmatch(identity) or identity in ('__proto__','prototype','constructor') or identity in seen:
            invalid('目录光源口编号必须为唯一安全ID')
        seen.add(identity)
        if index==0:continue
        if port.get('role')!='source' or type(port.get('sourceVersion')) is not int or port['sourceVersion']!=1:
            invalid('额外光源口需要role=source及sourceVersion=1')
        if type(port.get('geometryConfirmed')) is not bool:
            invalid('额外光源口必须明确名义几何确认状态')
        for key in ('xMm','yMm','beamHeightMm','directionX','directionY'):
            val=port.get(key)
            if type(val) not in (int,float) or not math.isfinite(val) or abs(val)>1e4 or key=='beamHeightMm' and val<0:
                invalid('额外光源口需登记有限固定位置、高度与水平方向')
        if math.hypot(port['directionX'],port['directionY'])<1e-9:
            invalid('额外光源口水平出光方向不能为零')
        result[identity]=port
    return result


def normalize_source_port_fields(instance, kit):
    """Preserve only explicitly supplied pure source parameters; fill no defaults."""
    if 'sourcePorts' not in instance:return {}
    layout=kit.get('layout',{})
    is_source=layout.get('opticalType')=='source' or 'opticalType' not in layout and kit.get('category')=='laser'
    if not is_source or isinstance(layout.get('opticalAssembly'),dict):
        invalid('实例独立光源口仅适用于父级激光源套件')
    known=validate_kit_source_ports(kit)
    value=instance['sourcePorts']
    if not isinstance(value,dict) or len(value)>16 or not known:
        invalid('实例独立光源口只适用于已登记额外光源，最多16项')
    result={}
    for identity,config in value.items():
        if not isinstance(identity,str) or not SOURCE_PORT_ID.fullmatch(identity) or identity in ('__proto__','prototype','constructor') or identity not in known:
            invalid('实例光源口编号未登记、属于主口或不安全')
        shape(config,{'configured','source'},{'configured','source'},'独立光源口')
        configured=boolean(config['configured'],'sourcePorts.configured')
        shape(config['source'],SOURCE_PORT_FIELDS,{'enabled'},'独立光源参数')
        source=normalize_optics({'elementType':'source','inserted':True,'source':config['source']})['source']
        if configured:
            required=set(SOURCE_PORT_REQUIRED)
            if source.get('polarizationType') in ('linear','elliptical'):required.add('polarizationAngleDeg')
            if source.get('polarizationType')=='elliptical':required.add('ellipticityDeg')
            if not required<=set(source):
                invalid('确认独立光源前须明示波长、功率、束径、M²、偏振及波前；空波前表示用户接受束腰假设')
        result[identity]={'configured':configured,'source':source}
    return {'sourcePorts':result}
