from pathlib import Path
import argparse
import json
import sys
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.earnings_reports import supplement_quarterly_eps
from backend.financials import CONCEPTS, observations, periods_as_of, trailing_eps
from backend.providers import fetch_facts, save_json
from backend.server import DEFAULT_COMPANIES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"])
    args = parser.parse_args()
    cache = ROOT / "data" / "cache"
    for symbol, _, cik, _ in DEFAULT_COMPANIES:
        if symbol not in args.symbols:
            continue
        if symbol == "TSM":
            from backend.tsmc import tsmc_quarters, tsmc_eps_document
            rows = tsmc_quarters(cache, date.today())
            augmented = tsmc_eps_document(rows["quarters"])
            save_json(cache / "enriched-TSM.json", augmented)
            print(json.dumps({"symbol": "TSM", "quarters": len(rows["quarters"]), "failures": len(rows["failures"])}))
            continue
        fact_path = cache / f"sec-{cik}.json"
        facts = json.loads(fact_path.read_text(encoding="utf-8")) if fact_path.exists() else fetch_facts(cik, cache)
        augmented = supplement_quarterly_eps(symbol, cik, facts, cache, date.today())
        save_json(cache / f"enriched-{symbol}.json", augmented)
        trailing = trailing_eps(periods_as_of(observations(augmented, CONCEPTS["eps"], "USD/shares"), date.today()))
        print(json.dumps({"symbol": symbol, "added": augmented["supplementalEps"]["count"], "failures": len(augmented["supplementalEps"]["failures"]), "currentTtmEps": trailing["val"] if trailing else None}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()