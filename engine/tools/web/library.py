#!/usr/bin/env python3
"""Versioned optical-library source, deterministic runtime compiler, and package staging.

The runtime application continues to consume catalog.json. Records under library/
are the sole editable catalog source. This tool never contacts CAD, changes a user
project/cart/database, or deploys a release. All mutating commands are explicit.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
from collections import Counter
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROTOCOL_VERSION = "zzlab-optics-library-v1"
GROUPS = {"components": "components", "kits": "kits", "boards": "registeredBoards"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")
ASSET_FIELDS = {"stepPath": ("assets", {".step", ".stp"}),
                "drawingPath": ("assets", {".pdf"}),
                "dxfPath": ("assets", {".dxf"}),
                "dxfPdfPath": ("assets", {".pdf"}),
                "setupPdfPath": ("assets", {".pdf"}),
                "topViewPath": ("static", {".svg", ".png", ".webp"}),
                "sideViewPath": ("static", {".svg", ".png", ".webp"})}


class LibraryError(ValueError):
    pass


def fail(message):
    raise LibraryError(message)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            fail(f"Duplicate JSON key: {key}")
        out[key] = value
    return out


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=strict_object,
                          parse_constant=lambda value: fail(f"Non-finite JSON number: {value}"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"Cannot read JSON {path}: {exc}")


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        fail(f"ID must be portable ASCII letters/digits/_.-: {value!r}")
    return value


def relative_path(value):
    if not isinstance(value, str) or not value or any(c in value for c in ("\\", "\0", ":")):
        fail(f"Unsafe relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        fail(f"Unsafe relative path: {value!r}")
    return value


def contained(root, relative):
    root = Path(root).resolve()
    candidate = root.joinpath(relative_path(relative)).resolve()
    if not candidate.is_relative_to(root):
        fail(f"Path or symlink escapes allowed root: {relative}")
    return candidate


def walk(value, pointer=""):
    yield pointer, value
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from walk(child, pointer + "/" + escaped)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, pointer + f"/{index}")


def entities(catalog):
    for group, key in GROUPS.items():
        for record in catalog.get(key, []):
            yield group, record


def make_source(catalog, source, origin_sha):
    """Write a new source directory, never merge into an existing source tree."""
    source = Path(source)
    if (source / "manifest.json").exists() or (source / "catalog-meta.json").exists() or (source / "records").exists():
        fail("Source already initialized; edit authoritative records or stage a package. Re-import is not an update mechanism.")
    meta = {key: value for key, value in catalog.items() if key not in GROUPS.values()}
    manifest = {"protocolVersion": PROTOCOL_VERSION, "sourceCatalogSha256": origin_sha,
                "rootKeyOrder": list(catalog),
                "recordOrder": {group: [r["id"] for r in catalog.get(key, [])] for group, key in GROUPS.items()}}
    atomic_write(source / "catalog-meta.json", json_bytes(meta))
    for group in GROUPS:
        (source / "records" / group).mkdir(parents=True, exist_ok=True)
    for group, record in entities(catalog):
        atomic_write(source / "records" / group / (identifier(record["id"]) + ".json"), json_bytes(record))
    atomic_write(source / "manifest.json", json_bytes(manifest))


def load_source(source):
    source = Path(source)
    manifest = read_json(source / "manifest.json")
    meta = read_json(source / "catalog-meta.json")
    if manifest.get("protocolVersion") != PROTOCOL_VERSION:
        fail("Unsupported library protocol version")
    if not isinstance(meta, dict) or set(meta) & set(GROUPS.values()):
        fail("catalog-meta must be an object without record arrays")
    order = manifest.get("rootKeyOrder")
    expected = set(meta) | set(GROUPS.values())
    if not isinstance(order, list) or len(order) != len(set(order)) or set(order) != expected:
        fail("rootKeyOrder must list every metadata field and record array exactly once")
    records = {}
    for group, key in GROUPS.items():
        ids = manifest.get("recordOrder", {}).get(group)
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
            fail(f"Invalid or duplicate {group} manifest order")
        expected_files = {identifier(item) + ".json" for item in ids}
        directory = source / "records" / group
        actual_files = {str(p.relative_to(directory)) for p in directory.rglob("*.json")}
        if actual_files != expected_files:
            fail(f"Unlisted/missing {group} records: extra={sorted(actual_files-expected_files)}, missing={sorted(expected_files-actual_files)}")
        records[key] = []
        for item in ids:
            record = read_json(contained(source, f"records/{group}/{item}.json"))
            if not isinstance(record, dict) or record.get("id") != item:
                fail(f"Record filename/ID mismatch: {group}/{item}")
            records[key].append(record)
    combined = {**meta, **records}
    return {key: combined[key] for key in order}


def validate_structure(catalog):
    from bom import validate_catalog, validate_laser_marking
    from layout import kit_geometry, local_bounds, collision_polygons
    for pointer, value in walk(catalog):
        if type(value) is float and not math.isfinite(value):
            fail(f"Non-finite number at {pointer}")
    for group, record in entities(catalog):
        identifier(record.get("id"))
        if 'laserMarking' in record:
            try:
                validate_laser_marking(record['laserMarking'])
            except (ValueError, TypeError, KeyError) as exc:
                fail(f"Invalid laser marking: {group}/{record['id']}: {exc}")
    try:
        # Runtime validator normalizes a copy. Never replace the original records.
        validate_catalog(catalog)
        kit_ids = {k["id"] for k in catalog["kits"]}
        graph = {}
        for kit in catalog["kits"]:
            geometry = kit.get("layout")
            if not isinstance(geometry, dict) or type(geometry.get("placementAllowed")) is not bool:
                fail(f"{kit['id']}: layout.placementAllowed must be an explicit boolean")
            overhang = geometry.get("baseOverhangAllowedWithPartialMounting", False)
            if type(overhang) is not bool:
                fail(f"{kit['id']}: baseOverhangAllowedWithPartialMounting must be boolean")
            if overhang:
                minimum = geometry.get("minimumAlignedMountingHoles")
                holes = geometry.get("mountingHoleOffsetsMm")
                if type(minimum) is not int or not 2 <= minimum <= 128 or not isinstance(holes, list):
                    fail(f"{kit['id']}: base overhang requires minimumAlignedMountingHoles between 2 and 128 and real mounting holes")
                points = []
                for hole in holes:
                    if not isinstance(hole, dict) or not all(type(hole.get(key)) in (int, float) for key in ("xMm", "yMm")):
                        fail(f"{kit['id']}: base overhang requires numeric real mounting-hole centers")
                    points.append((hole["xMm"], hole["yMm"]))
                if minimum > len(set(points)):
                    fail(f"{kit['id']}: base overhang minimum exceeds distinct real mounting holes")
            if "opticalClearApertureMm" in geometry:
                aperture = geometry["opticalClearApertureMm"]
                if type(aperture) not in (int, float) or not math.isfinite(aperture) or not 1e-6 <= aperture <= 1e4:
                    fail(f"{kit['id']}: invalid opticalClearApertureMm")
            if geometry["placementAllowed"]:
                checked = kit_geometry(kit)
                local_bounds(checked, "baseBoundsMm")
                local_bounds(checked, "collisionBoundsMm")
                collision_polygons(checked)
                if geometry.get("basePolygonsMm") is not None:
                    collision_polygons({**checked, "collisionPolygonsMm": geometry["basePolygonsMm"]})
                holes = geometry.get("mountingHoleOffsetsMm", [])
                if not isinstance(holes, list):
                    fail(f"{kit['id']}: mountingHoleOffsetsMm must be a list")
                points = []
                for point in holes:
                    if not isinstance(point, dict) or not all(type(point.get(k)) in (int, float) for k in ("xMm", "yMm")):
                        fail(f"{kit['id']}: mounting hole needs numeric xMm/yMm")
                    points.append((point["xMm"], point["yMm"]))
                if len(points) != len(set(points)):
                    fail(f"{kit['id']}: duplicate mounting hole center")
                minimum = geometry.get("minimumAlignedMountingHoles")
                if minimum is not None and (type(minimum) is not int or minimum < 1 or minimum > len(points)):
                    fail(f"{kit['id']}: minimumAlignedMountingHoles exceeds actual mounting holes")
                height = geometry.get("opticalAxisHeightMm")
                if height is not None and (type(height) not in (int, float) or not 0 <= height <= 5000):
                    fail(f"{kit['id']}: invalid optical-axis height")
                ports = geometry.get("opticalPortsMm")
                if ports is not None:
                    if not isinstance(ports, list):
                        fail(f"{kit['id']}: opticalPortsMm must be a list or null")
                    port_ids = set()
                    for port in ports:
                        if not isinstance(port, dict) or not isinstance(port.get("id"), str) or port["id"] in port_ids:
                            fail(f"{kit['id']}: missing/duplicate optical port ID")
                        port_ids.add(port["id"])
                        if not all(type(port.get(key)) in (int, float) for key in ("xMm", "yMm", "directionX", "directionY")):
                            fail(f"{kit['id']}: optical port needs numeric position and direction")
                        if abs(math.hypot(port["directionX"], port["directionY"]) - 1) > 1e-6:
                            fail(f"{kit['id']}: optical port direction must be a unit vector")
                        if port.get("beamHeightMm") is not None and (type(port["beamHeightMm"]) not in (int, float) or not 0 <= port["beamHeightMm"] <= 5000):
                            fail(f"{kit['id']}: invalid optical port height")
                center = geometry.get("opticalCenterMm")
                if center is not None and (not isinstance(center, dict) or not all(type(center.get(k)) in (int, float) for k in ("xMm", "yMm"))):
                    fail(f"{kit['id']}: opticalCenterMm must be numeric xMm/yMm or null")
            path, url = geometry.get("topViewPath"), geometry.get("topViewUrl")
            if path and url and url != "./" + path:
                fail(f"{kit['id']}: topViewPath/topViewUrl disagree")
            graph[kit["id"]] = []
            for child in kit.get("subassemblies", []):
                if child.get("kitId") not in kit_ids or type(child.get("quantity")) is not int or child["quantity"] < 1:
                    fail(f"{kit['id']}: invalid subassembly reference or quantity")
                graph[kit["id"]].append(child["kitId"])
        def visit(node, ancestors):
            if node in ancestors:
                fail(f"Cyclic subassemblies: {' -> '.join([*ancestors, node])}")
            for child in graph[node]:
                visit(child, [*ancestors, node])
        for node in graph:
            visit(node, [])
    except LibraryError:
        raise
    except Exception as exc:
        fail(f"Runtime/geometry validation failed: {exc}")


def asset_references(catalog):
    for group, record in list(entities(catalog)) + [("stageModules", row) for row in catalog.get("stageModules", [])]:
        for pointer, value in walk(record):
            if not isinstance(value, dict):
                continue
            for field, (root_name, suffixes) in ASSET_FIELDS.items():
                relative = value.get(field)
                if relative in (None, ""):
                    continue
                relative_path(relative)
                if Path(relative).suffix.lower() not in suffixes:
                    fail(f"Wrong asset extension: {group}/{record['id']}{pointer}/{field}")
                if root_name == "static" and not re.fullmatch(r"topviews/[A-Za-z0-9][A-Za-z0-9_.-]*\.(svg|png|webp)", relative):
                    fail(f"Top view is outside the public topviews route: {relative}")
                if root_name == "assets" and relative.split("/")[0] not in ("step", "drawings"):
                    fail(f"Manufacturing asset must be under step/ or drawings/: {relative}")
                if ('/laserMarking/files/' in pointer or field == 'setupPdfPath') and relative.split('/')[0] != 'drawings':
                    fail(f"Laser marking asset must be under drawings/: {relative}")
                yield root_name, relative, f"{group}/{record['id']}{pointer}/{field}"


def asset_inventory(catalog, project_root, overrides=None):
    overrides = overrides or {}
    indexed = {}
    for root_name, relative, ref in asset_references(catalog):
        key = root_name + "/" + relative
        if key not in indexed:
            path = overrides.get(key) or contained(Path(project_root) / root_name, relative)
            if not Path(path).is_file():
                fail(f"Missing runtime asset: {key} (referenced by {ref})")
            indexed[key] = {"path": key, "sha256": file_sha(path), "bytes": Path(path).stat().st_size, "references": []}
        indexed[key]["references"].append(ref)
    # These fields explicitly claim hashes of the shipped individual files.
    for group, record in entities(catalog):
        expected = []
        if group == "components":
            evidence = record.get("manufacturingEvidence", {})
            expected += [("stepPath", record.get("sourceStepSha256")), ("drawingPath", record.get("sourceDrawingSha256")),
                         ("dxfPath", record.get("sourceDxfSha256")), ("dxfPdfPath", record.get("dxfPdfSha256")), ("stepPath", evidence.get("sourceStepSha256")),
                         ("drawingPath", evidence.get("drawingSha256")), ("dxfPath", evidence.get("dxfSha256"))]
        elif group == "boards":
            evidence = record.get("sourceEvidence", {})
            expected += [("stepPath", evidence.get("stepSha256")), ("topViewPath", evidence.get("topViewSha256"))]
        for field, digest in expected:
            if digest and record.get(field):
                key = ASSET_FIELDS[field][0] + "/" + record[field]
                if indexed[key]["sha256"] != digest:
                    fail(f"Declared asset hash mismatch: {group}/{record['id']} {field}")
        if 'laserMarking' in record:
            from bom import validate_laser_marking
            try:
                marking = validate_laser_marking(record['laserMarking'])
            except (ValueError, TypeError, KeyError) as exc:
                fail(f"Invalid laser marking: {group}/{record['id']}: {exc}")
            for number, item in enumerate(marking['files']):
                for field, hash_field in (('dxfPath', 'sha256'), ('setupPdfPath', 'setupPdfSha256')):
                    if item.get(field):
                        key = ASSET_FIELDS[field][0] + '/' + item[field]
                        if indexed[key]['sha256'] != item[hash_field]:
                            fail(f"Declared laser marking hash mismatch: {group}/{record['id']}/laserMarking/files/{number}/{field}")
    return [indexed[k] for k in sorted(indexed)]


def provenance_and_gaps(group, record):
    sources = []
    for pointer, value in walk(record):
        if not isinstance(value, str) or not value:
            continue
        if pointer.endswith(("Url", "/sourceStep", "/originalSourceStep", "/specEvidencePath")) or pointer.endswith("/path"):
            sources.append({"pointer": pointer, "value": value})
    gaps = []
    def gap(code, detail):
        gaps.append({"code": code, "detail": detail})
    source_urls = [s["value"] for s in sources if s["value"].startswith(("http://", "https://"))]
    if not source_urls:
        gap("source-link-missing", "记录未提供来源链接；不代表没有来源文件。")
    if any("cad.onshape.com/documents/" in u for u in source_urls) and not any("/v/" in u for u in source_urls) and not any(k in record for k in ("manufacturingEvidence", "sourceAssembly")):
        gap("immutable-source-not-explicit", "来源包含可变工作区；记录未明确绑定不可变版本。")
    if group == "kits":
        layout = record.get("layout", {})
        if layout.get("placementAllowed") and not any(layout.get(k) for k in ("geometryEvidence", "calibration")):
            gap("geometry-evidence-not-explicit", "可放置记录未提供结构化几何/标定证据；须核对原始报告，不能自动视为已验证。")
        if layout.get("placementAllowed") and not layout.get("mountingHoleOffsetsMm"):
            gap("mounting-datum-unavailable", "无安装孔偏移；保留现有定位能力限制。")
        if layout.get("opticalDatumVerified") is False:
            gap("optical-datum-unverified", "原记录明确未确认光学基准；不能将名义/推测位置当实测光口。")
        if layout.get("opticalAxisHeightMm") is None:
            gap("optical-height-unavailable", "未提供确定光轴高度；不填默认高度冒充测量。")
        if layout.get("opticalType") == "unsupported":
            gap("optical-behavior-unsupported", "当前光路引擎不支持此器件的真实光学响应。")
    elif group == "components" and record.get("kind") == "custom":
        for field in ("stepPath", "drawingPath"):
            if not record.get(field):
                gap("manufacturing-asset-missing", f"未登记 {field}；不能声称完整加工资料。")
        if not record.get("manufacturingEvidence"):
            gap("manufacturing-evidence-not-structured", "加工审核证据尚未结构化登记；现有文件/状态原样保留。")
        spec = record.get("manufacturingSpec", {})
        for field in ("material", "surfaceTreatment"):
            if not spec.get(field) or "待确认" in spec[field]:
                gap("manufacturing-spec-pending", f"{field} 尚未确定。")
    elif group == "boards" and not record.get("drawingPath"):
        gap("board-drawing-missing", "已登记实际板型，尚无加工图；不作为完整制造包。")
    return sources, gaps


def audit(catalog, project_root, overrides=None):
    validate_structure(catalog)
    assets = asset_inventory(catalog, project_root, overrides)
    inventory, gaps = [], []
    for group, record in entities(catalog):
        sources, row_gaps = provenance_and_gaps(group, record)
        entity = f"{group}/{record['id']}"
        asset_paths = sorted({a["path"] for a in assets if any(r.startswith(entity + "/") for r in a["references"])})
        row = {"entity": entity, "id": record["id"], "name": record["name"],
               "recordPath": f"records/{group}/{record['id']}.json", "recordSha256": sha(json_bytes(record)),
               "declaredStatus": record.get("status", record.get("revision")),
               "provenance": sources, "assets": asset_paths,
               "protocolStatus": "legacy-imported", "structuralValidation": "passed", "physicalReverificationPerformed": False,
               "evidenceGapCount": len(row_gaps)}
        if group == "kits":
            row["category"] = record["category"]
            row["placementAllowed"] = record["layout"]["placementAllowed"]
            row["declaredOpticalType"] = record["layout"].get("opticalType")
            row["dependencies"] = ["components/" + c["componentId"] for c in record["components"]]
            row["dependencies"] += ["kits/" + c["kitId"] for c in record.get("subassemblies", [])]
        elif group == "components":
            row["kind"] = record["kind"]
        inventory.append(row)
        if row_gaps:
            gaps.append({"entity": entity, "name": record["name"], "items": row_gaps})
    digest = sha(json_bytes(catalog))
    summary = {"protocolVersion": PROTOCOL_VERSION, "catalogVersion": catalog["version"], "catalogSha256": digest,
               "status": "passed", "counts": {group: len(catalog.get(key, [])) for group, key in GROUPS.items()},
               "assetCount": len(assets), "assetScope": "Unique registered runtime STEP/PDF/DXF/topview files only; evidence source paths are provenance, not shipped runtime assets.", "entitiesWithEvidenceGaps": len(gaps),
               "checks": ["runtime-catalog-validator", "unique-portable-ids", "finite-numbers", "kit-placement-geometry",
                          "bom-and-optical-slot-references", "registered-board-geometry", "universal-post-references",
                          "acyclic-subassemblies", "asset-root-containment", "asset-existence-and-sha256", "declared-file-hashes"],
               "scope": "Structural/data/asset audit only. Existing geometry and manufacturing claims are retained, not newly certified."}
    return {"catalog-audit": summary, "entity-index": {"protocolVersion": PROTOCOL_VERSION, "catalogSha256": digest, "entities": inventory},
            "asset-index": {"protocolVersion": PROTOCOL_VERSION, "catalogSha256": digest, "assets": assets},
            "evidence-gaps": {"protocolVersion": PROTOCOL_VERSION, "catalogSha256": digest,
                              "blocking": False, "policy": "Evidence gaps are retained uncertainty, not a runtime validation failure or new physical certification.", "entities": gaps}}



def annotate_review_claims(reports, source, extra=None):
    declarations = []
    for path in sorted((Path(source) / "reviews").glob("*/review.json")):
        declarations.append(read_json(path))
    if extra:
        declarations.append(extra)
    by_entity = {row["entity"]: row for row in reports["entity-index"]["entities"]}
    for declaration in declarations:
        for record in declaration.get("records", []):
            row = by_entity.get(record.get("entity"))
            if row and row["recordSha256"] == record.get("recordSha256"):
                row["protocolStatus"] = "reviewer-declared-with-evidence"
                row["reviewPackageId"] = declaration["packageId"]
                row["reviewClaimScope"] = declaration.get("scope", "Submitted review declaration; not independent physical certification.")
    reports["catalog-audit"]["reviewerDeclaredEntities"] = sum(row["protocolStatus"] == "reviewer-declared-with-evidence" for row in by_entity.values())
    return reports

def write_reports(reports, destination):
    for name, report in reports.items():
        atomic_write(Path(destination) / (name + ".json"), json_bytes(report))


def verify_new_asset(path, target):
    """Basic file-format and active-SVG gate; geometry/PDF visual review remains human/CAD QA."""
    data = Path(path).read_bytes()
    suffix = Path(target).suffix.lower()
    if not data:
        fail(f"Empty package asset: {target}")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        fail(f"Invalid PDF header: {target}")
    if suffix in (".step", ".stp") and not data.lstrip().startswith(b"ISO-10303-21;"):
        fail(f"Invalid STEP header: {target}")
    if suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        fail(f"Invalid PNG header: {target}")
    if suffix == ".webp" and not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        fail(f"Invalid WebP header: {target}")
    if suffix == ".svg":
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            fail(f"SVG document declarations are not allowed: {target}")
        try:
            tree = ElementTree.fromstring(data)
        except ElementTree.ParseError as exc:
            fail(f"Invalid SVG: {target}: {exc}")
        for element in tree.iter():
            name = element.tag.split("}")[-1].lower()
            if name in ("script", "foreignobject", "iframe", "object", "embed", "style"):
                fail(f"Active/unreviewable SVG element {name}: {target}")
            for attribute, value in element.attrib.items():
                key = attribute.split("}")[-1].lower()
                if key.startswith("on") or "javascript:" in value.lower() or "url(" in value.lower() and not re.fullmatch(r"url\(#[A-Za-z0-9_.-]+\)", value):
                    fail(f"Active/external SVG attribute: {target}")
                if key == "href" and not (value.startswith("#") or value.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,"))):
                    fail(f"External SVG resource: {target}")



def source_state_sha(source):
    source = Path(source)
    paths = [source / "manifest.json", source / "catalog-meta.json"]
    paths += sorted((source / "records").rglob("*.json"))
    paths += sorted(p for p in (source / "reviews").rglob("*") if p.is_file())
    return sha(json_bytes([{ "path": str(p.relative_to(source)), "sha256": file_sha(p)} for p in paths]))


def validate_package_reviews(reviews, base):
    required = {"sourceReviewed", "geometryReviewed", "interactionReviewed", "bomReviewed"}
    if not isinstance(reviews, dict) or set(reviews) != required:
        fail("Package reviews must explicitly declare sourceReviewed, geometryReviewed, interactionReviewed, bomReviewed")
    evidence_files = {}
    for name, declaration in reviews.items():
        if not isinstance(declaration, dict) or set(declaration) - {"status", "reviewer", "reason", "evidence"}:
            fail(f"Invalid review declaration: {name}")
        if declaration.get("status") not in ("reviewed", "not-applicable"):
            fail(f"{name}: status must be reviewed or not-applicable")
        if not all(isinstance(declaration.get(k), str) and declaration[k].strip() for k in ("reviewer", "reason")):
            fail(f"{name}: identify reviewer and concrete review/reason; booleans are not evidence")
        evidence = declaration.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            fail(f"{name}: include hashed evidence, including rationale for not-applicable")
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                fail(f"{name}: invalid evidence file descriptor")
            relative = relative_path(item["path"])
            if not relative.startswith("evidence/"):
                fail("Package review evidence must be under evidence/")
            path = contained(base, relative)
            if not path.is_file() or file_sha(path) != item["sha256"]:
                fail(f"Missing or changed review evidence: {relative}")
            if relative in evidence_files and evidence_files[relative] != item["sha256"]:
                fail(f"Inconsistent evidence digest: {relative}")
            evidence_files[relative] = item["sha256"]
    return [{"path": path, "sha256": digest} for path, digest in sorted(evidence_files.items())]


def validate_review_archive(source):
    for path in sorted((Path(source) / "reviews").glob("*/review.json")):
        declaration = read_json(path)
        identifier(declaration.get("packageId"))
        if declaration["packageId"] != path.parent.name:
            fail("Review archive package ID mismatch")
        validate_package_reviews(declaration.get("reviews"), path.parent)


def validate_new_record(group, record):
    if group != "kits":
        return
    from optics_settings import ELEMENT_TYPES
    layout = record.get("layout", {})
    # Mechanical carriers have no optical datum. Giving them "unsupported"
    # makes the global-height planner incorrectly require an optical height.
    mechanical_only = layout.get("mechanicalOnly") is True
    if mechanical_only and (layout.get("opticalType") is not None or
                            record.get("opticalSlots") or layout.get("opticalAssembly") or
                            layout.get("opticalInteraction") or layout.get("opticalDefaults") or
                            layout.get("opticalDatumVerified") is not False or
                            any(layout.get(key) is not None for key in
                                ("opticalCenterMm", "opticalAxisHeightMm", "nominalOpticalHeightMm"))):
        fail(f"{record['id']}: mechanical-only carrier must not declare optical behavior or a datum")
    if not mechanical_only and layout.get("opticalType") not in ELEMENT_TYPES:
        fail(f"{record['id']}: new/revised kits must explicitly declare layout.opticalType; unknown = unsupported")
    if layout.get("placementAllowed"):
        required = ("topViewPath", "widthMm", "heightMm", "anchorXMm", "anchorYMm", "baseBoundsMm", "collisionBoundsMm", "collisionPolygonsMm", "mountingHoleOffsetsMm")
        if any(key not in layout for key in required):
            fail(f"{record['id']}: placeable package kit must explicitly register complete geometry and mounting data")
        if not layout["collisionPolygonsMm"]:
            fail(f"{record['id']}: missing collision geometry; register placementAllowed=false while unresolved")
        # A dimensioned commercial device may be placed on a table even when
        # its clamps are unmeasured. Do not invent holes or confuse placement
        # with verified threaded-board mounting.
        calibration = layout.get("calibration") or {}
        mounting_unknown = (layout.get("mountingConfirmed") is False or
                            isinstance(calibration, dict) and calibration.get("mountingPatternConfirmed") is False)
        if not layout["mountingHoleOffsetsMm"] and not mounting_unknown:
            fail(f"{record['id']}: empty mounting geometry needs an explicit unconfirmed-mounting declaration")
        if not (layout.get("geometryEvidence") or layout.get("calibration")):
            fail(f"{record['id']}: geometry evidence must be explicit; do not fabricate placement coordinates")


def adopt_stage(stage, source, project_root, apply=False):
    if not apply:
        return _adopt_stage_unlocked(stage, source, project_root, False)
    lock = Path(source) / ".adopt.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        fail("Another library adoption holds .adopt.lock; inspect it before retrying")
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(str(os.getpid()) + "\n")
        return _adopt_stage_unlocked(stage, source, project_root, True)
    finally:
        lock.unlink(missing_ok=True)

def package_candidate(package, source, project_root):
    package = Path(package)
    if package.is_dir():
        package = package / "package.json"
    base = package.parent.resolve()
    spec = read_json(package)
    if not isinstance(spec, dict) or spec.get("protocolVersion") != PROTOCOL_VERSION:
        fail("Unsupported package protocol")
    if set(spec) - {"protocolVersion", "packageId", "baseCatalogSha256", "records", "assets", "metadataPatch", "notes", "reviews"}:
        fail("Unknown package fields")
    identifier(spec.get("packageId"))
    catalog = load_source(source)
    if spec.get("baseCatalogSha256") != sha(json_bytes(catalog)):
        fail("Package baseCatalogSha256 does not match the current source; rebase/review explicitly")
    candidate = copy.deepcopy(catalog)
    records = spec.get("records")
    if not isinstance(records, list) or not records:
        fail("Package needs a nonempty records array")
    review_files = validate_package_reviews(spec.get("reviews"), base)
    changed, seen = [], set()
    for item in records:
        if not isinstance(item, dict) or set(item) - {"type", "id", "path", "mode", "previousSha256"}:
            fail("Invalid package record descriptor")
        group, rid, mode = item.get("type"), identifier(item.get("id")), item.get("mode", "add")
        if group not in GROUPS or mode not in ("add", "replace") or (group, rid) in seen:
            fail("Invalid/duplicate package entity or mode")
        seen.add((group, rid))
        record = read_json(contained(base, item.get("path")))
        if not isinstance(record, dict) or record.get("id") != rid:
            fail(f"Package record ID mismatch: {group}/{rid}")
        validate_new_record(group, record)
        if spec["reviews"]["sourceReviewed"]["status"] != "reviewed":
            fail("Every imported record needs reviewed source evidence")
        if (group == "boards" or group == "kits" and record["layout"].get("placementAllowed")) and spec["reviews"]["geometryReviewed"]["status"] != "reviewed":
            fail("Placeable kits and registered boards require geometryReviewed=reviewed")
        if group == "kits" and spec["reviews"]["interactionReviewed"]["status"] != "reviewed":
            fail("Kit imports require interactionReviewed=reviewed, including declared unsupported behavior")
        rows = candidate[GROUPS[group]]
        matches = [i for i, row in enumerate(rows) if row["id"] == rid]
        if mode == "add":
            if matches:
                fail(f"Add cannot overwrite existing ID: {group}/{rid}")
            rows.append(record)
        else:
            if not matches or item.get("previousSha256") != sha(json_bytes(rows[matches[0]])):
                fail(f"Replacement missing/mismatched old record SHA: {group}/{rid}")
            rows[matches[0]] = record
        changed.append({"entity": group + "/" + rid, "mode": mode, "recordSha256": sha(json_bytes(record))})
    patch = spec.get("metadataPatch", {})
    # This typed capability is validated by moving_stages through the runtime
    # catalog validator. It is additive; generic unknown root fields stay denied.
    if not isinstance(patch, dict) or set(patch) - ((set(catalog) - set(GROUPS.values())) | {"stageModules"}):
        fail("Metadata patch must contain existing root fields or the typed stageModules capability")
    candidate.update(patch)
    if candidate["version"] == catalog["version"]:
        fail("A package must change metadataPatch.version for cache/project compatibility")
    overrides, updates = {}, []
    if not isinstance(spec.get("assets", []), list):
        fail("Package assets must be an array")
    for item in spec.get("assets", []):
        if not isinstance(item, dict) or set(item) - {"root", "path", "source", "sha256", "mode", "previousSha256"}:
            fail("Invalid asset descriptor")
        root_name, relative, mode = item.get("root"), relative_path(item.get("path")), item.get("mode", "add")
        if root_name not in ("assets", "static") or mode not in ("add", "replace"):
            fail("Asset root/mode invalid")
        allowed = root_name == "assets" and relative.split("/")[0] in ("step", "drawings") and Path(relative).suffix.lower() in (".step", ".stp", ".pdf", ".dxf")
        allowed |= root_name == "static" and bool(re.fullmatch(r"topviews/[A-Za-z0-9][A-Za-z0-9_.-]*\.(svg|png|webp)", relative))
        if not allowed:
            fail(f"Package may only write manufacturing or topview assets: {root_name}/{relative}")
        key = root_name + "/" + relative
        if key in overrides:
            fail(f"Duplicate package asset: {key}")
        data_path = contained(base, item.get("source"))
        if not data_path.is_file() or file_sha(data_path) != item.get("sha256"):
            fail(f"Package asset SHA mismatch: {key}")
        target = contained(Path(project_root) / root_name, relative)
        if mode == "add" and target.exists():
            fail(f"Add cannot overwrite asset: {key}")
        if mode == "replace" and (not target.is_file() or file_sha(target) != item.get("previousSha256")):
            fail(f"Replacement missing/mismatched old asset SHA: {key}")
        verify_new_asset(data_path, key)
        overrides[key] = data_path
        updates.append({"path": key, "mode": mode, "sha256": item["sha256"], "previousSha256": item.get("previousSha256")})
    reports = audit(candidate, project_root, overrides)
    used = {row["path"] for row in reports["asset-index"]["assets"]}
    if set(overrides) - used:
        fail(f"Unreferenced package assets: {sorted(set(overrides)-used)}")
    plan = {"protocolVersion": PROTOCOL_VERSION, "packageId": spec["packageId"], "baseCatalogSha256": sha(json_bytes(catalog)),
            "candidateCatalogSha256": sha(json_bytes(candidate)), "catalogVersion": candidate["version"],
            "records": changed, "assets": updates, "metadataPatch": patch, "applied": False, "baseSourceSha256": source_state_sha(source),
            "reviews": spec["reviews"], "reviewEvidence": review_files,
            "reviewClaimScope": "Submitted reviewer declarations with hashed evidence; these are not independent physical certification by this tool."}
    annotate_review_claims(reports, source, {"packageId": plan["packageId"], "records": plan["records"], "scope": plan["reviewClaimScope"]})
    return candidate, overrides, reports, plan


def stage_package(package, source, project_root, output=None):
    candidate, overrides, reports, plan = package_candidate(package, source, project_root)
    if output is not None:
        output = Path(output)
        if output.exists():
            fail("Stage output must be a new directory; refusing to overwrite")
        output.mkdir(parents=True)
        try:
            make_source(candidate, output / "library", plan["baseCatalogSha256"])
            if (Path(source) / "reviews").exists():
                shutil.copytree(Path(source) / "reviews", output / "library" / "reviews")
            review_root = output / "library" / "reviews" / plan["packageId"]
            if review_root.exists():
                fail("Review package ID already exists; use a new packageId")
            package_base = Path(package) if Path(package).is_dir() else Path(package).parent
            for evidence in plan["reviewEvidence"]:
                destination = review_root / evidence["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(contained(package_base, evidence["path"]), destination)
            atomic_write(review_root / "review.json", json_bytes({"packageId": plan["packageId"], "records": plan["records"], "reviews": plan["reviews"], "scope": plan["reviewClaimScope"]}))
            write_reports(reports, output / "library" / "generated")
            atomic_write(output / "catalog.json", json_bytes(candidate))
            for relative, source_path in overrides.items():
                destination = output / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
            atomic_write(output / "stage-plan.json", json_bytes(plan))
        except Exception:
            shutil.rmtree(output)
            raise
    return plan


def _adopt_stage_unlocked(stage, source, project_root, apply=False):
    """Adopt reviewed stage to local editable source; runtime catalog stays untouched."""
    stage, source, project_root = Path(stage), Path(source), Path(project_root)
    plan = read_json(stage / "stage-plan.json")
    if not isinstance(plan, dict) or plan.get("protocolVersion") != PROTOCOL_VERSION:
        fail("Unsupported staged plan protocol")
    identifier(plan.get("packageId"))
    current = load_source(source)
    if source_state_sha(source) != plan.get("baseSourceSha256"):
        fail("Current source/review files changed since staging; rebuild stage")
    if sha(json_bytes(current)) != plan.get("baseCatalogSha256"):
        fail("Current source changed since stage creation; rebuild stage")
    candidate = load_source(stage / "library")
    if sha(json_bytes(candidate)) != plan.get("candidateCatalogSha256") or json_bytes(candidate) != (stage / "catalog.json").read_bytes():
        fail("Staged source/runtime no longer matches the reviewed plan")
    validate_review_archive(stage / "library")
    overrides = {}
    for item in plan["assets"]:
        if item.get("mode") not in ("add", "replace"):
            fail("Invalid staged asset mode")
        relative = relative_path(item["path"])
        root_name, rest = relative.split("/", 1)
        allowed = root_name == "assets" and rest.split("/")[0] in ("step", "drawings") and Path(rest).suffix.lower() in (".step", ".stp", ".pdf", ".dxf")
        allowed |= root_name == "static" and bool(re.fullmatch(r"topviews/[A-Za-z0-9][A-Za-z0-9_.-]*\.(svg|png|webp)", rest))
        if not allowed:
            fail("Invalid staged asset target")
        path = contained(stage, relative)
        target = contained(project_root / root_name, rest)
        if file_sha(path) != item["sha256"]:
            fail(f"Staged asset changed: {relative}")
        if item["mode"] == "add" and target.exists():
            fail(f"Asset appeared after staging: {relative}")
        if item["mode"] == "replace" and (not target.is_file() or file_sha(target) != item["previousSha256"]):
            fail(f"Current asset changed after staging: {relative}")
        verify_new_asset(path, relative)
        overrides[relative] = path
    reports = annotate_review_claims(audit(candidate, project_root, overrides), stage / "library")
    if not apply:
        return {**plan, "action": "adopt-dry-run", "next": "adopt STAGE --apply; then build --check/--write and deploy separately"}
    backup = source / "backups" / (plan["packageId"] + "-" + plan["baseCatalogSha256"][:12])
    if backup.exists():
        fail("Adoption backup already exists; inspect previous attempt before retrying")
    backup.mkdir(parents=True)
    snapshot_names = ("manifest.json", "catalog-meta.json", "records", "generated", "reviews")
    for name in snapshot_names:
        src, dest = source / name, backup / name
        if src.exists():
            shutil.copytree(src, dest) if src.is_dir() else shutil.copy2(src, dest)
    for relative in overrides:
        target = project_root / relative
        if target.exists():
            destination = backup / "assets-before" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    atomic_write(backup / "plan.json", json_bytes(plan))
    if source_state_sha(source) != plan["baseSourceSha256"]:
        fail("Source changed while preparing backup; no source/asset writes applied")
    try:
        for relative, staged_path in overrides.items():
            atomic_write(project_root / relative, staged_path.read_bytes())
        # Each file replacement is atomic; runtime is still the old catalog until build.
        for group, record in entities(candidate):
            atomic_write(source / "records" / group / (record["id"] + ".json"), json_bytes(record))
        for name in ("catalog-meta.json", "manifest.json"):
            atomic_write(source / name, (stage / "library" / name).read_bytes())
        if (stage / "library" / "reviews").exists():
            if (source / "reviews").exists():
                shutil.rmtree(source / "reviews")
            shutil.copytree(stage / "library" / "reviews", source / "reviews")
        write_reports(reports, source / "generated")
        receipt = {**plan, "action": "adopt", "applied": True, "backup": str(backup),
                   "runtimeCatalogWritten": False, "next": "build --write, test, deploy separately"}
        atomic_write(backup / "receipt.json", json_bytes(receipt))
    except Exception:
        for name in snapshot_names:
            prior, target = backup / name, source / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if prior.exists():
                shutil.copytree(prior, target) if prior.is_dir() else shutil.copy2(prior, target)
        for relative in overrides:
            prior = backup / "assets-before" / relative
            if prior.exists():
                atomic_write(project_root / relative, prior.read_bytes())
            else:
                (project_root / relative).unlink(missing_ok=True)
        raise
    return receipt



def check_derived_indexes(catalog, project_root, source, required=False):
    """Check index provenance without Node; explicit generation belongs to its builder."""
    names = ("interaction-index.json", "port-index.json")
    result = []
    canonical_catalog_hash = sha(json_bytes(catalog))
    for name in names:
        path = Path(source) / "generated" / name
        if not path.is_file():
            if required and name == "interaction-index.json":
                fail(f"Required derived index is missing: {path}; run the interaction-index builder")
            continue
        index = read_json(path)
        if index.get("sourceCatalogSha256") != canonical_catalog_hash:
            fail(f"Derived index has stale catalog SHA: {name}; rebuild it after catalog changes")
        for key in ("kits", "registeredBoards", *(("stageModules",) if catalog.get("stageModules") else ())):
            rows = index.get(key)
            expected = {record["id"]: record for record in catalog.get(key, [])}
            if not isinstance(rows, list) or len(rows) != len(expected) or {row.get("id") for row in rows} != set(expected):
                fail(f"Derived index has missing/duplicate {key}: {name}")
            for row in rows:
                digest = sha(json.dumps(expected[row["id"]], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
                if row.get("sourceRecordSha256") != digest:
                    fail(f"Derived index record SHA is stale: {name} {key}/{row['id']}")
        runtime = index.get("derivation", {}).get("runtimeFiles")
        if not isinstance(runtime, list) or not runtime:
            fail(f"Derived index has no runtime source hashes: {name}")
        seen = set()
        for item in runtime:
            relative = relative_path(item.get("path"))
            if relative in seen:
                fail(f"Duplicate derived-index runtime source: {relative}")
            seen.add(relative)
            runtime_path = contained(project_root, relative)
            if not runtime_path.is_file() or file_sha(runtime_path) != item.get("sha256"):
                fail(f"Derived index runtime source changed: {name} {relative}; rebuild the index")
        if required and name == "interaction-index.json":
            critical = ("moving_stages.py", "static/moving-stages.js", "static/optical-renderer.js", "static/optical-engine.js", "static/optical-interaction.js",
                        "static/optical-interaction-language.js", "optical_interaction.py",
                        "tools/build-interaction-index.py", "tools/build-interaction-index.cjs")
            omitted = [relative for relative in critical if (Path(project_root) / relative).is_file() and relative not in seen]
            if any(k.get('layout',{}).get('manualMountingPolicy') for k in catalog['kits']):omitted += [p for p in ('manual_source_mount.py','static/manual-source-mount.js') if p not in seen]
            if omitted:
                fail(f"Interaction index omits critical source fingerprints: {omitted}")
        for item in index.get("derivation", {}).get("definitionFiles", []):
            definition = contained(project_root, item.get("path"))
            if not definition.is_file() or file_sha(definition) != item.get("sha256"):
                fail(f"Derived index definition changed: {name} {item.get('path')}")
        result.append({"path": "generated/" + name, "sha256": file_sha(path), "status": "source-hashes-current"})
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT, help="Asset/validator project root (default repository)")
    parser.add_argument("--source", type=Path, help="Editable library root (default PROJECT/library)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-existing", help="One-time lossless bootstrap; refuses initialized sources")
    p.add_argument("--catalog", type=Path)
    p = sub.add_parser("build", help="Validate and compile deterministic runtime catalog")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Read-only byte equality check (default)")
    group.add_argument("--write", action="store_true", help="Explicitly update generated runtime catalog")
    p.add_argument("--catalog", type=Path)
    p.add_argument("--require-derived-index", action="store_true", help="Production gate: require current interaction index and verify optional port index (check mode)")
    p = sub.add_parser("audit", help="Validate all records/assets and summarize retained evidence gaps")
    p.add_argument("--write", action="store_true", help="Write derived reports under source/generated")
    p = sub.add_parser("stage", help="Validate package; default dry-run, optional isolated candidate output")
    p.add_argument("package", type=Path)
    p.add_argument("--output", type=Path)
    p = sub.add_parser("adopt", help="Adopt a reviewed stage to LOCAL editable source; never deploys")
    p.add_argument("stage", type=Path)
    p.add_argument("--apply", action="store_true", help="Explicit local source/asset writes with backup")
    p = sub.add_parser("package-template", help="Copy a commented-by-documentation package template")
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root, source = args.project_root.resolve(), (args.source or args.project_root / "library").resolve()
    if args.command not in ("import-existing",):
        validate_review_archive(source)
    if args.command == "package-template":
        if args.output.exists():
            fail("Template output already exists")
        shutil.copytree(ROOT / "library" / "templates" / "new-element", args.output)
        spec = read_json(args.output / "package.json")
        spec["baseCatalogSha256"] = sha(json_bytes(load_source(source)))
        atomic_write(args.output / "package.json", json_bytes(spec))
        result = {"template": str(args.output), "status": "template-only; replace TODO fields/assets before staging"}
    elif args.command == "import-existing":
        path = args.catalog or root / "catalog.json"
        catalog = read_json(path)
        reports = audit(catalog, root)
        make_source(catalog, source, file_sha(path))
        write_reports(reports, source / "generated")
        result = reports["catalog-audit"]
    elif args.command == "build":
        if args.write and args.require_derived_index:
            fail("--require-derived-index is a check gate; build --write first, rebuild indexes, then build --check --require-derived-index")
        catalog = load_source(source)
        reports = annotate_review_claims(audit(catalog, root), source)
        path = args.catalog or root / "catalog.json"
        compiled = json_bytes(catalog)
        if args.write:
            atomic_write(path, compiled)
            write_reports(reports, source / "generated")
        elif not path.is_file() or path.read_bytes() != compiled:
            fail(f"Generated runtime catalog differs: {path}; review source diff, then run build --write")
        indexes = [] if args.write else check_derived_indexes(catalog, root, source, args.require_derived_index)
        result = {**reports["catalog-audit"], "runtimeByteEquivalent": path.read_bytes() == compiled, "written": args.write, "derivedIndexes": indexes}
    elif args.command == "audit":
        reports = annotate_review_claims(audit(load_source(source), root), source)
        if args.write:
            write_reports(reports, source / "generated")
        result = reports["catalog-audit"]
    elif args.command == "stage":
        result = stage_package(args.package, source, root, args.output)
    else:
        result = adopt_stage(args.stage, source, root, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LibraryError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"library: {exc}", file=sys.stderr)
        raise SystemExit(2)
