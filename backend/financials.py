from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any


CONCEPTS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "Revenue"),
    "netIncome": ("NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"),
    "operatingIncome": ("OperatingIncomeLoss", "ProfitLossFromOperatingActivities"),
    "operatingCashFlow": ("NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForAdditionsToPropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "PaymentsToAcquireProductiveAssets"),
    "eps": ("EarningsPerShareDiluted", "DilutedEarningsLossPerShare"),
}
FORMS = {"10-Q", "10-K", "20-F", "40-F", "6-K", "8-K"}


def observations(document: dict[str, Any], concepts: tuple[str, ...], unit: str = "USD") -> list[dict[str, Any]]:
    rows = []
    for taxonomy in ("us-gaap", "ifrs-full"):
        for priority, concept in enumerate(concepts):
            values = document.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("units", {}).get(unit, [])
            for value in values:
                if str(value.get("form", "")).removesuffix("/A") not in FORMS:
                    continue
                try:
                    start = date.fromisoformat(value["start"])
                    end = date.fromisoformat(value["end"])
                    filed = date.fromisoformat(value["filed"])
                    amount = float(value["val"])
                except (KeyError, ValueError, TypeError):
                    continue
                if not math.isfinite(amount) or not 50 <= (end - start).days <= 400:
                    continue
                rows.append({**value, "start": start, "end": end, "filed": filed, "val": amount, "priority": priority, "concept": concept, "unit": unit})
    return rows


def periods_as_of(
    rows: list[dict[str, Any]], as_of: date, splits: tuple[tuple[date, float], ...] = (),
) -> list[dict[str, Any]]:
    periods: dict[tuple[date, date], dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: (item["filed"], -item["priority"])):
        if row["filed"] > as_of or row["end"] > as_of:
            continue
        factor = math.prod(ratio for split_date, ratio in splits if row["filed"] < split_date)
        periods[(row["start"], row["end"])] = {**row, "val": row["val"] / factor, "reportedValue": row["val"], "splitAdjustment": factor}
    return sorted(periods.values(), key=lambda item: (item["end"], item["start"]))


def quarter_at(periods: list[dict[str, Any]], end: date) -> dict[str, Any] | None:
    ending = [item for item in periods if item["end"] == end]
    direct = [item for item in ending if 60 <= (item["end"] - item["start"]).days <= 110]
    if direct:
        return max(direct, key=lambda item: item["filed"])
    for cumulative in ending:
        previous = [item for item in periods if item["start"] == cumulative["start"] and 60 <= (end - item["end"]).days <= 110]
        if previous:
            prior = max(previous, key=lambda item: item["end"])
            return {
                **cumulative, "start": prior["end"] + timedelta(days=1),
                "val": cumulative["val"] - prior["val"],
                "filed": max(cumulative["filed"], prior["filed"]),
                "derived": "cumulative minus previous cumulative",
            }
    return None


