"""The complete atlas follows existing CAD access and a verified release."""
import hashlib
import json
import unittest

import test_shared_kits as shared_tests
import test_guest_access as guest_tests


class MachiningAtlasHTTPTests(unittest.TestCase):
    setUpClass = classmethod(shared_tests.SharedHTTPTests.setUpClass.__func__)
    tearDownClass = classmethod(shared_tests.SharedHTTPTests.tearDownClass.__func__)
    call = guest_tests.GuestAccessHTTPTests.call

    def setUp(self):
        self.atlas = self.assets / "drawings" / "atlas"
        self.atlas.mkdir(parents=True, exist_ok=True)
        self.pdf = b"%PDF synthetic HTTP fixture; no production drawings"
        (self.atlas / "atlas-b6.pdf").write_bytes(self.pdf)
        self.receipt = {"filename": "atlas-b6.pdf",
                        "sha256": hashlib.sha256(self.pdf).hexdigest(),
                        "catalogSha256": hashlib.sha256(self.catalog.read_bytes()).hexdigest()}
        self.save_receipt()

    def save_receipt(self):
        (self.atlas / "current.json").write_text(json.dumps(self.receipt))

    def test_authenticated_members_and_readonly_get_exact_attachment(self):
        for role in ("readonly", "user", "admin"):
            status, body, headers = self.call("GET", "/api/machining-atlas", role=role)
            self.assertEqual((status, body), (200, self.pdf))
            self.assertEqual(headers["Content-Type"], "application/pdf")
            self.assertIn("attachment", headers["Content-Disposition"])

    def test_existing_login_requirement_cannot_be_bypassed(self):
        for role, token in (("guest", "test-secret"), ("user", None), ("user", "wrong")):
            self.assertEqual(self.call("GET", "/api/machining-atlas", role=role, token=token)[0], 401)
        self.assertEqual(self.call("GET", "/assets/drawings/atlas/atlas-b6.pdf", role="readonly")[0], 404)

    def test_new_catalog_or_modified_pdf_is_not_served_as_current(self):
        self.receipt["catalogSha256"] = "0" * 64
        self.save_receipt()
        self.assertEqual(self.call("GET", "/api/machining-atlas", role="user")[0], 503)
        self.receipt["catalogSha256"] = hashlib.sha256(self.catalog.read_bytes()).hexdigest()
        self.save_receipt()
        (self.atlas / "atlas-b6.pdf").write_bytes(self.pdf + b"changed")
        self.assertEqual(self.call("GET", "/api/machining-atlas", role="user")[0], 503)

    def test_client_cannot_select_another_file(self):
        self.assertEqual(self.call("GET", "/api/machining-atlas?path=other.pdf", role="user")[0], 400)
        self.receipt["filename"] = "../../plate.pdf"
        self.save_receipt()
        self.assertEqual(self.call("GET", "/api/machining-atlas", role="user")[0], 503)


if __name__ == "__main__":
    unittest.main()
