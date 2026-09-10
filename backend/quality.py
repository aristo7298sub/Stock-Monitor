from __future__ import annotations

import math
from datetime import date
from typing import Any

from backend.financials import CONCEPTS, FORMS, observations, periods_as_of, quarter_at, trailing_year


def instant_fact(document: dict[str, Any], concepts: tuple[str, ...], end: date, as_of: date, unit: str = "USD") -> dict[str, Any] | None:
    candidates = []
    for taxonomy in ("us-gaap", "ifrs-full"):
        for priority, concept in enumerate(concepts):
            for row in document.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("units", {}).get(unit, []):
                if row.get("start") or row.get("end") != end.isoformat() or str(row.get("form", "")).removesuffix("/A") not in FORMS:
                    continue
                try:
                    filed = date.fromisoformat(row["filed"])
                    amount = float(row["val"])
                except (KeyError, TypeError, ValueError):
                    continue
                if filed <= as_of and math.isfinite(amount):
                    candidates.append({**row, "val": amount, "concept": concept, "priority": priority})
    return max(candidates, key=lambda row: (row["filed"], -row["priority"])) if candidates else None


def annual_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    history = sorted(history, key=lambda row: row["periodEnd"])[-6:]
    contiguous = all(330 <= (date.fromisoformat(current["periodEnd"]) - date.fromisoformat(previous["periodEnd"])).days <= 400 for previous, current in zip(history, history[1:]))
    cagr = None
    if len(history) == 6 and contiguous and history[0].get("revenue", 0) and history[-1].get("revenue", 0):
        first, latest = history[0]["revenue"], history[-1]["revenue"]
        if first > 0 and latest > 0:
            elapsed = (date.fromisoformat(history[-1]["periodEnd"]) - date.fromisoformat(history[0]["periodEnd"])).days / 365.25
            cagr = 100 * ((latest / first) ** (1 / elapsed) - 1)
    recent = history[-5:]
    cash_values = [row["freeCashFlow"] for row in recent if row.get("freeCashFlow") is not None]
    income_values = [row["netIncome"] for row in recent if row.get("netIncome") is not None]
    return {"history": history, "historyContiguous": contiguous, "revenueCagr5y": cagr, "cashYearsKnown": len(cash_values), "cashYearsPositive": sum(value > 0 for value in cash_values), "profitYearsKnown": len(income_values), "profitYearsPositive": sum(value > 0 for value in income_values)}


def financial_quality(document: dict[str, Any], snapshot: dict[str, Any], as_of: date) -> dict[str, Any]:
    end = date.fromisoformat(snapshot["periodEnd"])
    concepts = {key: CONCEPTS[key] for key in ("revenue", "netIncome", "operatingIncome", "operatingCashFlow", "capex")}
    concepts["shareCompensation"] = ("ShareBasedCompensation",)
    series = {key: periods_as_of(observations(document, names), as_of) for key, names in concepts.items()}
    annuals = {row["end"]: row for row in series["revenue"] if 330 <= (row["end"] - row["start"]).days <= 400}
    history = []
    for endpoint, basis in sorted(annuals.items())[-6:]:
        values = {key: next((row["val"] for row in reversed(periods) if row["end"] == endpoint and row["start"] == basis["start"]), None) for key, periods in series.items()}
        cash, capex = values["operatingCashFlow"], values["capex"]
        history.append({**values, "periodStart": basis["start"].isoformat(), "periodEnd": endpoint.isoformat(), "filedAt": basis["filed"].isoformat(), "accession": basis["accn"], "freeCashFlow": cash - capex if cash is not None and capex is not None else None})
    balance_concepts = {"equity": ("StockholdersEquity", "EquityAttributableToOwnersOfParent"), "cash": ("CashAndCashEquivalentsAtCarryingValue",), "currentLongDebt": ("LongTermDebtCurrent",), "noncurrentLongDebt": ("LongTermDebtNoncurrent",), "shortBorrowings": ("ShortTermBorrowings",), "commercialPaper": ("CommercialPaper",)}
    balance = {key: instant_fact(document, names, end, as_of) for key, names in balance_concepts.items()}
    prior_ends = []
    for taxonomy in ("us-gaap", "ifrs-full"):
        for concept in balance_concepts["equity"]:
            for row in document.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("units", {}).get("USD", []):
                try:
                    endpoint = date.fromisoformat(row["end"])
                except (KeyError, ValueError):
                    continue
                if abs((end - endpoint).days - 365) <= 14:
                    prior_ends.append(endpoint)
    prior_equity = instant_fact(document, balance_concepts["equity"], max(prior_ends), as_of) if prior_ends else None
    equity = balance["equity"]
    net_income = snapshot.get("netIncomeTtm")
    roe = 100 * net_income / ((equity["val"] + prior_equity["val"]) / 2) if net_income is not None and equity and prior_equity and min(equity["val"], prior_equity["val"]) > 0 else None
    debt = balance["currentLongDebt"]["val"] + balance["noncurrentLongDebt"]["val"] if balance["currentLongDebt"] and balance["noncurrentLongDebt"] else None
    ocf = snapshot.get("operatingCashFlowTtm")
    sbc = trailing_year(series["shareCompensation"])
    sbc_value = sbc["val"] if sbc and sbc["end"] == end else None
    share_periods = periods_as_of(observations(document, ("WeightedAverageNumberOfDilutedSharesOutstanding",), "shares"), as_of)
    shares = quarter_at(share_periods, end)
    if shares and shares.get("derived"):
        shares = None
    if shares is None and snapshot.get("periodType") == "quarter":
        shares = next((row for row in reversed(share_periods) if row["end"] == end and 330 <= (row["end"] - row["start"]).days <= 400), None)
    fcf = snapshot.get("freeCashFlowTtm")
    proxy = (fcf - sbc_value) / shares["val"] if fcf is not None and sbc_value is not None and shares and shares["val"] > 0 else None
    return {
        "version": 1, "currency": snapshot["currency"], "periodEnd": snapshot["periodEnd"],
        **annual_summary(history), "roeTtm": roe, "equity": equity["val"] if equity else None,
        "longDebt": debt, "longDebtToOcf": debt / ocf if debt is not None and ocf is not None and ocf > 0 else None,
        "cash": balance["cash"]["val"] if balance["cash"] else None,
        "shortBorrowings": balance["shortBorrowings"]["val"] if balance["shortBorrowings"] else None,
        "commercialPaper": balance["commercialPaper"]["val"] if balance["commercialPaper"] else None,
        "shareCompensationTtm": sbc_value, "dilutedShares": shares["val"] if shares else None,
        "sharesPeriod": f"{shares['start']} / {shares['end']}" if shares else None,
        "cashPerShareProxy": proxy, "balanceEvidence": {key: {field: row.get(field) for field in ("val", "end", "filed", "accn", "concept")} for key, row in balance.items() if row},
        "roeBasis": "TTM net income / average positive equity at current and prior-year comparable dates; buybacks and non-operating gains may inflate ROE.",
        "debtBasis": "Current plus noncurrent long-term debt / TTM operating cash flow. Not total debt; other borrowings and leases require separate review. Missing debt is not zero.",
        "cashProxyBasis": "(TTM operating cash flow - cash capital expenditure - share compensation) / latest reported diluted weighted shares (quarter, or matching annual when Q4 is unavailable; sharesPeriod is explicit). Conservative research proxy, not audited owner earnings or distributable FCFE; no maintenance/growth Capex split.",
    }