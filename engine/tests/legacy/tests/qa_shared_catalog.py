"""Independent shared-library QA: real catalog, temporary DB and loopback server.

Never starts or writes the production service. Uses the JS project codec as the
source of a valid portable project, then compares server accounting/round-trip.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Config, create_server
from bom import APIError, aggregate, load_catalog
from shared_kits import Identity, SharedKitStore, prepare_project, project_payload, strict_json, thumbnail_svg
import shared_kits

NODE = Path(os.environ.get("ZZLAB_QA_NODE", "/Users/wjj/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"))
EXAMPLE = ROOT.parents[1] / "outputs/ZZLab光路套件网页交付/布局示例_2波片_3固定镜架.json"


def codec_run(script, value=None):
    result = subprocess.run([str(NODE), "-e", script], cwd=ROOT,
                            input=None if value is None else json.dumps(value),
                            text=True, check=True, capture_output=True)
    return json.loads(result.stdout)


def real_project():
    script = """
const fs=require('node:fs'),codec=require('./static/project-file.js');
const catalog=JSON.parse(fs.readFileSync('catalog.json','utf8'));
const p=codec.parse(JSON.parse(fs.readFileSync(process.env.ZZLAB_QA_EXAMPLE,'utf8')),{catalog}).project;
p.metadata={name:'QA real example',notes:'<script>not executable</script>',createdAt:'2026-09-24T00:00:00.000Z',updatedAt:'2026-09-24T00:00:00.000Z'};
p.optical={'waveplate-1::wave-1':{model:'',wavelength:'532',opticalType:'half-wave'},'waveplate-2::wave-1':{model:'QA-WAVE-780',wavelength:'780',kind:'standard'},'module:dp-module::fixed-1-45-mirror':{model:'QA-MODULE',wavelength:'1064'}};
const e=(id,kitId,quantity,instanceId)=>({id,kitId,kind:'standard',name:id,model:id.toUpperCase(),quantity,unit:'颗',notes:'',...(instanceId?{instanceId}:{})});
p.extras=[e('qa-global',null,5),e('qa-per-kit','waveplate',2),e('qa-instance','waveplate',3,'waveplate-1'),e('qa-inactive','pbs-fixed',7),e('qa-module','dp-module',11)];
p.moduleQuantities=[['dp-module',4]];p.ui.selectedIds=['waveplate-1'];
console.log(JSON.stringify(codec.create(p,{catalog,now:'2026-09-24T00:00:00.000Z'})));
"""
    env = dict(os.environ, ZZLAB_QA_EXAMPLE=str(EXAMPLE))
    result = subprocess.run([str(NODE), "-e", script], cwd=ROOT, env=env,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class SharedCatalogQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")
        cls.project = real_project()

    def test_real_canvas_counts_and_partial_optical_roundtrip(self):
        original = copy.deepcopy(self.project)
        payload = project_payload(self.project, self.catalog)
        self.assertEqual(self.project, original)
        preview = aggregate(self.catalog, payload)
        rows = {row["model"]: row for row in preview["standard"]}
        for model, count in (("QA-GLOBAL", 5), ("QA-PER-KIT", 4), ("QA-INSTANCE", 3), ("QA-WAVE-780", 1)):
            self.assertEqual(rows[model]["quantity"], count)
        self.assertNotIn("QA-INACTIVE", rows)
        self.assertNotIn("QA-MODULE", rows)
        self.assertTrue(preview["layoutValidation"]["valid"])
        self.assertEqual(len(preview["layout"]["instances"]), 5)
        self.assertEqual(self.project["optical"]["waveplate-1::wave-1"]["model"], "")

    def test_forged_material_assets_author_and_duplicate_json_are_rejected(self):
        for scope, key, value in (("root", "assets", {"stepPath": "/private/file"}),
                                  ("board", "material", "forged"),
                                  ("instance", "topViewUrl", "https://example.invalid/payload.svg"),
                                  ("extra", "stepPath", "../../private/file")):
            p = copy.deepcopy(self.project)
            target = p if scope == "root" else p["layout"]["board"] if scope == "board" else p["layout"]["instances"][0] if scope == "instance" else p["extras"][0]
            target[key] = value
            with self.subTest(scope=scope), self.assertRaises(APIError):
                project_payload(p, self.catalog)
        for data in ('{"a":1,"a":2}', '{"__proto__":{}}', '{"value":NaN}'):
            with self.assertRaises(APIError):
                strict_json(data)

    def test_thumbnail_uses_server_assets_once_and_no_uploaded_markup(self):
        preview = prepare_project(self.project, self.catalog)
        image = thumbnail_svg(preview, ROOT / "static")
        root = ET.fromstring(image)
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertEqual(len(root.findall(".//s:image", ns)), 2)
        self.assertEqual(len(root.findall(".//s:use", ns)), 5)
        self.assertNotIn(b"<script", image)
        self.assertNotIn(b"not executable", image)
        for element in root.iter():
            for name, value in element.attrib.items():
                if name.endswith("href"):
                    self.assertTrue(value.startswith("data:image/") or value.startswith("#kit"))
        self.assertLess(len(image), 1024 * 1024)

    def test_store_owner_admin_visibility_immutable_backup_and_restart(self):
        with tempfile.TemporaryDirectory(prefix="zzlab-shared-qa-") as directory:
            path = Path(directory)
            store = SharedKitStore(path / "persistent/library.sqlite3", path / "backup.sqlite3")
            owner, other, admin = Identity("101", "Owner", "user"), Identity("102", "Other", "user"), Identity("999", "Admin", "admin")
            result = store.publish("QA", "real catalog", self.project, b"<svg/>", owner)
            kid = result["kit"]["id"]
            self.assertEqual(result["backup"]["status"], "ok")
            row = store.get(kid, owner)
            self.assertEqual(strict_json(row["project_json"]), self.project)
            self.assertFalse(store.listing(other)["kits"][0]["canUnpublish"])
            with self.assertRaises(APIError):
                store.change_visibility(kid, other, False)
            store.change_visibility(kid, owner, False)
            self.assertEqual(store.listing(other)["withdrawn"], [])
            with self.assertRaises(APIError):
                store.get(kid, other)
            self.assertEqual(store.listing(admin)["withdrawn"][0]["id"], kid)
            store.change_visibility(kid, admin, True)
            restarted = SharedKitStore(path / "persistent/library.sqlite3")
            self.assertEqual(restarted.get(kid, other)["project_json"], row["project_json"])
            with sqlite3.connect(path / "backup.sqlite3") as backup:
                saved, active = backup.execute("SELECT project_json,active FROM shared_kits WHERE id=?", (kid,)).fetchone()
                self.assertEqual(saved, row["project_json"])
                self.assertEqual(active, 1)
            restored = codec_run("const fs=require('node:fs'),c=require('./static/project-file.js');const catalog=JSON.parse(fs.readFileSync('catalog.json','utf8'));console.log(JSON.stringify(c.parse(fs.readFileSync(0,'utf8'),{catalog}).project));", strict_json(row["project_json"]))
            self.assertEqual(restored, self.project)

    def test_nas_unavailable_preserves_committed_data_with_explicit_warning(self):
        with tempfile.TemporaryDirectory(prefix="zzlab-shared-qa-") as directory:
            p = Path(directory)
            store = SharedKitStore(p / "library.sqlite3", p / "unavailable/backup.sqlite3")
            result = store.publish("QA", "", self.project, b"<svg/>", Identity("101", "Owner", "user"))
            self.assertEqual(result["backup"]["status"], "warning")
            self.assertTrue(store.get(result["kit"]["id"], Identity("101", "Owner", "user")))

    def test_backup_copies_closed_local_sqlite_and_cleans_failed_transfer(self):
        with tempfile.TemporaryDirectory(prefix="zzlab-shared-transfer-qa-") as directory:
            p = Path(directory)
            remote = p / "simulated-nas"
            local = p / "local-snapshots"
            remote.mkdir();local.mkdir()
            store = SharedKitStore(p / "library.sqlite3", remote / "backup.sqlite3")
            owner = Identity("101", "Owner", "user")
            original_connect = sqlite3.connect
            original_tempdir = tempfile.TemporaryDirectory
            original_copy = shared_kits.shutil.copyfileobj
            connections = []
            handles = []
            def local_connect(filename, *args, **kwargs):
                path = Path(filename).resolve()
                self.assertFalse(path.is_relative_to(remote.resolve()), "SQLite must never open the NAS destination")
                connections.append(path)
                handle = original_connect(filename, *args, **kwargs)
                handles.append(handle)
                return handle
            def local_directory(*args, **kwargs):
                return original_tempdir(*args, **{**kwargs, "dir": local})
            def assert_closed():
                for handle in handles:
                    with self.assertRaises(sqlite3.ProgrammingError, msg="close all SQLite handles before transferring bytes"):
                        handle.execute("SELECT 1")
            def checked_copy(incoming, output, **kwargs):
                assert_closed()
                return original_copy(incoming, output, **kwargs)
            with patch.object(shared_kits.sqlite3, "connect", side_effect=local_connect), patch.object(shared_kits.tempfile, "TemporaryDirectory", side_effect=local_directory), patch.object(shared_kits.shutil, "copyfileobj", side_effect=checked_copy):
                first = store.publish("first", "", self.project, b"<svg/>", owner)
                self.assertEqual(first["backup"]["status"], "ok")
                previous = (remote / "backup.sqlite3").read_bytes()
                def broken_copy(incoming, output, **kwargs):
                    assert_closed()
                    output.write(incoming.read(128))
                    raise OSError("simulated interrupted network transfer")
                with patch.object(shared_kits.shutil, "copyfileobj", side_effect=broken_copy):
                    second = store.publish("second", "", self.project, b"<svg/>", owner)
                self.assertEqual(second["backup"]["status"], "warning")
                self.assertTrue(store.get(second["kit"]["id"], owner))
            self.assertEqual((remote / "backup.sqlite3").read_bytes(), previous, "failed transfer must preserve last complete backup")
            self.assertEqual(list(local.iterdir()), [], "local snapshot directories are cleaned")
            self.assertEqual([f.name for f in remote.iterdir()], ["backup.sqlite3"], "partial remote transfer files are cleaned")
            self.assertTrue(any(path.name == "snapshot.sqlite3" for path in connections))
            restored = p / "restored-local.sqlite3"
            restored.write_bytes(previous)
            with original_connect(restored) as database:
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(database.execute("SELECT COUNT(*) FROM shared_kits").fetchone()[0], 1)

    def test_http_real_project_owner_boundary_and_spoof_rejection(self):
        with tempfile.TemporaryDirectory(prefix="zzlab-shared-http-qa-") as directory:
            p = Path(directory)
            config = Config(catalog=ROOT / "catalog.json", assets=ROOT / "assets", static=ROOT / "static",
                            auth_token="qa-temporary-internal-token", shared_db=p / "library.sqlite3", shared_backup=p / "backup.sqlite3")
            server = create_server(config, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def request(method, route, payload=None, user="101", role="user", authenticated=True):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
                headers = {"Content-Type": "application/json"}
                if authenticated:
                    headers.update({"X-ZZLAB-Internal-Token": config.auth_token, "X-ZZLAB-Authenticated": "true", "X-ZZLAB-Role": role, "X-ZZLAB-User-ID": user, "X-ZZLAB-User": "QA Owner"})
                data = None if payload is None else json.dumps(payload).encode()
                connection.request(method, route, body=data, headers=headers)
                response = connection.getresponse(); body = response.read(); status = response.status
                connection.close()
                return status, body
            try:
                self.assertEqual(request("GET", "/api/shared-kits", authenticated=False)[0], 401)
                self.assertEqual(request("GET", "/api/shared-kits", role="readonly")[0], 403)
                body = {"name": "Independent QA", "description": "Temporary test only", "project": self.project}
                self.assertEqual(request("POST", "/api/shared-kits", {**body, "author_id": "999"})[0], 400)
                status, response = request("POST", "/api/shared-kits", body)
                self.assertEqual(status, 201, response)
                kid = json.loads(response)["kit"]["id"]
                status, downloaded = request("GET", f"/api/shared-kits/{kid}/project", user="102")
                self.assertEqual(status, 200);self.assertEqual(json.loads(downloaded), self.project)
                self.assertEqual(request("POST", f"/api/shared-kits/{kid}/unpublish", {}, user="102")[0], 403)
                self.assertEqual(request("POST", f"/api/shared-kits/{kid}/unpublish", {})[0], 200)
                self.assertEqual(request("GET", f"/api/shared-kits/{kid}/project", user="102")[0], 404)
                self.assertEqual(request("POST", f"/api/shared-kits/{kid}/restore", {}, user="999", role="admin")[0], 200)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SharedCatalogQA)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"passed": result.wasSuccessful(), "tests": result.testsRun,
              "catalogVersion": SharedCatalogQA.catalog["version"], "scope": "real catalog + JS codec + ephemeral loopback HTTP + temporary SQLite/backup only",
              "productionRecordsCreated": 0, "projectSha256": hashlib.sha256(json.dumps(SharedCatalogQA.project, sort_keys=True).encode()).hexdigest(),
              "reviewedSourceSha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("shared_kits.py", "app.py", "static/shared-project.js", "static/project-file.js")},
              "backupChecks": ["SQLite only opens local files", "all SQLite handles close before byte transfer", "failed transfer preserves prior complete backup", "local snapshots and partial remote files cleaned", "copied-back backup integrity_check is ok"],
              "resolvedFindings": ["listing now selects summary columns without BLOBs", "NAS receives a closed local SQLite snapshot by ordinary file copy, avoiding SMB SQLite locking"]}
    (ROOT / "data_evidence/shared_catalog_independent_qa.json").write_text(json.dumps(report, indent=2) + "\n")
    sys.exit(0 if result.wasSuccessful() else 1)
