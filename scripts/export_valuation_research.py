from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import exchange_calendars

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import server
from backend.providers import save_json


PRIMARY_CHECKPOINTS = {
    "AAPL": ("2025-09-27", 1.85),
    "AMZN": ("2025-12-31", 1.95),
    "GOOGL": ("2025-12-31", 2.82),
    "MSFT": ("2026-06-30", 4.81),
    "NVDA": ("2026-01-25", 1.76),
    "TSM": ("2026-06-30", 4.31),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def source_key(row: dict) -> tuple:
    return (row["start"], row["end"], row.get("filedAt", row.get("filed")), row.get("accession", row.get("accn")), float(row.get("reportedEps", row.get("val"))))


def component_total(components: list[dict], observed: date, source_keys: set[tuple] | None = None) -> float:
    require(len(components) == 4, "Exactly four standalone quarters are required")
    ordered = sorted(components, key=lambda row: row["end"])
    for index, component in enumerate(ordered):
        start, end = date.fromisoformat(component["start"]), date.fromisoformat(component["end"])
        require(60 <= (end - start).days <= 110, "An EPS component is not a standalone quarter")
        require(date.fromisoformat(component["filedAt"]) < observed, "Future or same-day earnings were used before availability")
        require(end < observed, "Future financial period")
        require(component["splitAdjustment"] > 0, "Invalid split adjustment")
        adjusted = component["reportedEps"] / component["splitAdjustment"]
        require(math.isclose(component["eps"], adjusted, rel_tol=1e-10, abs_tol=1e-10), "EPS differs from original fact and split factor")
        if index:
            require(start == date.fromisoformat(ordered[index - 1]["end"]) + timedelta(days=1), "Quarter boundary gap or overlap")
        if source_keys is not None:
            require(source_key(component) in source_keys, "EPS does not match an original SEC or primary-report input")
    require(330 <= (date.fromisoformat(ordered[-1]["end"]) - date.fromisoformat(ordered[0]["start"])).days <= 400, "Four quarters do not span a year")
    return sum(component["reportedEps"] / component["splitAdjustment"] for component in ordered)


def audit_valuation(value: dict, prices: list[dict], source_keys: set[tuple] | None = None) -> dict:
    require(value.get("algorithmVersion") == server.ALGORITHM_VERSION, "Obsolete valuation algorithm")
    require(value.get("status") in {"qualified", "limited"} and value.get("currentPeQualified"), "Valuation is not eligible for historical comparison")
    require(value.get("frequency") == "daily", "Annual samples are not daily history")
    as_of = date.fromisoformat(value["asOf"])
    years = value["horizonYears"]
    try:
        start = as_of.replace(year=as_of.year - years)
    except ValueError:
        start = as_of.replace(year=as_of.year - years, day=28)
    calendar = exchange_calendars.get_calendar("XNYS", start=start - timedelta(days=10), end=as_of + timedelta(days=10))
    sessions = [session.date().isoformat() for session in calendar.sessions_in_range(start.isoformat(), as_of.isoformat())]
    price_map = {row["date"]: row["close"] for row in prices}
    timeline = value["earningsTimeline"]
    event_dates = [event["availableOn"] for event in timeline]
    require(event_dates == sorted(set(event_dates)), "Earnings timeline is not strictly chronological")
    totals = {}
    expected = {}
    known_losses = 0
    for session in sessions:
        cursor = bisect_right(event_dates, session) - 1
        if cursor < 0 or session not in price_map:
            continue
        event = timeline[cursor]
        if event["eps"] is None or (date.fromisoformat(session) - date.fromisoformat(event["periodEnd"])).days > 160:
            continue
        if cursor not in totals:
            totals[cursor] = component_total(event["components"], date.fromisoformat(session), source_keys)
            require(math.isclose(totals[cursor], event["eps"], rel_tol=1e-10), "Timeline EPS is not the sum of its original quarters")
        if totals[cursor] <= 0:
            known_losses += 1
            continue
        expected[session] = {"eps": totals[cursor], "pe": price_map[session] / totals[cursor], "filed": event["filedAt"], "end": event["periodEnd"]}
    history = value["history"]
    require(len(history) == len({row["date"] for row in history}), "Duplicate daily samples")
    require({row["date"] for row in history} == set(expected), "Published sample dates differ from independently reconstructed eligible sessions")
    for sample in history:
        source = expected[sample["date"]]
        require(sample["price"] == price_map[sample["date"]], "Daily close differs from Nasdaq input")
        require(math.isclose(sample["pe"], source["pe"], rel_tol=1e-10), "Daily PE does not match price divided by original quarterly EPS")
        require(math.isclose(sample["eps"], source["eps"], rel_tol=1e-10), "Daily EPS mismatch")
        require(sample["epsFiledAt"] == source["filed"] and sample["epsPeriodEnd"] == source["end"], "Wrong earnings event paired to price")
    current_eps = component_total(value["earningsComponents"], as_of, source_keys)
    require(math.isclose(value["epsTtm"], current_eps, rel_tol=1e-10), "Current EPS component mismatch")
    require(value["price"] == price_map[value["asOf"]], "Current close mismatch")
    require(math.isclose(value["pe"], value["price"] / current_eps, rel_tol=1e-10), "Current PE mismatch")
    independent_rank = round(100 * sum(row["pe"] <= value["pe"] for row in expected.values()) / len(expected), 2)
    require(independent_rank == value["percentile"], "Historical percentile mismatch")
    require(value["percentile10y"] == (independent_rank if years == 10 else None), "A shorter window was presented as ten years")
    require(value["sampleCount"] == len(expected), "Sample count mismatch")
    selected = next(window for window in value["coverage"] if window["years"] == years)
    require(selected["expectedSessions"] == len(sessions), "Exchange-session count mismatch")
    require(selected["nonpositiveEarningsSessions"] == known_losses, "Loss-session count mismatch")
    require(selected["missingEarningsSessions"] == len(sessions) - len(expected) - known_losses, "Missing-session count mismatch")
    values = [row["pe"] for row in expected.values()]
    quintiles = statistics.quantiles(values, n=5, method="inclusive")
    quantiles = {20: quintiles[0], 50: statistics.median(values), 80: quintiles[-1]}
    for reference in value["referencePrices"]:
        require(math.isclose(reference["pe"], quantiles[reference["percentile"]], rel_tol=1e-10), "Historical multiple quantile mismatch")
        require(math.isclose(reference["price"], reference["pe"] * current_eps, rel_tol=1e-10), "Reference-price arithmetic mismatch")
    return {"arithmeticAndSourceMatching": "passed", "horizonYears": years, "dailySamplesChecked": len(history), "earningsEventsChecked": len(totals), "knownLossSessions": known_losses, "independentlyRecountedPercentile": independent_rank, "externalFinancialAudit": False}


def verify_report_hash(path: Path, expected: str) -> str:
    raw = path.read_bytes()
    candidates = {"file bytes": raw}
    if path.suffix == ".html":
        candidates["UTF-8 text read by parser"] = path.read_text(encoding="utf-8").encode("utf-8")
        candidates["original UTF-8 HTML before legacy Windows newline translation"] = raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
    for basis, content in candidates.items():
        if hashlib.sha256(content).hexdigest() == expected:
            return basis
    raise AssertionError(f"Original report hash mismatch: {path.name}")


def input_evidence(symbol: str, cik: str) -> tuple[set[tuple], list[dict], dict]:
    cache = server.CACHE_DIR
    keys = set()
    metadata = {"primaryReports": []}
    if symbol != "TSM":
        path = cache / f"sec-{cik.zfill(10)}.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        metadata["secInputSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        for taxonomy in source["facts"].values():
            for concept in ("EarningsPerShareDiluted", "DilutedEarningsLossPerShare"):
                for row in taxonomy.get(concept, {}).get("units", {}).get("USD/shares", []):
                    if all(field in row for field in ("start", "end", "filed", "accn", "val")):
                        keys.add(source_key(row))
    supplement = json.loads((cache / f"quarterly-eps-{symbol}.json").read_text(encoding="utf-8"))
    for row in supplement["quarters"]:
        keys.add(source_key(row))
        path = cache / "reports" / f"{hashlib.sha256(row['sourceUrl'].encode()).hexdigest()}.{'pdf' if '.pdf' in row['sourceUrl'].lower() else 'html'}"
        require(path.is_file(), f"Cached original report not found: {row['sourceUrl']}")
        hash_basis = verify_report_hash(path, row["sourceHash"])
        metadata["primaryReports"].append({"periodEnd": row["end"], "sourceUrl": row["sourceUrl"], "sourceHash": row["sourceHash"], "hashBasis": hash_basis, "eps": row["val"]})
    if symbol in PRIMARY_CHECKPOINTS:
        endpoint, expected = PRIMARY_CHECKPOINTS[symbol]
        checkpoint = next(row for row in supplement["quarters"] if row["end"] == endpoint)
        require(checkpoint["val"] == expected, f"Manually read primary-report checkpoint changed: {symbol} {endpoint}")
        metadata["primaryCheckpoint"] = {"periodEnd": endpoint, "expectedReportedEps": expected, "sourceUrl": checkpoint["sourceUrl"], "status": "matched"}
    path = cache / f"prices-{symbol}.json"
    metadata["priceInputSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    prices = json.loads(path.read_text(encoding="utf-8"))
    metadata["priceSource"] = prices["source"]
    metadata["priceFetchedAt"] = prices["fetchedAt"]
    return keys, prices["prices"], metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct daily PE from cached prices and original quarterly EPS, without calling the production ranking function")
    parser.add_argument("--refresh", action="store_true", help="Fetch current provider data before checking")
    args = parser.parse_args()
    server.init_database()
    if args.refresh:
        server.refresh_stale_facts(force=True)
        server.refresh_valuations(force=True)
    with server.connect() as connection:
        rows = connection.execute("SELECT * FROM companies ORDER BY symbol").fetchall()
    results = []
    for row in rows:
        value = server.company_valuation(row, include_history=True)
        if not value or value.get("status") not in {"qualified", "limited"}:
            results.append({"symbol": row["symbol"], "checks": {"arithmeticAndSourceMatching": "not_eligible", "externalFinancialAudit": False}, "valuation": value})
            print(f"UNAVAILABLE {row['symbol']}: no eligible historical comparison")
            continue
        keys, prices, evidence = input_evidence(row["symbol"], row["cik"])
        checks = audit_valuation(value, prices, keys)
        results.append({"symbol": row["symbol"], "checks": checks, "inputEvidence": evidence, "sourceErrors": server.company_payload(row)["errors"], "valuation": value})
        print(f"CHECKED {row['symbol']}: PE={value['pe']:.4f}; {value['horizonYears']}Y rank={value['percentile']:.2f}%; daily samples={value['sampleCount']}; original checkpoint matched")
    destination = ROOT / "research" / "pe-percentile-results.json"
    save_json(destination, {"exportedAt": server.iso_now(), "algorithmVersion": server.ALGORITHM_VERSION, "scope": "Arithmetic, dated source matching, cached original hashes and six manually read EPS checkpoints; not an independent financial audit or investment recommendation.", "results": results})
    print(f"Exported {len(results)} company records to {destination}")


if __name__ == "__main__":
    main()