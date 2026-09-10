import unittest
from datetime import date

from backend.valuation import ALGORITHM_VERSION, daily_valuation, eps_timeline, pe_percentile, years_before, trading_sessions, distribution_value, split_checks, published_valuation
from backend.providers import parse_annual_pe


class PercentileTests(unittest.TestCase):
    def test_empirical_rank_includes_ties(self):
        points = [
            {"date": "2025-01-01", "pe": 10},
            {"date": "2025-02-01", "pe": 20},
            {"date": "2025-03-01", "pe": 20},
            {"date": "2025-04-01", "pe": 40},
        ]
        self.assertEqual(pe_percentile(points, 20, date(2026, 9, 7))["percentile10y"], 75)

    def test_calendar_window_invalid_earnings_and_duplicate_dates(self):
        points = [
            {"date": "2016-09-06", "pe": 1},
            {"date": "2016-09-07", "pe": 10},
            {"date": "2026-09-07", "pe": 20},
            {"date": "2026-09-07", "pe": 30},
            {"date": "2026-09-08", "pe": 1},
            {"date": "2025-01-01", "pe": -5},
            {"date": "2025-02-01", "pe": 0},
            {"date": "2025-03-01", "pe": float("nan")},
            {"date": "invalid", "pe": 12},
        ]
        result = pe_percentile(points, 20, date(2026, 9, 7))
        self.assertEqual(result["sampleCount"], 2)
        self.assertEqual(result["percentile10y"], 50)
        self.assertEqual(result["historyStart"], "2016-09-07")
        self.assertEqual(result["history"][-1]["pe"], 30)

    def test_not_a_fixed_pe_band(self):
        cheap_history = [{"date": "2025-01-01", "pe": 5}, {"date": "2025-02-01", "pe": 10}]
        rich_history = [{"date": "2025-01-01", "pe": 30}, {"date": "2025-02-01", "pe": 40}]
        self.assertEqual(pe_percentile(cheap_history, 20, date(2026, 9, 7))["percentile10y"], 100)
        self.assertEqual(pe_percentile(rich_history, 20, date(2026, 9, 7))["percentile10y"], 0)

    def test_invalid_current_and_empty_history_fail_explicitly(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                pe_percentile([], value, date(2026, 9, 7))
        with self.assertRaises(ValueError):
            pe_percentile([], 20, date(2026, 9, 7))

    def test_leap_year_boundary(self):
        self.assertEqual(years_before(date(2024, 2, 29)), date(2014, 2, 28))

    def test_exchange_holiday_is_not_a_missing_price_day(self):
        self.assertEqual(trading_sessions(date(2026, 9, 4), date(2026, 9, 7)), ("2026-09-04",))

    def test_cached_ranking_loses_eligibility_when_data_expires(self):
        cached = {"algorithmVersion": ALGORITHM_VERSION, "currentPeQualified": True, "asOf": "2026-08-28", "epsPeriodEnd": "2026-06-30", "pe": 20, "percentile": 5, "percentile10y": 5}
        value = published_valuation(cached, as_of=date(2026, 9, 7))
        self.assertEqual(value["status"], "stale")
        self.assertIsNone(value["percentile"])
        self.assertEqual(value["pe"], 20)

    def test_reference_prices_use_quantiles_not_fixed_pe_bands(self):
        self.assertEqual(distribution_value([10, 20, 30], 0.5), 20)
        self.assertEqual(distribution_value([10, 20, 30], 0.2), 14)

    def test_unadjusted_split_price_discontinuity_fails(self):
        with self.assertRaises(ValueError):
            split_checks([{"date": "2020-08-28", "close": 400}, {"date": "2020-08-31", "close": 100}], "AAPL", date(2026, 9, 7))

    def test_missing_new_quarter_invalidates_old_ttm(self):
        quarters = [("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"), ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31")]
        entries = [{"start": start, "end": end, "filed": "2026-02-01", "val": 2, "form": "10-K", "accn": "fixture"} for start, end in quarters]
        entries.append({"start": "2026-01-01", "end": "2026-06-30", "filed": "2026-07-30", "val": 8, "form": "10-Q", "accn": "missing-q1-q2"})
        document = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": entries}}}}}
        events = eps_timeline(document, "AAPL", date(2026, 9, 7))
        self.assertEqual(events[0]["eps"], 8)
        self.assertIsNone(events[-1]["eps"])

    def test_eps_available_after_filing_and_split_normalized(self):
        quarters = [("2018-01-01", "2018-03-31"), ("2018-04-01", "2018-06-30"), ("2018-07-01", "2018-09-30"), ("2018-10-01", "2018-12-31")]
        entries = [{"start": start, "end": end, "filed": filed, "val": value, "form": "10-K", "accn": accession} for start, end in quarters for filed, value, accession in [("2019-02-01", 8, "old"), ("2021-02-01", 2, "restated")]]
        document = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": entries}}}}}
        events = eps_timeline(document, "AAPL", date(2026, 9, 7))
        self.assertEqual(events[0]["availableOn"], "2019-02-02")
        self.assertEqual(events[0]["eps"], 8)
        self.assertEqual(events[1]["eps"], 8)

    def test_short_history_is_not_labeled_ten_years(self):
        with self.assertRaises(ValueError):
            daily_valuation([{"date": "2026-09-04", "close": 100}], {"facts": {}}, "AAPL", date(2026, 9, 7))

    def test_annual_provider_has_explicit_frequency_and_ten_samples(self):
        rows = "".join(f"<tr><td>{year}</td><td>{year - 2000}</td></tr>" for year in range(2011, 2026))
        source = """<p>As of Sep 4, 2026</p><peer-valuation-benchmark :initial-data='{"benchmark":{"ticker":"TSM","values":{"pe":30}}}'></peer-valuation-benchmark>"""
        source += f"<table><tr><th>Year</th><th>PE ratio</th></tr>{rows}</table>"
        result = parse_annual_pe(source, "TSM", date(2026, 9, 7))
        self.assertEqual(result["frequency"], "annual")
        self.assertEqual(result["sampleCount"], 10)
        self.assertEqual(result["percentile10y"], 100)


if __name__ == "__main__":
    unittest.main()