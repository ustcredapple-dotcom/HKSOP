"""Contract and JSON boundary tests; no DB, network, CAD, or source edits."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from optical_interaction import validate_optical_interaction, validate_kit_optical_interaction


FIXTURES = Path(__file__).parent / "fixtures" / "optical_interaction_validation.json"


class OpticalInteractionValidationTests(unittest.TestCase):
    def test_shared_json_fixtures(self):
        fixtures = json.loads(FIXTURES.read_text())
        for case in fixtures["cases"]:
            with self.subTest(case=case["id"]):
                before = copy.deepcopy(case["program"])
                if case["valid"]:
                    result = validate_optical_interaction(case["program"])
                    self.assertEqual(result, case.get("normalized", before))
                    self.assertIsNot(result, case["program"])
                else:
                    with self.assertRaises(ValueError):
                        validate_optical_interaction(case["program"])
                self.assertEqual(case["program"], before)

    def test_non_json_numbers_fail_closed(self):
        base = {"format": "zzlab-optical-interaction", "version": 1,
                "model": "source", "emission": {}}
        for val in (float("nan"), float("inf"), float("-inf"), 10 ** 1000):
            with self.subTest(value=repr(val)):
                item = dict(base, heightToleranceMm=val)
                with self.assertRaises(ValueError):
                    validate_optical_interaction(item)

    def test_non_string_keys_and_non_json_containers_fail(self):
        base = {"format": "zzlab-optical-interaction", "version": 1,
                "model": "source", "emission": {}}
        for value in (dict(base, emission=[]), {**base, 1: "unknown"}, tuple(base), set(base)):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    validate_optical_interaction(value)

    def test_output_has_no_aliases_to_nested_program(self):
        program = {"format": "zzlab-optical-interaction", "version": 1,
                   "model": "planar", "onNoMatch": "pass", "inputs": [
                       {"id": "main", "steps": [{"op": "mirror", "mirror": {
                           "mode": "data", "samples": [{"wavelengthNm": 532, "incidenceAngleDeg": 45,
                           "reflectanceP": .9, "reflectanceS": .95, "phaseDifferenceDeg": None}]}}]}]}
        result = validate_optical_interaction(program)
        result["inputs"][0]["steps"][0]["mirror"]["samples"][0]["reflectanceP"] = .1
        self.assertEqual(program["inputs"][0]["steps"][0]["mirror"]["samples"][0]["reflectanceP"], .9)

    def test_missing_measurements_are_not_filled(self):
        program = {"format": "zzlab-optical-interaction", "version": 1,
                   "model": "planar", "onNoMatch": "block", "inputs": [
                       {"id": "main", "steps": [{"op": "mirror"}, {"op": "lens"},
                                                   {"op": "waveplate"}, {"op": "coupler"}]}]}
        self.assertEqual(validate_optical_interaction(program), program)


class OpticalInteractionCatalogIntegrationTests(unittest.TestCase):
    """Exercise the actual catalog and request API validators with synthetic rows."""

    @staticmethod
    def program():
        return {"format": "zzlab-optical-interaction", "version": 1, "model": "planar",
                "onNoMatch": "block", "inputs": [{"id": "main", "steps": [{"op": "pass"}]}]}

    def test_catalog_keeps_trusted_program_and_does_not_change_bom_or_project(self):
        from bom import aggregate, validate_catalog
        from layout import layout_json
        from test_layout import layout_fixture, request

        original = layout_fixture()
        original["kits"][0]["layout"]["opticalType"] = "mirror"
        baseline = aggregate(original, request())
        candidate = copy.deepcopy(original)
        candidate["kits"][0]["layout"]["opticalInteraction"] = self.program()
        normalized = validate_catalog(candidate)
        self.assertEqual(normalized["kits"][0]["layout"]["opticalInteraction"], self.program())
        self.assertIsNot(normalized["kits"][0]["layout"]["opticalInteraction"],
                         candidate["kits"][0]["layout"]["opticalInteraction"])
        result = aggregate(normalized, request())
        for key in ("items", "lubang", "manufacturing", "standard", "totals", "layoutValidation", "layout"):
            self.assertEqual(result[key], baseline[key], key)
        self.assertNotIn(b"opticalInteraction", layout_json(result))

    def test_invalid_trusted_program_fails_catalog_api_closed(self):
        from bom import APIError, validate_catalog
        from test_layout import layout_fixture

        cases = json.loads(FIXTURES.read_text())["cases"]
        for case in cases:
            if case["valid"]:
                continue
            with self.subTest(case=case["id"]):
                candidate = layout_fixture()
                candidate["kits"][0]["layout"]["opticalType"] = "mirror"
                candidate["kits"][0]["layout"]["opticalInteraction"] = case["program"]
                with self.assertRaises(APIError) as caught:
                    validate_catalog(candidate)
                self.assertEqual(caught.exception.code, "catalog_invalid")
                self.assertEqual(caught.exception.status, 503)

    def test_request_instances_cannot_inject_or_override_catalog_language(self):
        from bom import APIError, aggregate, validate_catalog
        from test_layout import layout_fixture, request

        catalog = layout_fixture()
        catalog["kits"][0]["layout"]["opticalType"] = "mirror"
        catalog["kits"][0]["layout"]["opticalInteraction"] = self.program()
        catalog = validate_catalog(catalog)
        for nested in (False, True):
            with self.subTest(nestedInOptics=nested):
                payload = request()
                instance = payload["layout"]["instances"][0]
                if nested:
                    instance["optics"] = {"elementType": "empty", "inserted": False,
                                          "opticalInteraction": self.program()}
                else:
                    instance["opticalInteraction"] = self.program()
                with self.assertRaises(APIError):
                    aggregate(catalog, payload)

    def test_current_legacy_catalog_preserves_every_original_value(self):
        from bom import validate_catalog

        raw = json.loads((Path(__file__).resolve().parents[1] / "catalog.json").read_text())
        before = copy.deepcopy(raw)
        # Catalog validation historically adds empty optional component fields.
        # The new opt-in language must not rewrite any original field or geometry.
        with patch("optical_interaction.validate_optical_interaction", wraps=validate_optical_interaction) as hook:
            normalized = validate_catalog(raw)
        self.assertEqual(raw, before)
        self.assertEqual(hook.call_count, sum("opticalInteraction" in k.get("layout", {}) for k in raw["kits"]))
        for key, value in before.items():
            if key in ("components", "kits"):
                for component, result in zip(value, normalized[key]):
                    self.assertEqual({k: result[k] for k in component}, component, component["id"])
            else:
                self.assertEqual(normalized[key], value, key)

    def test_kit_context_requires_explicit_compatible_type_and_no_3d_assembly(self):
        planar = self.program()
        source = {"format": "zzlab-optical-interaction", "version": 1, "model": "source", "emission": {}}
        for kind in ("empty", "mirror", "dichroic", "pbs", "waveplate", "lens", "coupler", "unsupported"):
            with self.subTest(validType=kind):
                self.assertEqual(validate_kit_optical_interaction({"opticalType": kind, "opticalInteraction": planar}), planar)
        self.assertEqual(validate_kit_optical_interaction({"opticalType": "source", "opticalInteraction": source,
                                                         "opticalAxisHeightMm": None}), source)
        for context in ({}, {"opticalType": "unknown"}, {"opticalType": True}, {"opticalType": "source"},
                        {"opticalType": "mirror", "opticalAssembly": {}},
                        {"opticalType": "mirror", "opticalAssembly": None}):
            with self.subTest(context=context), self.assertRaises(ValueError):
                validate_kit_optical_interaction({**context, "opticalInteraction": planar})
        for kind in ("empty", "mirror", "dichroic", "pbs", "waveplate", "lens", "coupler", "unsupported"):
            with self.subTest(invalidSourceType=kind), self.assertRaises(ValueError):
                validate_kit_optical_interaction({"opticalType": kind, "opticalInteraction": source})
        for context in (None, {}, {"opticalAssembly": {}}, {"opticalType": "legacy-unknown"}):
            self.assertIsNone(validate_kit_optical_interaction(context))

    def test_incompatible_context_is_rejected_at_catalog_api_boundary(self):
        from bom import APIError, validate_catalog
        from test_layout import layout_fixture

        source = {"format": "zzlab-optical-interaction", "version": 1, "model": "source", "emission": {}}
        for context in ({"opticalInteraction": self.program()},
                        {"opticalInteraction": source, "opticalType": "coupler"},
                        {"opticalInteraction": self.program(), "opticalType": "source"},
                        {"opticalInteraction": self.program(), "opticalType": "mirror", "opticalAssembly": {}}):
            with self.subTest(context=context):
                catalog = layout_fixture()
                catalog["kits"][0]["layout"].update(context)
                with self.assertRaises(APIError) as caught:
                    validate_catalog(catalog)
                self.assertEqual(caught.exception.code, "catalog_invalid")


if __name__ == "__main__":
    unittest.main()
