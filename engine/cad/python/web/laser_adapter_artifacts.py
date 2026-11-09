"""Validated, content-addressed laser adapter artifacts; no caller-supplied paths."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from bom import APIError
from laser_adapter import validate_adapter_spec

DRAWING_REVISION = 'thread-designation-only-20261026'
CAD_TIMEOUT_SECONDS = 180
ARTIFACT_SUFFIXES = {"step": ".step", "drawing": ".pdf", "holeSpec": ".json", "topView": ".svg"}


def _valid_cache(folder, spec, check_drawing=True):
    try:
        if folder.is_symlink() or (folder / "artifact.json").is_symlink():
            return False
        report = json.loads((folder / "artifact.json").read_text())
        if not isinstance(report, dict) or not isinstance(report.get("geometryValidation"), dict):
            return False
        if check_drawing and report.get("drawing", {}).get("drawingRevision") != DRAWING_REVISION:
            return False
        if report.get("digest") != spec["digest"] or report.get("generatorVersion") != spec["generatorVersion"] or report.get("spec") != spec:
            return False
        if not report.get("geometryValidation", {}).get("valid"):
            return False
        for key, suffix in ARTIFACT_SUFFIXES.items():
            path = folder / (spec["filenameStem"] + suffix)
            if path.is_symlink() or not path.is_file() or path.stat().st_size < 100:
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != report["sha256"][key]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _result(folder, spec):
    return {**{key: folder / (spec["filenameStem"] + suffix) for key, suffix in ARTIFACT_SUFFIXES.items()},
            "spec": spec, "componentId": spec["componentId"], "model": spec["model"], "filenameStem": spec["filenameStem"]}


def ensure_adapter_artifacts(raw_spec, cache_dir, cad_python=None):
    """Validate the canonical spec before any read/write or CAD process spawn."""
    spec = validate_adapter_spec(raw_spec)
    cache = Path(cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    folder = cache / spec["digest"]
    if _valid_cache(folder, spec):
        return _result(folder, spec)
    python = cad_python or os.environ.get("ZZLAB_CAD_PYTHON")
    if not python or not Path(python).is_file():
        raise APIError("cad_unavailable", "激光器底板 CAD 生成服务尚未配置，请管理员设置 ZZLAB_CAD_PYTHON。", 503)
    worker = Path(__file__).with_name("laser_adapter_worker.py").resolve()
    with (cache / ".cad-worker.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if _valid_cache(folder, spec):
            return _result(folder, spec)
        tmp = Path(tempfile.mkdtemp(prefix=".laser-adapter-", dir=cache))
        try:
            reuse = _valid_cache(folder, spec, check_drawing=False)
            if reuse:
                for f in [spec["filenameStem"] + suffix for suffix in ARTIFACT_SUFFIXES.values()] + ["artifact.json"]:
                    shutil.copy2(folder / f, tmp / f)
            request = tmp / "request.json"
            request.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            try:
                process = subprocess.run([str(python), str(worker), "--request", str(request), "--out", str(tmp)] + (["--drawing-only"] if reuse else []),
                                         cwd=str(worker.parent), capture_output=True, text=True,
                                         timeout=CAD_TIMEOUT_SECONDS, check=False)
            except OSError as exc:
                raise APIError("cad_unavailable", "激光器底板 CAD 解释器无法启动，请检查服务配置。", 503) from exc
            except subprocess.TimeoutExpired as exc:
                raise APIError("cad_timeout", "激光器底板 CAD 生成超过 180 秒，请稍后重试。", 503) from exc
            if process.returncode != 0 or not _valid_cache(tmp, spec):
                raise APIError("cad_failed", "激光器底板 STEP / 图纸生成未完成，请检查 CAD 服务依赖或参数。", 503)
            if folder.is_symlink():
                folder.unlink()
            elif folder.exists():
                shutil.rmtree(folder)
            tmp.rename(folder)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)
    return _result(folder, spec)
