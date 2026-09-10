from __future__ import annotations

import json
import math
import os
import re
import statistics
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from backend.valuation import ALGORITHM_VERSION, SPLITS, years_before, pe_percentile


SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def sec_headers() -> dict[str, str]:
    contact = os.environ.get("SEC_CONTACT", "").strip()
    agent = "Stock Monitor/1.0 personal investment research"
    return {"User-Agent": f"{agent} ({contact})" if contact else agent, "Accept": "application/json"}


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def fetch_facts(cik: str, cache_dir: Path) -> dict[str, Any]:
    response = requests.get(SEC_FACTS_URL.format(cik=str(cik).zfill(10)), headers=sec_headers(), timeout=(10, 45))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload.get("facts"), dict):
        raise ValueError("SEC returned no company facts")
    save_json(cache_dir / f"sec-{str(cik).zfill(10)}.json", payload)
    return payload


def check_price_revision(prices: list[dict[str, Any]], previous: dict[str, Any], policy: list[list[Any]]) -> None:
    current = {row["date"]: row["close"] for row in prices}
    new_actions = [action for action in policy if action not in previous.get("splitPolicy", policy)]
    changes = []
    for row in previous.get("prices", []):
        revised = current.get(row["date"])
        if not revised or revised <= 0 or row["close"] <= 0:
            continue
        expected = math.prod(ratio for effective_date, ratio in new_actions if row["date"] < effective_date)
        changes.append(abs(row["close"] / revised / expected - 1))
    if len(changes) >= 20 and statistics.median(changes) > 0.02:
        raise ValueError("历史价格发生未解释的重标定，可能涉及拆股或数据源口径变更；核对公司行动前暂停估值。")