def trailing_year(periods: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not periods:
        return None
    end = max(item["end"] for item in periods)
    ending = [item for item in periods if item["end"] == end]
    annuals = [item for item in periods if 330 <= (item["end"] - item["start"]).days <= 400]
    current_annual = [item for item in annuals if item["end"] == end]
    if current_annual:
        return max(current_annual, key=lambda item: item["filed"])
    for current in sorted(ending, key=lambda item: item["start"]):
        previous_annuals = [item for item in annuals if 0 <= (current["start"] - item["end"]).days <= 8]
        for annual in previous_annuals:
            comparable = [item for item in periods if item["start"] == annual["start"] and abs((end - item["end"]).days - 365) <= 14]
            if comparable:
                prior = max(comparable, key=lambda item: item["filed"])
                return {
                    **current, "start": prior["end"] + timedelta(days=1),
                    "val": annual["val"] + current["val"] - prior["val"],
                    "filed": max(annual["filed"], current["filed"], prior["filed"]),
                    "derived": "last fiscal year + current YTD - prior comparable YTD",
                }
    quarters = [quarter for endpoint in sorted({item["end"] for item in periods}) if (quarter := quarter_at(periods, endpoint))]
    latest = quarters[-4:]
    if len(latest) == 4 and latest[-1]["end"] == end:
        contiguous = all(0 <= (latest[index]["start"] - latest[index - 1]["end"]).days <= 8 for index in range(1, 4))
        if contiguous and 330 <= (end - latest[0]["start"]).days <= 400:
            return {**latest[-1], "start": latest[0]["start"], "val": sum(item["val"] for item in latest), "filed": max(item["filed"] for item in latest), "derived": "four contiguous quarters"}
    return None


def trailing_eps(periods: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not periods:
        return None
    end = max(item["end"] for item in periods)
    quarters = [item for item in periods if 60 <= (item["end"] - item["start"]).days <= 110 and not item.get("derived")]
    by_end = {}
    for item in sorted(quarters, key=lambda row: row["filed"]):
        by_end[item["end"]] = item
    latest = [by_end[endpoint] for endpoint in sorted(by_end)][-4:]
    if len(latest) != 4 or latest[-1]["end"] != end:
        return None
    if any((latest[index]["start"] - latest[index - 1]["end"]).days != 1 for index in range(1, 4)):
        return None
    if not 330 <= (end - latest[0]["start"]).days <= 400:
        return None
    return {
        **latest[-1], "start": latest[0]["start"],
        "val": sum(item["val"] for item in latest),
        "filed": max(item["filed"] for item in latest),
        "derived": "sum of four reported standalone diluted quarterly EPS",
        "components": latest,
    }


def percent_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return round(100 * (current / previous - 1), 2)


def normalize_financials(document: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    series = {key: periods_as_of(observations(document, concepts, "USD/shares" if key == "eps" else "USD"), as_of) for key, concepts in CONCEPTS.items()}
    if not series["revenue"]:
        raise ValueError("No dated USD revenue facts; cannot publish a financial snapshot")
    end = max(item["end"] for item in series["revenue"])
    basis = quarter_at(series["revenue"], end)
    if basis:
        period_type = "quarter"
    else:
        basis = min((item for item in series["revenue"] if item["end"] == end), key=lambda item: item["start"])
        period_type = "annual" if (end - basis["start"]).days >= 330 else "ytd"
    matched = {}
    for key, periods in series.items():
        period = quarter_at(periods, end) if period_type == "quarter" else next((item for item in periods if item["end"] == end and item["start"] == basis["start"]), None)
        matched[key] = period if period and period["start"] == basis["start"] else None
    result = {key: row["val"] if row else None for key, row in matched.items() if key != "eps"}
    cash, capex = result["operatingCashFlow"], result["capex"]
    result["freeCashFlow"] = cash - capex if cash is not None and capex is not None else None
    for key, periods in series.items():
        trailing = trailing_eps(periods) if key == "eps" else trailing_year(periods)
        result[f"{key}Ttm"] = trailing["val"] if trailing and trailing["end"] == end else None
    result["freeCashFlowTtm"] = result["operatingCashFlowTtm"] - result["capexTtm"] if result["operatingCashFlowTtm"] is not None and result["capexTtm"] is not None else None
    growth = {}
    for key in ("revenue", "netIncome"):
        candidates = [endpoint for endpoint in {item["end"] for item in series[key]} if abs((end - endpoint).days - 365) <= 14]
        prior = quarter_at(series[key], max(candidates)) if candidates and period_type == "quarter" else None
        if candidates and period_type == "annual":
            prior = next((item for item in series[key] if item["end"] == max(candidates) and (item["end"] - item["start"]).days >= 330), None)
        growth[f"{key}YoY"] = percent_change(result[key], prior["val"] if prior else None)
    result.update(growth)
    result.update({"cashDelta": None, "capexDelta": None, "fcfDelta": None, "marginalCoverage": None})
    prior_ends = [endpoint for endpoint in {item["end"] for item in series["revenue"]} if 60 <= (end - endpoint).days <= 110]
    if period_type == "quarter" and prior_ends:
        prior_end = max(prior_ends)
        prior_cash = quarter_at(series["operatingCashFlow"], prior_end)
        prior_capex = quarter_at(series["capex"], prior_end)
        if cash is not None and capex is not None and prior_cash and prior_capex and prior_cash["start"] == prior_capex["start"]:
            cash_delta = cash - prior_cash["val"]
            capex_delta = capex - prior_capex["val"]
            result.update({"cashDelta": cash_delta, "capexDelta": capex_delta, "fcfDelta": cash_delta - capex_delta, "marginalCoverage": round(cash_delta / capex_delta, 4) if capex_delta > 0 else None})
    result.update({
        "schemaVersion": 3, "currency": "USD", "periodType": period_type,
        "periodStart": basis["start"].isoformat(), "periodEnd": end.isoformat(),
        "filedAt": max(row["filed"] for row in matched.values() if row).isoformat(),
        "form": basis["form"], "accession": basis["accn"], "source": "SEC Company Facts",
        "capexConcept": matched["capex"]["concept"] if matched["capex"] else None,
        "cashFlowBasis": "Operating cash flow less cash paid for productive assets/PPE; excludes unpaid finance-lease additions and does not net disposal proceeds.",
        "quarterly": period_type == "quarter", "periodAligned": True,
    })
    return result