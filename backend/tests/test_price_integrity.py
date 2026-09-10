import unittest
from datetime import date, timedelta

from backend.providers import check_price_revision


class PriceRevisionTests(unittest.TestCase):
    def setUp(self):
        self.prices = [{"date": (date(2024, 5, 1) + timedelta(days=index)).isoformat(), "close": 100.0} for index in range(25)]

    def test_unknown_split_or_rebasing_withdraws_valuation(self):
        changed = [{**row, "close": 50} for row in self.prices]
        with self.assertRaisesRegex(ValueError, "重标定"):
            check_price_revision(changed, {"prices": self.prices, "splitPolicy": []}, [])

    def test_configured_new_split_explains_historical_rebasing(self):
        changed = [{**row, "close": 10} for row in self.prices]
        check_price_revision(changed, {"prices": self.prices, "splitPolicy": []}, [["2024-06-10", 10]])

    def test_legacy_cache_and_one_corrected_close_do_not_false_alarm(self):
        changed = [{**row, "close": 100.01} for row in self.prices]
        changed[-1]["close"] = 101
        check_price_revision(changed, {"prices": self.prices}, [["2021-07-20", 4]])


if __name__ == "__main__":
    unittest.main()