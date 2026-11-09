"""Explicit, instance-pair-only waivers for conservative 2D collision checks.

These saved user decisions never change catalog geometry, mounting eligibility,
height validation or the collision/keepout rules for boards and moving stages.
"""
from __future__ import annotations

CAPABILITY = "zzlab-collision-overrides-v1"
MAX_OVERRIDES = 10000


def _invalid(message):
    from bom import APIError
    raise APIError("invalid_collision_overrides", message)


def normalize_fields(layout, instance_ids):
    if "collisionOverrides" not in layout:
        return {}
    value = layout["collisionOverrides"]
    if not isinstance(value, list) or len(value) > MAX_OVERRIDES:
        _invalid(f"碰撞豁免必须为最多 {MAX_OVERRIDES} 对器件的数组。")
    known, pairs = set(instance_ids), set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"instanceIds"}:
            _invalid("每项碰撞豁免只允许 instanceIds 两个器件编号。")
        ids = row["instanceIds"]
        if (not isinstance(ids, list) or len(ids) != 2 or
                any(not isinstance(i, str) or not i or i not in known for i in ids)):
            _invalid("碰撞豁免必须引用当前工程中两个存在的器件。")
        if ids[0] == ids[1]:
            _invalid("不能将器件自身列为碰撞豁免。")
        pair = tuple(sorted(ids))
        if pair in pairs:
            _invalid("同一对器件不能重复登记碰撞豁免。")
        pairs.add(pair)
    return {"collisionOverrides": [{"instanceIds": list(pair)} for pair in sorted(pairs)]}


def pair_keys(fields):
    return {frozenset(row["instanceIds"]) for row in fields.get("collisionOverrides", [])}


def permits(code, instance_ids, pairs):
    return (code == "collision" and len(instance_ids) == 2 and
            instance_ids[0] != instance_ids[1] and frozenset(instance_ids) in pairs)


def local_fields(layout, instances):
    """Project already-normalized waivers onto a derived per-board layout."""
    if "collisionOverrides" not in layout:
        return {}
    ids = {i["id"] for i in instances}
    return {"collisionOverrides": [
        {"instanceIds": list(row["instanceIds"])}
        for row in layout["collisionOverrides"] if set(row["instanceIds"]) <= ids
    ]}
