import hashlib
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from scripts.export_valuation_research import component_total, source_key, verify_report_hash


class IndependentComponentChecks(unittest.TestCase):
    def test_legacy_windows_newline_translation_is_reversible_but_numeric_edits_fail(self):
        original = b"<html>EPS 0.60\r\nQuarter ended 2016-09-30</html>"
        digest = hashlib.sha256(original).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_bytes(original.replace(b"\n", b"\r\n"))
            self.assertIn("legacy Windows", verify_report_hash(path, digest))
            path.write_bytes(original.replace(b"0.60", b"0.90"))
            with self.assertRaisesRegex(AssertionError, "hash mismatch"):
                verify_report_hash(path, digest)

    def setUp(self):
        self.components = [
            {"start": "2025-01-01", "end": "2025-03-31", "filedAt": "2025-05-01", "reportedEps": 2, "splitAdjustment": 2, "eps": 1, "accession": "q1"},
            {"start": "2025-04-01", "end": "2025-06-30", "filedAt": "2025-08-01", "reportedEps": 4, "splitAdjustment": 2, "eps": 2, "accession": "q2"},
            {"start": "2025-07-01", "end": "2025-09-30", "filedAt": "2025-11-01", "reportedEps": 3, "splitAdjustment": 1, "eps": 3, "accession": "q3"},
            {"start": "2025-10-01", "end": "2025-12-31", "filedAt": "2026-02-01", "reportedEps": 4, "splitAdjustment": 1, "eps": 4, "accession": "q4"},
        ]

    def test_independent_sum_matches_original_values_and_split_adjustments(self):
        sources = {source_key(row) for row in self.components}
        self.assertEqual(component_total(self.components, date(2026, 2, 2), sources), 10)

    def test_corrupt_adjustment_and_missing_original_are_rejected(self):
        changed = deepcopy(self.components)
        changed[0]["eps"] = 2
        with self.assertRaisesRegex(AssertionError, "split factor"):
            component_total(changed, date(2026, 2, 2))
        with self.assertRaisesRegex(AssertionError, "original SEC"):
            component_total(self.components, date(2026, 2, 2), set())

    def test_future_earnings_and_quarter_gaps_fail(self):
        with self.assertRaisesRegex(AssertionError, "before availability"):
            component_total(self.components, date(2026, 2, 1))
        changed = deepcopy(self.components)
        changed[-1]["start"] = "2025-10-02"
        with self.assertRaisesRegex(AssertionError, "gap or overlap"):
            component_total(changed, date(2026, 2, 2))


if __name__ == "__main__":
    unittest.main()