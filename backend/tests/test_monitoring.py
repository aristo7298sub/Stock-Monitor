import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from backend import server


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patches = [patch.object(server, "DATA_DIR", Path(self.directory.name)), patch.object(server, "DATABASE_PATH", Path(self.directory.name) / "test.db")]
        for item in self.patches:
            item.start()
        server.init_database()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_migration_preserves_existing_companies_and_is_idempotent(self):
        with server.connect() as connection:
            connection.execute("UPDATE companies SET quote_json=? WHERE symbol='AAPL'", (json.dumps({"price": 123}),))
        server.init_database()
        companies = server.database_companies()
        self.assertEqual(len(companies), 6)
        self.assertEqual(next(item for item in companies if item["symbol"] == "AAPL")["quote"]["price"], 123)

    def test_html_entrypoints_cannot_keep_an_obsolete_ui_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("<html>current build</html>", encoding="utf-8")
            with patch.object(server, "WEB_DIST", root):
                for path in ("", "index.html", "research"):
                    self.assertEqual(server.web(path).headers["cache-control"], "no-store")

    def test_failed_refresh_keeps_last_good_quote_and_separate_fact_error(self):
        with server.connect() as connection:
            connection.execute("UPDATE companies SET quote_json=?,facts_error='SEC unavailable' WHERE symbol='AAPL'", (json.dumps({"price": 123}),))
        with patch.object(server.requests, "get", side_effect=RuntimeError("offline")):
            self.assertEqual(server.refresh_quotes(["AAPL"]), 0)
        apple = next(item for item in server.database_companies() if item["symbol"] == "AAPL")
        self.assertEqual(apple["quote"]["price"], 123)
        self.assertIn("facts", apple["errors"])
        self.assertIn("quote", apple["errors"])

    def test_successful_quotes_commit_before_logging(self):
        response = Mock()
        response.json.return_value = {"FormattedQuoteResult": {"FormattedQuote": [{"symbol": "AAPL", "last": "123.45", "change_pct": "1.2", "volume": "300"}]}}
        with patch.object(server.requests, "get", return_value=response):
            self.assertEqual(server.refresh_quotes(["AAPL"]), 1)
        with server.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM quote_history WHERE symbol='AAPL'").fetchone()[0], 1)
            logs = list(connection.execute("SELECT status FROM refresh_events WHERE source='cnbc'"))
            self.assertEqual([row[0] for row in logs], ["ok"])
        apple = next(item for item in server.database_companies() if item["symbol"] == "AAPL")
        self.assertEqual(apple["quote"]["price"], 123.45)

    def test_quote_refresh_and_filing_logs_can_write_concurrently(self):
        response = Mock()
        response.json.return_value = {"FormattedQuoteResult": {"FormattedQuote": [{"symbol": "AAPL", "last": "123.45"}]}}
        with patch.object(server.requests, "get", return_value=response), ThreadPoolExecutor(max_workers=3) as pool:
            quote_job = pool.submit(server.refresh_quotes, ["AAPL"])
            log_jobs = [pool.submit(server.log_refresh, "filings", "ok", str(index)) for index in range(10)]
            self.assertEqual(quote_job.result(), 1)
            for job in log_jobs:
                job.result()
        with server.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM refresh_events").fetchone()[0], 11)

    def test_new_filing_triggers_one_refresh_and_is_deduplicated(self):
        payload = {"filings": {"recent": {"form": ["10-Q"], "accessionNumber": ["0000320193-26-000020"], "filingDate": ["2026-07-31"], "reportDate": ["2026-06-27"], "primaryDocument": ["aapl.htm"]}}}
        response = Mock()
        response.json.return_value = payload
        with server.connect() as connection:
            connection.execute("UPDATE companies SET financials_json=? WHERE symbol='AAPL'", (json.dumps({"periodEnd": "2026-06-27"}),))
        with patch.object(server.requests, "get", return_value=response), patch.object(server, "refresh_company_facts", return_value=True) as refresh, patch.object(server, "refresh_stale_facts"), patch.object(server, "refresh_valuations"):
            self.assertEqual(server.check_earnings(["AAPL"]), 1)
            self.assertEqual(server.check_earnings(["AAPL"]), 0)
            refresh.assert_called_once()
        with server.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM filing_events").fetchone()[0], 1)

    def test_xbrl_lag_retries_the_known_filing(self):
        payload = {"filings": {"recent": {"form": ["10-Q"], "accessionNumber": ["new"], "filingDate": ["2026-07-31"], "reportDate": ["2026-06-27"], "primaryDocument": ["aapl.htm"]}}}
        response = Mock()
        response.json.return_value = payload
        with server.connect() as connection:
            connection.execute("UPDATE companies SET latest_filing_json=?,financials_json=? WHERE symbol='AAPL'", (json.dumps({"accession": "new"}), json.dumps({"periodEnd": "2026-03-28"})))
        with patch.object(server.requests, "get", return_value=response), patch.object(server, "refresh_company_facts", return_value=True) as refresh, patch.object(server, "refresh_stale_facts"), patch.object(server, "refresh_valuations"):
            server.check_earnings(["AAPL"])
            refresh.assert_called_once_with("AAPL", "0000320193")

    def test_newer_filing_and_old_financials_are_labeled_pending(self):
        with server.connect() as connection:
            connection.execute("UPDATE companies SET financials_json=?,latest_filing_json=? WHERE symbol='TSM'", (json.dumps({"periodEnd": "2024-12-31"}), json.dumps({"reportDate": "2026-06-30"})))
        tsm = next(item for item in server.database_companies() if item["symbol"] == "TSM")
        self.assertTrue(tsm["earnings"]["pendingStructuredData"])

    def test_release_event_date_is_not_mistaken_for_a_quarter_end(self):
        financials = {"periodEnd": "2026-06-30", "filedAt": "2026-07-31"}
        release = {"form": "8-K", "reportDate": "2026-07-30", "filedAt": "2026-07-30"}
        self.assertFalse(server.financial_report_pending(release, financials))
        self.assertTrue(server.financial_report_pending({**release, "filedAt": "2026-10-23"}, financials))

    def test_new_earnings_withdraw_cached_ranks_in_both_apis(self):
        value = {"algorithmVersion": server.ALGORITHM_VERSION, "pe": 20, "percentile": 1, "percentile10y": 1, "currentPeQualified": True, "epsPeriodEnd": "2026-03-31", "history": []}
        with server.connect() as connection:
            connection.execute("UPDATE companies SET valuation_json=?,financials_json=? WHERE symbol='AAPL'", (json.dumps(value), json.dumps({"periodEnd": "2026-06-30"})))
        with patch.object(server, "published_valuation", side_effect=lambda value, **kwargs: value):
            apple = next(item for item in server.database_companies() if item["symbol"] == "AAPL")
            detailed = server.valuation_details("AAPL")["valuation"]
        for valuation in [apple["valuation"], detailed]:
            self.assertEqual(valuation["pe"], 20)
            self.assertFalse(valuation["currentPeQualified"])
            self.assertIsNone(valuation["percentile"])
            self.assertIsNone(valuation["percentile10y"])

    def test_new_filing_invalidates_valuation_even_before_xbrl_changes(self):
        response = Mock()
        response.json.return_value = {"filings": {"recent": {"form": ["10-Q"], "accessionNumber": ["new"], "filingDate": ["2026-07-31"], "reportDate": ["2026-06-27"], "primaryDocument": ["aapl.htm"]}}}
        with server.connect() as connection:
            connection.execute("UPDATE companies SET valuation_updated_at=? WHERE symbol='AAPL'", (server.iso_now(),))
        with patch.object(server.requests, "get", return_value=response), patch.object(server, "refresh_company_facts", return_value=False), patch.object(server, "refresh_stale_facts"):
            server.check_earnings(["AAPL"])
        with server.connect() as connection:
            self.assertIsNone(connection.execute("SELECT valuation_updated_at FROM companies WHERE symbol='AAPL'").fetchone()[0])

    def test_valuation_retries_if_financial_revision_arrives_mid_calculation(self):
        with server.connect() as connection:
            connection.execute("UPDATE companies SET valuation_json=? WHERE symbol='AAPL'", (json.dumps({"pe": 10}),))

        def calculate(*args):
            with server.connect() as connection:
                connection.execute("UPDATE companies SET financials_json=? WHERE symbol='AAPL'", (json.dumps({"periodEnd": "2026-06-27"}),))
            return {"pe": 20, "frequency": "daily", "source": "test", "history": [{"date": "2026-09-04", "pe": 20}]}

        with patch.object(server, "fetch_valuation", side_effect=calculate):
            self.assertEqual(server.refresh_valuations(["AAPL"], force=True), 0)
            apple = next(item for item in server.database_companies() if item["symbol"] == "AAPL")
            self.assertIsNone(apple["valuation"]["pe"])
            self.assertEqual(apple["valuation"]["status"], "withdrawn")
            self.assertIsNone(apple["valuationUpdatedAt"])
            self.assertEqual(server.refresh_valuations(["AAPL"], force=True), 1)

    def test_old_percentile_is_withdrawn_not_treated_as_current_evidence(self):
        with server.connect() as connection:
            connection.execute("UPDATE companies SET valuation_json=? WHERE symbol='TSM'", (json.dumps({"pe": 32, "percentile10y": 100, "frequency": "annual", "asOf": "2026-09-04"}),))
        tsm = next(item for item in server.database_companies() if item["symbol"] == "TSM")
        self.assertIsNone(tsm["valuation"]["percentile10y"])
        self.assertEqual(tsm["valuation"]["status"], "withdrawn")


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_filing_job_runs_outside_utc_eight(self):
        callback = Mock(return_value=6)
        with patch.object(server, "utc_now", return_value=datetime(2026, 9, 7, 17, tzinfo=timezone.utc)), patch.object(server.asyncio, "sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await server.periodic_job("test", 300, callback)
        callback.assert_called_once()
        self.assertEqual(server.MONITOR_STATE["test"]["updated"], 6)
        server.MONITOR_STATE.pop("test", None)


if __name__ == "__main__":
    unittest.main()