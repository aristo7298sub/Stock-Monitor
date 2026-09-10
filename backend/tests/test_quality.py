import unittest
from datetime import date

from backend.quality import annual_summary, financial_quality, instant_fact


class QualityTests(unittest.TestCase):
    def test_instant_facts_require_same_date_and_actual_disclosure(self):
        document = {"facts": {"us-gaap": {"StockholdersEquity": {"units": {"USD": [
            {"end": "2026-06-30", "filed": "2026-07-30", "val": 100, "form": "10-Q"},
            {"end": "2026-06-30", "filed": "2026-10-30", "val": 200, "form": "10-Q"},
        ]}}}}}
        self.assertEqual(instant_fact(document, ("StockholdersEquity",), date(2026, 6, 30), date(2026, 9, 9))["val"], 100)
        self.assertIsNone(instant_fact(document, ("StockholdersEquity",), date(2026, 3, 31), date(2026, 9, 9)))

    def test_five_year_growth_requires_six_consecutive_annual_endpoints(self):
        history = [{"periodEnd": f"{2020 + index}-12-31", "revenue": 100 * 1.1 ** index, "netIncome": 5, "freeCashFlow": 2} for index in range(6)]
        result = annual_summary(history)
        self.assertAlmostEqual(result["revenueCagr5y"], 10, places=2)
        self.assertEqual(result["cashYearsPositive"], 5)
        self.assertIsNone(annual_summary(history[1:])["revenueCagr5y"])
        history[2]["periodEnd"] = "2021-12-31"
        self.assertIsNone(annual_summary(history)["revenueCagr5y"])

    def test_missing_capital_facts_are_not_zero_or_healthy(self):
        result = financial_quality({"facts": {}}, {"periodEnd": "2026-06-30", "currency": "USD", "netIncomeTtm": 100, "operatingCashFlowTtm": 100, "freeCashFlowTtm": 90}, date(2026, 9, 9))
        self.assertIsNone(result["roeTtm"])
        self.assertIsNone(result["longDebtToOcf"])
        self.assertIsNone(result["cashPerShareProxy"])

    def test_cash_proxy_deducts_share_compensation_and_roe_uses_average_equity(self):
        facts = {}
        for concept, entries, unit in [
            ("StockholdersEquity", [("2025-06-30", 80), ("2026-06-30", 120)], "USD"),
            ("LongTermDebtCurrent", [("2026-06-30", 10)], "USD"),
            ("LongTermDebtNoncurrent", [("2026-06-30", 30)], "USD"),
        ]:
            facts[concept] = {"units": {unit: [{"end": end, "filed": "2026-07-30", "val": amount, "form": "10-Q"} for end, amount in entries]}}
        facts["ShareBasedCompensation"] = {"units": {"USD": [{"start": "2025-07-01", "end": "2026-06-30", "filed": "2026-07-30", "val": 10, "form": "10-K", "accn": "test"}]}}
        facts["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {"shares": [{"start": "2026-04-01", "end": "2026-06-30", "filed": "2026-07-30", "val": 20, "form": "10-Q", "accn": "test"}]}}
        result = financial_quality({"facts": {"us-gaap": facts}}, {"periodEnd": "2026-06-30", "currency": "USD", "netIncomeTtm": 20, "operatingCashFlowTtm": 80, "freeCashFlowTtm": 50}, date(2026, 9, 9))
        self.assertEqual(result["roeTtm"], 20)
        self.assertEqual(result["longDebtToOcf"], 0.5)
        self.assertEqual(result["cashPerShareProxy"], 2)
        shares = facts["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"][0]
        shares["start"] = "2025-07-01"
        annual = financial_quality({"facts": {"us-gaap": facts}}, {"periodEnd": "2026-06-30", "periodType": "quarter", "currency": "USD", "freeCashFlowTtm": 50}, date(2026, 9, 9))
        self.assertEqual(annual["cashPerShareProxy"], 2)
        self.assertEqual(annual["sharesPeriod"], "2025-07-01 / 2026-06-30")


if __name__ == "__main__":
    unittest.main()