"""A catalog-only optical placeholder remains portable without inventing physics."""
import copy
import json
import unittest

from bom import aggregate
from layout import layout_json
from optics_settings import normalize_optics
from test_layout import layout_fixture, request


class CatalogOpticsPersistenceTests(unittest.TestCase):
    def test_unsupported_optics_round_trip_without_procurement_changes(self):
        catalog = layout_fixture()
        data = request()
        before = aggregate(catalog, data)
        settings = {"elementType": "unsupported", "inserted": True, "configured": True,
                    "surfaceAngleDeg": 90, "clearApertureMm": 25.4}
        self.assertEqual(normalize_optics(settings), settings)
        data["layout"]["instances"][0]["optics"] = copy.deepcopy(settings)
        result = aggregate(catalog, data)
        self.assertEqual(result["layout"]["instances"][0]["optics"], settings)
        reopened = aggregate(catalog, json.loads(layout_json(result)))
        self.assertEqual(reopened["layout"], result["layout"])
        for key in ("items", "lubang", "manufacturing", "standard", "totals", "layoutValidation"):
            self.assertEqual(result[key], before[key])
