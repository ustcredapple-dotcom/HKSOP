"""Validate the bounded, data-only optical interaction language in the catalog.

This is a catalog contract, not an instance/project setting or executable code.
Validation never fills missing physical measurements or changes existing optics.
The browser interpreter and this validator must accept the same JSON language.
"""
from __future__ import annotations

import copy
import math


FORMAT = "zzlab-optical-interaction"
VERSION = 1
MAX_INPUTS = 16
MAX_STEPS = 8
MAX_OUTPUTS = 16
RESERVED_INPUT_IDS = {"__proto__", "constructor", "prototype"}
OPTICAL_TYPES = {"empty", "mirror", "dichroic", "pbs", "waveplate", "lens", "coupler", "source", "unsupported"}
# Match JavaScript String.trim() while counting the original value in code points.
TRIM_CHARS = " \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
TOP_FIELDS = {"format", "version", "model", "heightToleranceMm", "inputs", "onNoMatch", "emission"}
CONDITION_FIELDS = {"direction", "wavelengthNm"}
STEP_FIELDS = {
    "pass": {"op"},
    "pbs": {"op"},
    "mirror": {"op", "mirror"},
    "waveplate": {"op", "waveplates"},
    "lens": {"op", "focalLengthMm"},
    "coupler": {"op", "halfAngleDeg"},
    "attenuate": {"op", "transmission"},
    "absorb": {"op", "reason"},
    "block": {"op", "reason"},
}


def _invalid(label, reason):
    raise ValueError(f"光路交互语言无效：{label}{reason}。")


def _object(value, allowed, required, label):
    if not isinstance(value, dict):
        _invalid(label, "必须是对象")
    if any(not isinstance(key, str) for key in value):
        _invalid(label, "只能使用字符串字段名")
    if set(value) - allowed or not required <= set(value):
        _invalid(label, "缺少必要字段或包含未知字段")


def _number(value, lower, upper, label):
    # Bounds before isfinite also reject huge Python integers without OverflowError.
    if type(value) not in (int, float) or not lower <= value <= upper or not math.isfinite(value):
        _invalid(label, f"必须是{lower:g}至{upper:g}的有限数字")
    return value


def _choice(value, values, label):
    if not isinstance(value, str) or value not in values:
        _invalid(label, "包含未登记选项")
    return value