def fetch_prices(symbol: str, as_of: date, cache_dir: Path) -> list[dict[str, Any]]:
    url = f"https://api.nasdaq.com/api/quote/{symbol}/historical"
    response = requests.get(url, params={"assetclass": "stocks", "fromdate": years_before(as_of, 11).isoformat(), "todate": as_of.isoformat(), "limit": 6000}, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nasdaq.com/"}, timeout=(10, 40))
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    table = data.get("tradesTable") or {}
    rows = table.get("rows") or []
    if not rows:
        raise ValueError(f"Nasdaq history has no rows: {payload.get('status')}")
    by_date = {}
    for row in rows:
        observed = datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat()
        close = float(row["close"].replace("$", "").replace(",", ""))
        by_date[observed] = {"date": observed, "close": close}
    prices = [by_date[key] for key in sorted(by_date)]
    path = cache_dir / f"prices-{symbol}.json"
    policy = [[effective.isoformat(), ratio] for effective, ratio in SPLITS.get(symbol, ()) if effective <= as_of]
    if path.is_file():
        check_price_revision(prices, json.loads(path.read_text(encoding="utf-8")), policy)
    save_json(path, {"source": url, "fetchedAt": datetime.now(timezone.utc).isoformat(), "splitPolicy": policy, "prices": prices})
    return prices


def parse_annual_pe(source: str, symbol: str, as_of: date) -> dict[str, Any]:
    soup = BeautifulSoup(source, "html.parser")
    component = soup.find("peer-valuation-benchmark")
    if component is None:
        raise ValueError("FullRatio public benchmark data missing")
    benchmark = json.loads(component[":initial-data"])["benchmark"]
    if benchmark["ticker"].upper() != symbol:
        raise ValueError("FullRatio returned a different company")
    current_pe = float(benchmark["values"]["pe"])
    text = soup.get_text(" ", strip=True)
    match = re.search(r"as (?:of|at)\s+([A-Z][a-z]{2} \d{1,2},\s*\d{4})", text, re.IGNORECASE)
    if not match:
        raise ValueError("No provider valuation date found")
    observed = datetime.strptime(re.sub(r"\s+", " ", match.group(1)), "%b %d, %Y").date()
    if observed > as_of:
        raise ValueError("Provider valuation is dated in the future")
    samples = []
    for table in soup.select("table"):
        headers = [item.get_text(" ", strip=True) for item in table.select("th")]
        if headers[:2] != ["Year", "PE ratio"]:
            continue
        for row in table.select("tr"):
            columns = [item.get_text(" ", strip=True) for item in row.select("td")]
            if len(columns) < 2 or not re.fullmatch(r"\d{4}", columns[0]):
                continue
            try:
                samples.append({"date": f"{columns[0]}-12-31", "pe": float(columns[1].replace(",", ""))})
            except ValueError:
                continue
    result = pe_percentile(samples, current_pe, observed)
    expected_years = set(range(observed.year - 10, observed.year))
    found_years = {int(item["date"][:4]) for item in result["history"]}
    if not expected_years.issubset(found_years):
        raise ValueError("Public annual PE table does not cover ten complete years")
    result.update({
        "frequency": "annual", "asOf": observed.isoformat(), "forwardPe": None,
        "basis": "Provider TTM P/E at each year end; provider earnings convention",
        "source": "FullRatio public annual P/E table", "coverageYears": 10,
        "warnings": ["Annual sampling only: ten year-end observations, not daily time percentile.", "Use provider P/E for TSM ADR; never divide USD price by TWD EPS directly." if symbol == "TSM" else "Provider earnings conventions may differ from SEC diluted EPS; use consistent historical/current provider P/E."],
    })
    return result


def fetch_annual_pe(symbol: str, exchange: str, as_of: date, cache_dir: Path) -> dict[str, Any]:
    market = "nyse" if exchange.upper() == "NYSE" else "nasdaq"
    url = f"https://fullratio.com/stocks/{market}-{symbol.lower()}/pe-ratio"
    response = requests.get(url, timeout=(10, 35))
    response.raise_for_status()
    result = parse_annual_pe(response.text, symbol, as_of)
    result["sourceUrl"] = url
    save_json(cache_dir / f"annual-pe-{symbol}.json", result)
    return result


def fetch_valuation(symbol: str, cik: str, exchange: str, as_of: date, cache_dir: Path) -> dict[str, Any]:
    from backend.valuation import SPLITS, daily_valuation

    reason = "No verified daily EPS/ADR split history for this security"
    try:
        if symbol not in SPLITS:
            raise ValueError(reason)
        facts_path = cache_dir / f"sec-{str(cik).zfill(10)}.json"
        facts = json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.exists() else fetch_facts(cik, cache_dir)
        if symbol == "TSM":
            from backend.tsmc import tsmc_quarters, tsmc_eps_document
            data = tsmc_quarters(cache_dir, as_of)
            facts = tsmc_eps_document(data["quarters"])
        else:
            from backend.earnings_reports import supplement_quarterly_eps
            facts = supplement_quarterly_eps(symbol, cik, facts, cache_dir, as_of)
        prices = fetch_prices(symbol, as_of, cache_dir)
        result = daily_valuation(prices, facts, symbol, as_of)
        result.update({"sourceUrl": f"https://api.nasdaq.com/api/quote/{symbol}/historical", "earningsSourceUrl": SEC_FACTS_URL.format(cik=str(cik).zfill(10))})
        if symbol == "TSM":
            result["basis"] = "Sum of four TSMC-reported USD diluted EPS per ADR; quarter-specific company FX translation"
            result["warnings"].append("TSMC USD ADR earnings use the FX convention in each quarterly release, not a single current spot USD/TWD rate.")
        for component in result["earningsComponents"]:
            if not component["sourceUrl"]:
                component["sourceUrl"] = SEC_FACTS_URL.format(cik=str(cik).zfill(10))
        return result
    except ValueError as error:
        reason = str(error)
    return {"algorithmVersion": ALGORITHM_VERSION, "status": "incomplete", "pe": None, "percentile10y": None, "forwardPe": None, "asOf": as_of.isoformat(), "reason": reason, "sampleCount": 0, "frequency": "daily", "source": "SEC + Nasdaq (pending validation)", "history": []}