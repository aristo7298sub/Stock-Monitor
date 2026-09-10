import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from backend.earnings_reports import cached_html, parse_eps_tables, parse_pdf_eps_text, q4_reports, quarter_number, quarter_start


class EarningsReportTests(unittest.TestCase):
    def test_dynamic_directory_refreshes_but_original_document_cache_is_reused(self):
        response = Mock()
        response.content = b"<html>published report</html>"
        with tempfile.TemporaryDirectory() as directory, patch("backend.earnings_reports.requests.get", return_value=response) as request:
            cache = Path(directory)
            url = "https://investor.tsmc.com/english/quarterly-results/2026/q3"
            cached_html(url, cache)
            cached_html(url, cache)
            self.assertEqual(request.call_count, 1)
            cached_path = next((cache / "reports").glob("*.html"))
            future = datetime.now().timestamp() + 1
            os.utime(cached_path, (future, future))
            cached_html(url, cache, max_age=timedelta(seconds=0))
            self.assertEqual(request.call_count, 2)

    def test_current_report_index_does_not_cache_an_empty_directory_forever(self):
        response = Mock()
        response.json.return_value = {"GetFinancialReportListResult": []}
        with tempfile.TemporaryDirectory() as directory, patch("backend.earnings_reports.requests.get", return_value=response) as request:
            cache = Path(directory)
            year = date.today().year
            self.assertEqual(q4_reports("https://abc.xyz", year, cache), [])
            path = cache / "reports" / f"index-abc.xyz-{year}.json"
            old = datetime.now().timestamp() - 301
            os.utime(path, (old, old))
            response.json.return_value = {"GetFinancialReportListResult": [{"ReportSubType": "Third Quarter"}]}
            self.assertEqual(q4_reports("https://abc.xyz", year, cache)[0]["ReportSubType"], "Third Quarter")
            self.assertEqual(request.call_count, 2)

    def test_fiscal_year_labels_do_not_use_calendar_year_blindly(self):
        self.assertEqual(quarter_number("NVDA", date(2026, 1, 25)), (2026, 4))
        self.assertEqual(quarter_number("NVDA", date(2026, 7, 26)), (2027, 2))
        self.assertEqual(quarter_number("MSFT", date(2025, 9, 30)), (2026, 1))
        self.assertEqual(quarter_number("AAPL", date(2025, 12, 27)), (2026, 1))
        self.assertEqual(quarter_start("MSFT", date(2016, 9, 30), date(2016, 7, 2)), date(2016, 7, 1))
        self.assertEqual(quarter_start("AAPL", date(2026, 6, 27), date(2026, 3, 29)), date(2026, 3, 29))

    def test_gaap_quarter_is_not_annual_or_share_count(self):
        source = """<table><tr><td></td><td colspan="2">Three Months Ended</td><td>Twelve Months Ended</td></tr>
        <tr><td></td><td>September 27, 2025</td><td>September 28, 2024</td><td>September 27, 2025</td></tr>
        <tr><td>Net income</td><td>27466</td><td>14736</td><td>112010</td></tr>
        <tr><td>Earnings per share:</td></tr><tr><td>Basic</td><td>1.85</td><td>0.97</td><td>7.49</td></tr>
        <tr><td>Diluted</td><td>$1.85</td><td>0.97</td><td>7.46</td></tr>
        <tr><td>Shares used in computing earnings per share:</td></tr><tr><td>Diluted</td><td>14863609</td><td>15242853</td></tr></table>"""
        result = parse_eps_tables(source, date(2025, 9, 27), date(2025, 10, 30), "https://www.sec.gov/example.htm")
        self.assertEqual(result[0]["val"], 1.85)
        self.assertEqual(result[0]["end"], "2025-09-27")
        self.assertIn("Diluted", result[0]["evidence"]["row"])

    def test_nongaap_and_wrong_period_rejected(self):
        source = """<table><tr><td>Three Months Ended September 27, 2025</td></tr>
        <tr><td>Non-GAAP Net income</td><td>100</td></tr><tr><td>Diluted earnings per share</td><td>2</td></tr></table>"""
        self.assertEqual(parse_eps_tables(source, date(2025, 9, 27), date(2025, 10, 30), "test"), [])
        self.assertEqual(parse_eps_tables(source.replace("Non-GAAP", "GAAP"), date(2024, 9, 28), date(2025, 10, 30), "test"), [])

    def test_split_header_dates_and_column_order(self):
        source = """<table><tr><td></td><td colspan="2">Three Months Ended June 30,</td><td>Twelve Months Ended June 30,</td></tr>
        <tr><td></td><td>2025</td><td>2026</td><td>2026</td></tr>
        <tr><td>Net income</td><td>20</td><td>30</td><td>100</td></tr>
        <tr><td>Diluted earnings per share</td><td>3.65</td><td>4.81</td><td>17.95</td></tr></table>"""
        result = parse_eps_tables(source, date(2026, 6, 30), date(2026, 7, 29), "test")
        self.assertEqual(result[0]["val"], 4.81)

    def test_pdf_old_year_first_selects_current_quarter(self):
        text = "\n".join([
            "CONSOLIDATED STATEMENTS OF INCOME",
            " " * 40 + "Quarter Ended December 31," + " " * 17 + "Year Ended December 31,",
            f"{'':40}{'2024':>10}{'2025':>14}{'2024':>14}{'2025':>14}",
            f"{'Revenues':40}{'100':>10}{'200':>14}{'400':>14}{'800':>14}",
            f"{'Net income':40}{'10':>10}{'20':>14}{'40':>14}{'80':>14}",
            f"{'Diluted net income per share':40}{'2.15':>10}{'2.82':>14}{'8.04':>14}{'10.81':>14}",
        ])
        value, proof = parse_pdf_eps_text(text, date(2025, 12, 31))
        self.assertEqual(value, 2.82)
        self.assertEqual(proof["quarterColumn"], "2")
        self.assertIsNone(parse_pdf_eps_text(text, date(2025, 9, 30)))
        wrapped = text.replace(f"{'Diluted net income per share':40}", "Diluted earnings per share of Class A, Class B, and Class\n" + f"{'C stock':40}")
        self.assertEqual(parse_pdf_eps_text(wrapped, date(2025, 12, 31))[0], 2.82)


if __name__ == "__main__":
    unittest.main()