def _text(value, limit, label):
    if (not isinstance(value, str) or not value.strip(TRIM_CHARS) or len(value) > limit
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        _invalid(label, f"必须是1至{limit}字的非空字符串")
    return value


def _condition(value, label):
    """Validate only condition fields; callers validate their surrounding shape."""
    result = {}
    if "direction" in value:
        direction = value["direction"]
        fields = {"angleDeg", "halfAngleDeg", "bidirectional"}
        _object(direction, fields, fields, label + ".direction")
        if type(direction["bidirectional"]) is not bool:
            _invalid(label + ".direction.bidirectional", "必须是布尔值")
        result["direction"] = {
            "angleDeg": _number(direction["angleDeg"], -3600, 3600, label + ".direction.angleDeg"),
            "halfAngleDeg": _number(direction["halfAngleDeg"], 0, 90, label + ".direction.halfAngleDeg"),
            "bidirectional": direction["bidirectional"],
        }
    if "wavelengthNm" in value:
        wavelength = value["wavelengthNm"]
        fields = {"min", "max", "onMismatch"}
        _object(wavelength, fields, fields, label + ".wavelengthNm")
        lo = _number(wavelength["min"], 1, 1e6, label + ".wavelengthNm.min")
        hi = _number(wavelength["max"], 1, 1e6, label + ".wavelengthNm.max")
        if lo > hi:
            _invalid(label + ".wavelengthNm", "最小值不能大于最大值")
        result["wavelengthNm"] = {
            "min": lo, "max": hi,
            "onMismatch": _choice(wavelength["onMismatch"], ("block", "warn"), label + ".wavelengthNm.onMismatch"),
        }
    return result


def _optics_parameters(value, kind, label):
    # Delayed import avoids a cycle when bom imports this catalog validator.
    from optics_settings import mirror, waveplate
    from bom import APIError

    try:
        return mirror(value) if kind == "mirror" else waveplate(value)
    except (APIError, ValueError, TypeError, OverflowError) as exc:
        _invalid(label, f"参数不符合既有{kind}格式：{exc}")


def _step(value, label):
    if not isinstance(value, dict):
        _invalid(label, "必须是对象")
    op = _choice(value.get("op"), STEP_FIELDS, label + ".op")
    required = {"op"}
    if op == "attenuate":
        required.add("transmission")
    if op == "block":
        required.add("reason")
    _object(value, STEP_FIELDS[op], required, label)
    result = {"op": op}
    if op == "mirror" and "mirror" in value:
        result["mirror"] = _optics_parameters(value["mirror"], "mirror", label + ".mirror")
    if op == "waveplate" and "waveplates" in value:
        waveplates = value["waveplates"]
        if not isinstance(waveplates, list) or not 1 <= len(waveplates) <= 8:
            _invalid(label + ".waveplates", "必须是1至8片的数组")
        result["waveplates"] = [_optics_parameters(row, "waveplate", f"{label}.waveplates[{i}]")
                                for i, row in enumerate(waveplates)]
    if op == "lens" and "focalLengthMm" in value:
        focal = _number(value["focalLengthMm"], -1e6, 1e6, label + ".focalLengthMm")
        if abs(focal) < 1e-6:
            _invalid(label + ".focalLengthMm", "绝对值不能小于0.000001")
        result["focalLengthMm"] = focal
    if op == "coupler" and "halfAngleDeg" in value:
        result["halfAngleDeg"] = _number(value["halfAngleDeg"], 0, 90, label + ".halfAngleDeg")
    if op == "attenuate":
        result["transmission"] = _number(value["transmission"], 0, 1, label + ".transmission")
    if "reason" in value:
        result["reason"] = _text(value["reason"], 500, label + ".reason")
    return result


def validate_optical_interaction(value):
    """Return an independent normalized v1 program, or raise ValueError.

    The caller must only supply trusted kit.layout.opticalInteraction. Absent
    programs keep legacy behavior; None is not a program. Runtime direction
    ambiguity, missing physical data and output energy limits belong to the
    interpreter, not to schema validation.
    """
    _object(value, TOP_FIELDS, {"format", "version", "model"}, "program")
    if value["format"] != FORMAT:
        _invalid("program.format", "不受支持")
    if type(value["version"]) not in (int, float) or value["version"] != VERSION:
        _invalid("program.version", "不受支持")
    model = _choice(value["model"], ("planar", "source"), "program.model")
    result = {"format": FORMAT, "version": VERSION, "model": model}
    if "heightToleranceMm" in value:
        result["heightToleranceMm"] = _number(value["heightToleranceMm"], 0, 100, "program.heightToleranceMm")
    if model == "source":
        if "inputs" in value or "onNoMatch" in value or "emission" not in value:
            _invalid("source", "必须包含emission，且不能包含inputs/onNoMatch")
        _object(value["emission"], CONDITION_FIELDS, set(), "source.emission")
        result["emission"] = _condition(value["emission"], "source.emission")
    else:
        if "emission" in value or "inputs" not in value or "onNoMatch" not in value:
            _invalid("planar", "必须包含inputs/onNoMatch，且不能包含emission")
        result["onNoMatch"] = _choice(value["onNoMatch"], ("block", "pass"), "program.onNoMatch")
        inputs = value["inputs"]
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_INPUTS:
            _invalid("program.inputs", f"必须是1至{MAX_INPUTS}项的数组")
        result["inputs"], seen = [], set()
        for i, row in enumerate(inputs):
            label = f"inputs[{i}]"
            _object(row, CONDITION_FIELDS | {"id", "steps"}, {"id", "steps"}, label)
            identity = _text(row["id"], 80, label + ".id")
            if identity in seen or identity in RESERVED_INPUT_IDS:
                _invalid(label + ".id", "不能重复或使用保留名称")
            seen.add(identity)
            steps = row["steps"]
            if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
                _invalid(label + ".steps", f"必须是1至{MAX_STEPS}项的数组")
            result["inputs"].append({"id": identity, **_condition(row, label),
                                     "steps": [_step(step, f"{label}.steps[{j}]") for j, step in enumerate(steps)]})
    return copy.deepcopy(result)


def validate_kit_optical_interaction(layout):
    """Validate the program and its trusted catalog context, without mutation.

    Older catalog rows have no program and retain their existing type inference.
    New language entries must declare their actual optical type explicitly;
    three-dimensional compound optics stay under their separate engine contract.
    Unknown physical height may be registered, but cannot authorize propagation.
    """
    if layout is None:
        return None
    if not isinstance(layout, dict):
        _invalid("layout", "必须是对象")
    if "opticalInteraction" not in layout:
        return None
    optical_type = _choice(layout.get("opticalType"), OPTICAL_TYPES, "layout.opticalType")
    if "opticalAssembly" in layout:
        _invalid("layout", "不能同时声明三维opticalAssembly和共面opticalInteraction")
    program = validate_optical_interaction(layout["opticalInteraction"])
    if program["model"] == "source" and optical_type != "source":
        _invalid("layout", "source交互仅适用于显式source光学类型")
    if program["model"] == "planar" and optical_type == "source":
        _invalid("layout", "source光学类型必须使用source交互声明")
    return program


def validate_kit_optical_assembly(layout, optical_slots=None):
    """v2 coupler, v3 passive spatial, v4 passive lens/retarder contract.

    Only v2 may emit at the parent. Internal optical settings contain values,
    never geometry or an independently enabled emitter. Missing measurements
    remain missing and are checked again by the runtime before propagation.
    """
    assembly = layout.get('opticalAssembly') if isinstance(layout, dict) else None
    if assembly is None:
        return None
    if not isinstance(assembly, dict):
        _invalid('opticalAssembly', '必须是对象')
    version = assembly.get('version', 1)
    if type(version) not in (int, float) or version not in (1, 2, 3, 4):
        _invalid('opticalAssembly.version', '只支持1、2、3或4')
    if version == 1:
        if 'emissionNodeId' in assembly:
            _invalid('opticalAssembly.emissionNodeId', '需要version 2')
        return copy.deepcopy(assembly)
    if version == 2 and (layout.get('opticalType') != 'coupler' or 'opticalInteraction' in layout):
        _invalid('opticalAssembly v2', '仅适用于显式coupler类型，不能同时声明共面交互')
    if version >= 3 and (layout.get('opticalType') != 'empty' or 'opticalInteraction' in layout or 'emissionNodeId' in assembly):
        _invalid('opticalAssembly passive', '仅适用于无出光口的被动复合器件')
    if type(assembly.get('verified')) is not bool:
        _invalid('opticalAssembly.verified', '必须显式声明布尔值')

    def vector(value, label, unit=False):
        if isinstance(value, dict):
            value = [value.get(k) for k in ('x', 'y', 'z')]
        if not isinstance(value, list) or len(value) != 3:
            _invalid(label, '需要三维向量')
        result = [_number(v, -1e8, 1e8, label) for v in value]
        length = math.hypot(*result)
        if unit:
            if length < 1e-12:
                _invalid(label, '不能为零向量')
            result = [v / length for v in result]
        return result

    bounds = assembly.get('bounds')
    if not isinstance(bounds, dict):
        _invalid('opticalAssembly.bounds', '需要三维边界')
    lower, upper = vector(bounds.get('min'), 'bounds.min'), vector(bounds.get('max'), 'bounds.max')
    if any(a >= b for a, b in zip(lower, upper)):
        _invalid('bounds', '上界必须大于下界')
    nodes = assembly.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 256:
        _invalid('nodes', '需要1至256个已登记平面')
    known = {}
    for node in nodes:
        if not isinstance(node, dict):
            _invalid('node', '必须是对象')
        identity = _text(node.get('id'), 128, 'node.id')
        if identity in known or identity in RESERVED_INPUT_IDS:
            _invalid('node.id', '重复或保留编号')
        kind = _choice(node.get('type'), (('lens',) if version == 4 else ()) + ('mirror', 'dichroic', 'objective', 'waveplate', 'coupler'), 'node.type')
        known[identity] = node
        center, normal = vector(node.get('centerMm'), 'node.centerMm'), vector(node.get('normal'), 'node.normal', True)
        radius = _number(node.get('radiusMm'), 1e-12, 1e8, 'node.radiusMm')
        if 'mechanicalClearRadiusMm' in node:
            _number(node['mechanicalClearRadiusMm'], 1e-12, radius, 'node.mechanicalClearRadiusMm')
        if type(node.get('geometryConfirmed')) is not bool:
            _invalid('node.geometryConfirmed', '必须显式声明布尔值')
        faces = node.get('faces')
        if not isinstance(faces, list) or not 1 <= len(faces) <= 16:
            _invalid('node.faces', '需要已登记的实际平面')
        for face in faces:
            if not isinstance(face, dict):
                _invalid('face', '必须是对象')
            fc, fn = vector(face.get('centerMm'), 'face.centerMm'), vector(face.get('normal'), 'face.normal', True)
            _number(face.get('radiusMm', radius), 1e-12, 1e8, 'face.radiusMm')
            if kind in ('lens', 'waveplate', 'coupler') and (len(faces) != 1 or abs(normal[2]) > 1e-7 or math.dist(center, fc) > 1e-7 or abs(sum(a*b for a, b in zip(normal, fn))-1) > 1e-7):
                _invalid('薄平面', '需要唯一注册面与水平名义正向法线')
        if 'halfAngleDeg' in node:
            _number(node['halfAngleDeg'], 0, 15, 'node.halfAngleDeg')
    port = known.get(assembly.get('emissionNodeId'))
    if version >= 3 and any(n['type'] == 'coupler' for n in nodes):
        _invalid('opticalAssembly passive', '被动器件不能包含耦合出光口')
    if version == 2 and (not port or port['type'] != 'coupler' or sum(n['type'] == 'coupler' for n in nodes) != 1):
        _invalid('emissionNodeId', '必须引用总装唯一的coupler端口')
    internal = assembly.get('internalElements', [])
    if not isinstance(internal, list) or len(internal) > 16:
        _invalid('internalElements', '最多16个内部光学设置')
    slots, seen = set(), set()
    for row in internal:
        if not isinstance(row, dict) or row.get('id') not in known or row.get('id') in seen or row.get('type') != known[row['id']]['type'] or row.get('type') in ('coupler', 'source'):
            _invalid('internalElements', '只允许已登记的非光源平面，编号和类型必须一致')
        seen.add(row['id'])
        defaults = row.get('opticalDefaults', {})
        if not isinstance(defaults, dict) or ('source' in defaults and not isinstance(defaults['source'], dict)):
            _invalid('internalElements.opticalDefaults', '必须是参数对象')
        if defaults.get('source', {}).get('enabled'):
            _invalid('internalElements', '不能启用独立内部光源')
        if row.get('type') in ('waveplate','lens'):
            slot = _text(row.get('slotId'), 128, 'internal.slotId')
            if slot in slots:
                _invalid('internal.slotId', '每片必须绑定独立安装位')
            if optical_slots is not None and not any(isinstance(s, dict) and s.get('id') == slot and s.get('type') == row.get('type') for s in optical_slots):
                _invalid('internal.slotId', '必须引用套件已登记的同类型安装位')
            slots.add(slot)
    if any(n['type'] in ('lens','waveplate') and n['id'] not in seen for n in nodes):
        _invalid('internalElements', '每个透镜或波片平面必须登记独立设置')
    return copy.deepcopy(assembly)
