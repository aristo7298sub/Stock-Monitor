import unittest

from backend.tsmc import parse_release, management_cash


class TsmcQuarterTests(unittest.TestCase):
    def test_management_cash_retains_native_currency_and_sign(self):
        text = "II - 2. Operating Income Analysis\n(In NT$ billions) 2Q26 1Q26 2Q25\nOperating Income 766.60 658.97 463.42\nIV - 1. Quarterly Cash Flow Analysis\n(In NT$ billions) 2Q26 1Q26 2Q25\nNet Operating Sources/(Uses) 783.36 698.97 497.07\nCapital Expenditures (496.00) (350.76) (297.22)\nV. Capital Expenditures\nCapital Expenditures 15.70 11.10 26.80"
        values = management_cash(text, 2026, 2)
        self.assertEqual(values["operatingCashFlow"][0], 783.36e9)
        self.assertEqual(values["capex"][0], -496e9)
        with self.assertRaises(ValueError):
            management_cash(text.replace("NT$", "US$"), 2026, 2)
        with self.assertRaises(ValueError):
            management_cash(text.replace("2Q26 1Q26", "1Q26 2Q26"), 2026, 2)
        with self.assertRaises(ValueError):
            management_cash(text.replace("Quarterly Cash Flow Analysis", "Capital Expenditures"), 2026, 2)

    def test_usd_eps_is_per_adr_not_twd_per_ordinary_share(self):
        text = "Hsinchu, Taiwan July 16, 2026 -- TSMC announced consolidated revenue of NT$1,270.38 billion, net income of NT$706.56 billion, and diluted earnings per share of NT$27.25 (US$4.31 per ADR unit) for the second quarter ended June 30, 2026. In US dollars, second quarter revenue was $40.20 billion."
        row = parse_release(text, 2026, 2, "https://investor.tsmc.com/example.pdf", "hash")
        self.assertEqual(row["val"], 4.31)
        self.assertEqual(row["epsTwd"], 27.25)
        self.assertEqual(row["end"], "2026-06-30")
        self.assertEqual(row["filed"], "2026-07-16")
        self.assertEqual(row["revenueUsd"], 40.2e9)
        self.assertEqual(parse_release(text.replace("income of NT$706.56", "income of NT $706. 56"), 2026, 2, "test", "hash")["netIncomeTwd"], 706.56e9)
        self.assertEqual(parse_release(text.replace("27.25", "27. 25"), 2026, 2, "test", "hash")["epsTwd"], 27.25)
        with self.assertRaises(ValueError):
            parse_release(text, 2026, 1, "test", "hash")
        with self.assertRaises(ValueError):
            parse_release(text.replace("per ADR unit", "per ordinary share"), 2026, 2, "test", "hash")


if __name__ == "__main__":
    unittest.main()