"""Meaningful protocol boundaries: lossless migration, trust gates and failed adoption rollback."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("library_protocol_tool", ROOT / "tools" / "library.py")
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


class LibraryProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.source = self.root / "library"
        self.component = {"id": "part-a", "name": "已购器件", "unit": "个", "kind": "standard", "sourceUrl": "https://example.org/product"}
        self.catalog = {"version": "test-1", "updatedAt": "2026-10-05", "categories": [{"id": "sample", "label": "测试"}],
                        "components": [self.component], "kits": [], "registeredBoards": [], "notes": ["原样保留"]}
        lib.atomic_write(self.root / "catalog.json", lib.json_bytes(self.catalog))
        lib.make_source(self.catalog, self.source, lib.sha(lib.json_bytes(self.catalog)))
        self.package = Path(self.temp.name) / "package"
        self.package.mkdir()
        self.part_b = {**self.component, "id": "part-b", "name": "新增采购器件"}
        lib.atomic_write(self.package / "records" / "part-b.json", lib.json_bytes(self.part_b))
        review = b"Actual fixture review: purchased part only; geometry and optical behavior are not applicable."
        lib.atomic_write(self.package / "evidence" / "review.txt", review)
        self.package_spec = {"protocolVersion": lib.PROTOCOL_VERSION, "packageId": "qa-add-b", "baseCatalogSha256": lib.sha(lib.json_bytes(self.catalog)),
                             "records": [{"type": "components", "id": "part-b", "path": "records/part-b.json"}], "assets": [],
                             "metadataPatch": {"version": "test-2"},
                             "reviews": {key: {"status": "reviewed" if key in ("sourceReviewed", "bomReviewed") else "not-applicable", "reviewer": "unit-test fixture",
                                               "reason": "Purchased component; fixture explicitly has no geometry or optical interaction.",
                                               "evidence": [{"path": "evidence/review.txt", "sha256": lib.sha(review)}]}
                                         for key in ("sourceReviewed", "geometryReviewed", "interactionReviewed", "bomReviewed")}}
        self.write_package()

    def write_package(self):
        lib.atomic_write(self.package / "package.json", lib.json_bytes(self.package_spec))

    def make_stage(self):
        stage = Path(self.temp.name) / "stage"
        lib.stage_package(self.package, self.source, self.root, stage)
        return stage

    def add_pdf(self):
        pdf = b"%PDF-1.4\nfixture source evidence only\n%%EOF\n"
        lib.atomic_write(self.package / "payload" / "part-b.pdf", pdf)
        self.part_b["drawingPath"] = "drawings/qa-part-b.pdf"
        lib.atomic_write(self.package / "records" / "part-b.json", lib.json_bytes(self.part_b))
        self.package_spec["assets"] = [{"root": "assets", "path": self.part_b["drawingPath"], "source": "payload/part-b.pdf", "sha256": lib.sha(pdf)}]
        self.write_package()

    def test_mechanical_carrier_keeps_no_optical_datum(self):
        carrier = {"id": "stage", "opticalSlots": [], "layout": {
            "mechanicalOnly": True, "opticalCenterMm": None,
            "opticalDatumVerified": False, "placementAllowed": False}}
        lib.validate_new_record("kits", carrier)
        for key, value in [("opticalType", "mirror"), ("nominalOpticalHeightMm", 62.5),
                           ("opticalInteraction", {"format": "anything"}),
                           ("opticalDatumVerified", True)]:
            invalid = copy.deepcopy(carrier)
            invalid["layout"][key] = value
            with self.assertRaisesRegex(lib.LibraryError, "mechanical-only"):
                lib.validate_new_record("kits", invalid)
        del carrier["layout"]["mechanicalOnly"]
        with self.assertRaisesRegex(lib.LibraryError, "opticalType"):
            lib.validate_new_record("kits", carrier)

    def test_current_catalog_round_trip_is_byte_exact(self):
        actual = lib.load_source(ROOT / "library")
        self.assertEqual(lib.json_bytes(actual), (ROOT / "catalog.json").read_bytes())
        manifest = lib.read_json(ROOT / "library" / "manifest.json")
        self.assertEqual([len(actual[key]) for key in ("components", "kits", "registeredBoards")],
                         [len(manifest["recordOrder"][group]) for group in ("components", "kits", "boards")])

    def test_reimport_is_not_a_silent_update(self):
        with self.assertRaisesRegex(lib.LibraryError, "already initialized"):
            lib.make_source(self.catalog, self.source, "fake")

    def test_manifest_does_not_ignore_unlisted_records(self):
        lib.atomic_write(self.source / "records" / "components" / "part-b.json", lib.json_bytes(self.part_b))
        with self.assertRaisesRegex(lib.LibraryError, "Unlisted/missing"):
            lib.load_source(self.source)

    def test_duplicate_json_keys_and_nonfinite_numbers_fail(self):
        for content in ('{"id":"a","id":"b"}', '{"x":NaN}'):
            path = Path(self.temp.name) / "bad.json"
            path.write_text(content)
            with self.assertRaises(lib.LibraryError):
                lib.read_json(path)

    def test_package_dry_run_does_not_write_source_runtime_or_assets(self):
        before = lib.source_state_sha(self.source)
        runtime = (self.root / "catalog.json").read_bytes()
        plan = lib.stage_package(self.package, self.source, self.root)
        self.assertFalse(plan["applied"])
        self.assertEqual(lib.source_state_sha(self.source), before)
        self.assertEqual((self.root / "catalog.json").read_bytes(), runtime)
        self.assertFalse((self.root / "assets").exists())

    def test_stage_adopt_requires_explicit_apply_and_leaves_runtime_unchanged(self):
        self.add_pdf()
        stage = self.make_stage()
        before = lib.source_state_sha(self.source)
        preview = lib.adopt_stage(stage, self.source, self.root)
        self.assertFalse(preview["applied"])
        self.assertEqual(lib.source_state_sha(self.source), before)
        receipt = lib.adopt_stage(stage, self.source, self.root, True)
        self.assertTrue(receipt["applied"])
        self.assertEqual(lib.load_source(self.source)["version"], "test-2")
        self.assertTrue((self.root / "assets" / self.part_b["drawingPath"]).is_file())
        self.assertEqual(lib.read_json(self.root / "catalog.json")["version"], "test-1")
        lib.validate_review_archive(self.source)
        self.assertTrue((Path(receipt["backup"]) / "receipt.json").is_file())

    def test_changed_source_prevents_adoption(self):
        stage = self.make_stage()
        current = lib.read_json(self.source / "records" / "components" / "part-a.json")
        current["name"] = "someone else edited this"
        lib.atomic_write(self.source / "records" / "components" / "part-a.json", lib.json_bytes(current))
        with self.assertRaisesRegex(lib.LibraryError, "source/review files changed"):
            lib.adopt_stage(stage, self.source, self.root, True)
        self.assertFalse((self.source / ".adopt.lock").exists())

    def test_concurrent_adoption_lock_blocks_writes(self):
        stage = self.make_stage()
        (self.source / ".adopt.lock").write_text("another process")
        with self.assertRaisesRegex(lib.LibraryError, "Another library adoption"):
            lib.adopt_stage(stage, self.source, self.root, True)

    def test_failed_adoption_rolls_back_source_assets_reports_reviews(self):
        self.add_pdf()
        prior_report = b'{"old":"report"}\n'
        lib.atomic_write(self.source / "generated" / "sentinel.json", prior_report)
        stage = self.make_stage()
        before = lib.source_state_sha(self.source)
        original_write = lib.atomic_write
        triggered = []
        def fail_after_assets(path, data):
            if Path(path) == self.source / "manifest.json" and not triggered:
                triggered.append(True)
                raise OSError("simulated disk write failure")
            return original_write(path, data)
        with patch.object(lib, "atomic_write", side_effect=fail_after_assets):
            with self.assertRaisesRegex(OSError, "simulated"):
                lib.adopt_stage(stage, self.source, self.root, True)
        self.assertEqual(lib.source_state_sha(self.source), before)
        self.assertEqual((self.source / "generated" / "sentinel.json").read_bytes(), prior_report)
        self.assertFalse((self.root / "assets" / self.part_b["drawingPath"]).exists())
        self.assertFalse((self.source / "reviews").exists())
        self.assertFalse((self.source / ".adopt.lock").exists())

    def test_existing_id_requires_replace_and_previous_hash(self):
        self.package_spec["records"][0].update(id="part-a")
        lib.atomic_write(self.package / "records" / "part-b.json", lib.json_bytes(self.component))
        self.write_package()
        with self.assertRaisesRegex(lib.LibraryError, "cannot overwrite"):
            lib.stage_package(self.package, self.source, self.root)
        self.package_spec["records"][0]["mode"] = "replace"
        self.write_package()
        with self.assertRaisesRegex(lib.LibraryError, "old record SHA"):
            lib.stage_package(self.package, self.source, self.root)
        self.package_spec["records"][0]["previousSha256"] = lib.sha(lib.json_bytes(self.component))
        self.write_package()
        self.assertEqual(lib.stage_package(self.package, self.source, self.root)["records"][0]["mode"], "replace")

    def test_asset_traversal_and_symlink_escape_fail(self):
        self.add_pdf()
        self.package_spec["assets"][0]["path"] = "drawings/../../app.py"
        self.write_package()
        with self.assertRaisesRegex(lib.LibraryError, "Unsafe"):
            lib.stage_package(self.package, self.source, self.root)
        outside = Path(self.temp.name) / "outside.pdf"
        outside.write_bytes(b"%PDF-1.4\n")
        (self.package / "escape.pdf").symlink_to(outside)
        self.package_spec["assets"][0].update(path=self.part_b["drawingPath"], source="escape.pdf", sha256=lib.file_sha(outside))
        self.write_package()
        with self.assertRaisesRegex(lib.LibraryError, "escapes allowed root"):
            lib.stage_package(self.package, self.source, self.root)

    def test_review_boolean_or_unhashed_statement_is_rejected(self):
        self.package_spec["reviews"]["geometryReviewed"] = True
        self.write_package()
        with self.assertRaisesRegex(lib.LibraryError, "Invalid review"):
            lib.stage_package(self.package, self.source, self.root)

    def test_changed_review_evidence_prevents_stage(self):
        (self.package / "evidence" / "review.txt").write_text("Changed after signing")
        with self.assertRaisesRegex(lib.LibraryError, "changed review evidence"):
            lib.stage_package(self.package, self.source, self.root)

    def test_new_kit_cannot_silently_fall_back_to_lens(self):
        kit = {"id": "unknown-optic", "layout": {"placementAllowed": False}}
        with self.assertRaisesRegex(lib.LibraryError, "explicitly declare"):
            lib.validate_new_record("kits", kit)
        kit["layout"]["opticalType"] = "unsupported"
        lib.validate_new_record("kits", kit)

    def test_package_rejects_unchanged_catalog_version(self):
        self.package_spec["metadataPatch"] = {}
        self.write_package()
        with self.assertRaisesRegex(lib.LibraryError, "must change"):
            lib.stage_package(self.package, self.source, self.root)

    def test_table_placement_with_evidenced_shape_does_not_claim_mounting(self):
        catalog = lib.read_json(ROOT / "catalog.json")
        for identity in ("laser-556nm", "laser-935nm"):
            kit = copy.deepcopy(next(row for row in catalog["kits"] if row["id"] == identity))
            self.assertEqual(kit["layout"]["mountingHoleOffsetsMm"], [])
            lib.validate_new_record("kits", kit)
            kit["layout"].pop("mountingConfirmed", None)
            kit["layout"].get("calibration", {}).pop("mountingPatternConfirmed", None)
            with self.assertRaisesRegex(lib.LibraryError, "unconfirmed-mounting"):
                lib.validate_new_record("kits", kit)

    def test_assets_are_hashed_before_import(self):
        self.add_pdf()
        (self.package / "payload" / "part-b.pdf").write_bytes(b"%PDF-1.4\nchanged\n")
        with self.assertRaisesRegex(lib.LibraryError, "SHA mismatch"):
            lib.stage_package(self.package, self.source, self.root)

    def test_receipt_failure_rolls_back_after_all_other_source_writes(self):
        self.add_pdf()
        stage = self.make_stage()
        before = lib.source_state_sha(self.source)
        original_write = lib.atomic_write
        def fail_receipt(path, data):
            if Path(path).name == "receipt.json":
                raise OSError("simulated receipt failure")
            return original_write(path, data)
        with patch.object(lib, "atomic_write", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "receipt failure"):
                lib.adopt_stage(stage, self.source, self.root, True)
        self.assertEqual(lib.source_state_sha(self.source), before)
        self.assertFalse((self.source / "reviews").exists())
        self.assertFalse((self.source / "generated").exists())
        self.assertFalse((self.root / "assets" / self.part_b["drawingPath"]).exists())

    def test_staged_plan_cannot_escape_backup_directory(self):
        stage = self.make_stage()
        plan = lib.read_json(stage / "stage-plan.json")
        plan["packageId"] = "../../escape"
        lib.atomic_write(stage / "stage-plan.json", lib.json_bytes(plan))
        with self.assertRaisesRegex(lib.LibraryError, "ID must be portable"):
            lib.adopt_stage(stage, self.source, self.root, True)

    def test_existing_asset_replacement_is_restored_on_failure(self):
        self.add_pdf()
        previous = b"%PDF-1.4\nold fixture\n"
        target = self.root / "assets" / self.part_b["drawingPath"]
        lib.atomic_write(target, previous)
        self.package_spec["assets"][0].update(mode="replace", previousSha256=lib.sha(previous))
        self.write_package()
        stage = self.make_stage()
        original_write = lib.atomic_write
        def fail_receipt(path, data):
            if Path(path).name == "receipt.json":
                raise OSError("simulate final write failure")
            return original_write(path, data)
        with patch.object(lib, "atomic_write", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                lib.adopt_stage(stage, self.source, self.root, True)
        self.assertEqual(target.read_bytes(), previous)

    def test_production_index_guard_requires_index_and_checks_runtime_sources(self):
        with self.assertRaisesRegex(lib.LibraryError, "Required derived index"):
            lib.check_derived_indexes(self.catalog, self.root, self.source, required=True)
        runtime = self.root / "probe-runtime.py"
        runtime.write_text("fixture_version = 1\n")
        index = {"sourceCatalogSha256": lib.sha(lib.json_bytes(self.catalog)), "kits": [], "registeredBoards": [],
                 "derivation": {"runtimeFiles": [{"path": runtime.name, "sha256": lib.file_sha(runtime)}]}}
        lib.atomic_write(self.source / "generated" / "interaction-index.json", lib.json_bytes(index))
        checked = lib.check_derived_indexes(self.catalog, self.root, self.source, required=True)
        self.assertEqual(len(checked), 1)
        runtime.write_text("fixture_version = 2\n")
        with self.assertRaisesRegex(lib.LibraryError, "runtime source changed"):
            lib.check_derived_indexes(self.catalog, self.root, self.source, required=True)

    def test_production_index_cannot_omit_existing_dsl_or_generator_source(self):
        runtime = self.root / "probe-runtime.py"
        runtime.write_text("fixture_version = 1\n")
        (self.root / "optical_interaction.py").write_text("dsl_version = 1\n")
        index = {"sourceCatalogSha256": lib.sha(lib.json_bytes(self.catalog)), "kits": [], "registeredBoards": [],
                 "derivation": {"runtimeFiles": [{"path": runtime.name, "sha256": lib.file_sha(runtime)}]}}
        lib.atomic_write(self.source / "generated" / "interaction-index.json", lib.json_bytes(index))
        with self.assertRaisesRegex(lib.LibraryError, "critical source fingerprints"):
            lib.check_derived_indexes(self.catalog, self.root, self.source, required=True)

    def test_script_svg_is_rejected(self):
        path = Path(self.temp.name) / "bad.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        with self.assertRaisesRegex(lib.LibraryError, "Active"):
            lib.verify_new_asset(path, "static/topviews/bad.svg")


if __name__ == "__main__":
    unittest.main()
