import unittest
from datetime import date

from backend.financials import normalize_financials, observations, periods_as_of, trailing_year, trailing_eps


def fact(start, end, value, filed="2026-08-01", form="10-Q"):
    return {"start": start, "end": end, "val": value, "filed": filed, "form": form, "accn": "test-filing"}


def document(concepts):
    return {"facts": {"us-gaap": {name: {"units": {"USD": entries}} for name, entries in concepts.items()}}}


class FinancialPeriodTests(unittest.TestCase):
    def test_eps_is_not_additive_when_weighted_shares_change(self):
        values = [("2025-01-01", "2025-12-31", 400 / 87.5), ("2025-01-01", "2025-09-30", 3), ("2025-10-01", "2025-12-31", 2), ("2026-01-01", "2026-03-31", 2), ("2026-04-01", "2026-06-30", 2), ("2026-07-01", "2026-09-30", 2), ("2026-01-01", "2026-09-30", 6)]
        periods = [{"start": date.fromisoformat(start), "end": date.fromisoformat(end), "val": value, "filed": date(2026, 11, 1), "accn": "fixture"} for start, end, value in values]
        self.assertAlmostEqual(trailing_year(periods)["val"], 7.5714285714)
        self.assertEqual(trailing_eps(periods)["val"], 8)

    def test_missing_q4_is_not_reconstructed_by_subtracting_eps(self):
        values = [("2025-01-01", "2025-12-31", 5), ("2025-01-01", "2025-09-30", 3), ("2026-01-01", "2026-03-31", 2), ("2026-04-01", "2026-06-30", 2), ("2026-07-01", "2026-09-30", 2)]
        periods = [{"start": date.fromisoformat(start), "end": date.fromisoformat(end), "val": value, "filed": date(2026, 11, 1), "accn": "fixture"} for start, end, value in values]
        self.assertIsNone(trailing_eps(periods))

    def test_quarterly_cash_is_not_ytd_cash(self):
        snapshot = normalize_financials(document({
            "Revenues": [fact("2026-04-01", "2026-06-30", 100)],
            "NetIncomeLoss": [fact("2026-04-01", "2026-06-30", 25)],
            "NetCashProvidedByUsedInOperatingActivities": [fact("2026-01-01", "2026-03-31", 30), fact("2026-01-01", "2026-06-30", 75)],
            "PaymentsToAcquirePropertyPlantAndEquipment": [fact("2026-01-01", "2026-03-31", 10), fact("2026-01-01", "2026-06-30", 25)],
        }), date(2026, 9, 7))
        self.assertEqual(snapshot["operatingCashFlow"], 45)
        self.assertEqual(snapshot["capex"], 15)
        self.assertEqual(snapshot["freeCashFlow"], 30)
        self.assertEqual(snapshot["periodType"], "quarter")

    def test_incremental_coverage_uses_two_aligned_quarters(self):
        snapshot = normalize_financials(document({
            "Revenues": [fact("2026-01-01", "2026-03-31", 90), fact("2026-04-01", "2026-06-30", 100)],
            "NetCashProvidedByUsedInOperatingActivities": [fact("2026-01-01", "2026-03-31", 30), fact("2026-01-01", "2026-06-30", 75)],
            "PaymentsToAcquirePropertyPlantAndEquipment": [fact("2026-01-01", "2026-03-31", 10), fact("2026-01-01", "2026-06-30", 25)],
        }), date(2026, 9, 7))
        self.assertEqual(snapshot["marginalCoverage"], 3)
        self.assertEqual(snapshot["fcfDelta"], 10)

    def test_productive_assets_cash_spending_is_capex_not_business_acquisitions(self):
        snapshot = normalize_financials(document({
            "Revenues": [fact("2026-04-01", "2026-06-30", 100)],
            "NetCashProvidedByUsedInOperatingActivities": [fact("2026-04-01", "2026-06-30", 40)],
            "PaymentsToAcquireProductiveAssets": [fact("2026-04-01", "2026-06-30", 15)],
            "PaymentsToAcquireBusinessesNetOfCashAcquired": [fact("2026-04-01", "2026-06-30", 90)],
        }), date(2026, 9, 7))
        self.assertEqual(snapshot["capex"], 15)
        self.assertEqual(snapshot["freeCashFlow"], 25)
        self.assertEqual(snapshot["capexConcept"], "PaymentsToAcquireProductiveAssets")

    def test_annual_cannot_be_presented_as_a_quarter(self):
        snapshot = normalize_financials(document({"Revenues": [fact("2025-01-01", "2025-12-31", 400, form="20-F")]}), date(2026, 9, 7))
        self.assertEqual(snapshot["periodType"], "annual")
        self.assertFalse(snapshot["quarterly"])
        self.assertEqual(snapshot["revenueTtm"], 400)

    def test_q4_reconstructed_from_annual_minus_nine_months(self):
        snapshot = normalize_financials(document({"Revenues": [fact("2025-01-01", "2025-09-30", 270), fact("2025-01-01", "2025-12-31", 400, form="10-K")]}), date(2026, 9, 7))
        self.assertEqual(snapshot["revenue"], 130)
        self.assertEqual(snapshot["periodType"], "quarter")

    def test_ttm_and_filing_date_no_lookahead(self):
        rows = observations(document({"Revenues": [
            fact("2025-01-01", "2025-12-31", 100, "2026-02-01", "10-K"),
            fact("2025-01-01", "2025-06-30", 40, "2026-08-01"),
            fact("2026-01-01", "2026-06-30", 60, "2026-08-01"),
        ]}), ("Revenues",))
        self.assertEqual(trailing_year(periods_as_of(rows, date(2026, 7, 31)))["val"], 100)
        self.assertEqual(trailing_year(periods_as_of(rows, date(2026, 8, 2)))["val"], 120)

    def test_mismatched_cash_periods_are_missing_not_subtracted(self):
        snapshot = normalize_financials(document({
            "Revenues": [fact("2026-04-01", "2026-06-30", 100)],
            "NetCashProvidedByUsedInOperatingActivities": [fact("2026-01-01", "2026-06-30", 75)],
            "PaymentsToAcquirePropertyPlantAndEquipment": [fact("2026-04-01", "2026-06-30", 15)],
        }), date(2026, 9, 7))
        self.assertIsNone(snapshot["operatingCashFlow"])
        self.assertIsNone(snapshot["freeCashFlow"])


if __name__ == "__main__":
    unittest.main()