from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Iterable

import exchange_calendars

from backend.financials import CONCEPTS, observations, periods_as_of, trailing_eps

ALGORITHM_VERSION = 4


def published_valuation(value: dict[str, Any] | None, include_history: bool = False, as_of: date | None = None) -> dict[str, Any] | None:
    if value is None:
        return None
    if value.get("algorithmVersion") != ALGORITHM_VERSION:
        return {
            "pe": None, "forwardPe": None, "percentile10y": None,
            "asOf": value.get("asOf", ""), "status": "withdrawn",
            "reason": "旧估值已撤回：累计 EPS 拼接口径或年度采样不满足统一日频估值标准。",
            "algorithmVersion": ALGORITHM_VERSION, "sampleCount": 0,
        }
    result = dict(value)
    if value.get("currentPeQualified"):
        current_date = as_of or datetime.now(timezone.utc).date()
        priced_on = date.fromisoformat(value["asOf"])
        closed = date.fromisoformat(last_closed_session(current_date))
        lag = len(trading_sessions(priced_on + timedelta(days=1), closed)) if priced_on < closed else 0
        earnings_age = (current_date - date.fromisoformat(value["epsPeriodEnd"])).days
        if lag > 1 or earnings_age > 160:
            result.update({"status": "stale", "currentPeQualified": False, "percentile": None, "percentile10y": None, "referencePrices": [], "reason": "价格或盈利数据已过期，保留原值但停止价格判断。", "priceLagSessions": lag})
    if not include_history:
        result.pop("history", None)
        result.pop("earningsTimeline", None)
    return result


SPLITS = {
    "AAPL": ((date(2020, 8, 31), 4.0),),
    "GOOGL": ((date(2022, 7, 18), 20.0),),
    "GOOG": ((date(2022, 7, 18), 20.0),),
    "AMZN": ((date(2022, 6, 6), 20.0),),
    "NVDA": ((date(2021, 7, 20), 4.0), (date(2024, 6, 10), 10.0)),
    "MSFT": (),
    "TSM": (),
}

def years_before(as_of: date, years: int = 10) -> date:
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:
        return as_of.replace(year=as_of.year - years, day=28)


def pe_percentile(
    observations: Iterable[dict[str, Any]],
    current_pe: float,
    as_of: date,
    years: int = 10,
) -> dict[str, Any]:
    if not math.isfinite(current_pe) or current_pe <= 0:
        raise ValueError("P/E requires positive, finite trailing earnings and price")
    if years < 1:
        raise ValueError("Lookback years must be positive")
    start = years_before(as_of, years)
    by_date: dict[date, float] = {}
    excluded = 0
    for observation in observations:
        try:
            observed = date.fromisoformat(str(observation["date"])[:10])
            value = float(observation["pe"])
        except (KeyError, TypeError, ValueError):
            excluded += 1
            continue
        if not start <= observed <= as_of or not math.isfinite(value) or value <= 0:
            excluded += 1
            continue
        by_date[observed] = value
    if not by_date:
        raise ValueError("No valid positive P/E observations in the lookback window")
    values = sorted(by_date.values())
    count = len(values)
    return {
        "pe": current_pe,
        "percentile10y": round(100 * bisect_right(values, current_pe) / count, 2),
        "sampleCount": count,
        "excludedCount": excluded,
        "windowStart": start.isoformat(),
        "windowEnd": as_of.isoformat(),
        "historyStart": min(by_date).isoformat(),
        "historyEnd": max(by_date).isoformat(),
        "minimumPe": min(values),
        "maximumPe": max(values),
        "method": "100 * count(historical_pe <= current_pe) / valid_sample_count",
        "history": [{"date": observed.isoformat(), "pe": value} for observed, value in sorted(by_date.items())],
    }


def eps_timeline(document: dict[str, Any], symbol: str, as_of: date) -> list[dict[str, Any]]:
    if symbol not in SPLITS:
        raise ValueError(f"Split-adjustment policy not configured for {symbol}")
    rows = observations(document, CONCEPTS["eps"], "USD/shares")
    splits = tuple(item for item in SPLITS[symbol] if item[0] <= as_of)
    events = []
    for filed in sorted({item["filed"] for item in rows if item["filed"] <= as_of}):
        periods = periods_as_of(rows, filed, splits)
        trailing = trailing_eps(periods)
        events.append({
            "availableOn": (filed + timedelta(days=1)).isoformat(),
            "filedAt": filed.isoformat(),
            "periodEnd": max(item["end"] for item in periods).isoformat(),
            "eps": trailing["val"] if trailing else None,
            "accession": trailing["accn"] if trailing else None,
            "reason": None if trailing else "Four consecutive reported quarterly EPS are not available",
            "components": [
                {"start": row["start"].isoformat(), "end": row["end"].isoformat(), "filedAt": row["filed"].isoformat(),
                 "eps": row["val"], "reportedEps": row["reportedValue"], "splitAdjustment": row["splitAdjustment"],
                 "accession": row["accn"], "sourceUrl": row.get("sourceUrl"), "sourceHash": row.get("sourceHash"),
                 "extraction": row.get("extraction", "SEC standard diluted EPS fact"), "evidence": row.get("evidence")}
                for row in (trailing["components"] if trailing else [])
            ],
        })
    return events


@lru_cache(maxsize=32)
def trading_sessions(start: date, end: date) -> tuple[str, ...]:
    calendar = exchange_calendars.get_calendar("XNYS", start=start - timedelta(days=14), end=end + timedelta(days=14))
    return tuple(item.date().isoformat() for item in calendar.sessions_in_range(start.isoformat(), end.isoformat()))


def last_closed_session(as_of: date) -> str:
    calendar = exchange_calendars.get_calendar("XNYS", start=as_of - timedelta(days=15), end=as_of + timedelta(days=2))
    sessions = calendar.sessions_in_range((as_of - timedelta(days=10)).isoformat(), as_of.isoformat())
    now = datetime.now(timezone.utc)
    completed = [session for session in sessions if as_of != now.date() or calendar.session_close(session).to_pydatetime() <= now]
    return completed[-1].date().isoformat()


def distribution_value(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def split_checks(prices: list[dict[str, Any]], symbol: str, as_of: date) -> list[dict[str, Any]]:
    checks = []
    for split_date, ratio in SPLITS[symbol]:
        if split_date > as_of:
            continue
        before = [item for item in prices if item["date"] < split_date.isoformat()]
        after = [item for item in prices if item["date"] >= split_date.isoformat()]
        if not before or not after:
            continue
        price_ratio = before[-1]["close"] / after[0]["close"]
        if not 0.5 <= price_ratio <= 2:
            raise ValueError(f"Price discontinuity at {symbol} split {split_date}; split-adjusted prices not verified")
        checks.append({"effectiveDate": split_date.isoformat(), "splitRatio": ratio, "priceBefore": before[-1]["close"], "priceAfter": after[0]["close"], "priceRatio": price_ratio, "status": "passed"})
    return checks


def daily_valuation(prices: list[dict[str, Any]], document: dict[str, Any], symbol: str, as_of: date) -> dict[str, Any]:
    prices_by_date = {item["date"]: item for item in prices if item["date"] <= as_of.isoformat() and math.isfinite(item["close"]) and item["close"] > 0}
    prices = [prices_by_date[key] for key in sorted(prices_by_date)]
    if not prices:
        raise ValueError("No dated price observations")
    price_checks = split_checks(prices, symbol, as_of)
    events = eps_timeline(document, symbol, as_of)
    samples = []
    missing_dates = []
    loss_dates = []
    states = {}
    cursor = 0
    earnings = None
    latest_price = prices[-1]
    for price in prices:
        while cursor < len(events) and events[cursor]["availableOn"] <= price["date"]:
            earnings = events[cursor]
            cursor += 1
        if not earnings or earnings["eps"] is None:
            missing_dates.append(price["date"])
            states[price["date"]] = "missing_eps"
            continue
        if (date.fromisoformat(price["date"]) - date.fromisoformat(earnings["periodEnd"])).days > 160:
            missing_dates.append(price["date"])
            states[price["date"]] = "stale_eps"
            continue
        if earnings["eps"] <= 0:
            loss_dates.append(price["date"])
            states[price["date"]] = "nonpositive_eps"
            continue
        states[price["date"]] = "valid"
        samples.append({"date": price["date"], "price": price["close"], "pe": price["close"] / earnings["eps"], "eps": earnings["eps"], "epsFiledAt": earnings["filedAt"], "epsPeriodEnd": earnings["periodEnd"]})
    if not samples or samples[-1]["date"] != latest_price["date"]:
        raise ValueError("Latest trailing earnings are missing, stale, or non-positive; P/E is not meaningful")
    valuation_date = date.fromisoformat(latest_price["date"])
    current_pe = samples[-1]["pe"]
    windows = []
    for years in (10, 5, 3, 1):
        expected = trading_sessions(years_before(valuation_date, years), valuation_date)
        missing = [day for day in expected if states.get(day) not in {"valid", "nonpositive_eps"}]
        valid = [item for item in samples if years_before(valuation_date, years).isoformat() <= item["date"] <= latest_price["date"]]
        price_missing = [day for day in expected if day not in prices_by_date]
        largest_gap = 0
        gap = 0
        for day in expected:
            gap = gap + 1 if day in missing else 0
            largest_gap = max(largest_gap, gap)
        coverage = (len(expected) - len(missing)) / len(expected)
        qualified = coverage >= 0.995 and len(price_missing) <= 2 and largest_gap <= 3 and len(valid) >= 200 * years
        windows.append({"years": years, "qualified": qualified, "expectedSessions": len(expected), "pricedSessions": len(expected) - len(price_missing), "validSamples": len(valid), "missingEarningsSessions": len(missing), "nonpositiveEarningsSessions": sum(states.get(day) == "nonpositive_eps" for day in expected), "coveragePercent": round(coverage * 100, 3), "maxMissingRun": largest_gap, "missingDateExamples": missing[:5], "percentile": round(100 * sum(item["pe"] <= current_pe for item in valid) / len(valid), 2) if qualified else None})
    selected = next((window for window in windows if window["qualified"]), None)
    horizon = selected["years"] if selected else None
    selected_samples = [item for item in samples if years_before(valuation_date, horizon or 10).isoformat() <= item["date"]]
    reference = []
    if selected:
        reference = [{"percentile": percentile, "pe": distribution_value([row["pe"] for row in selected_samples], percentile / 100), "price": distribution_value([row["pe"] for row in selected_samples], percentile / 100) * earnings["eps"]} for percentile in (20, 50, 80)]
    closed = last_closed_session(as_of)
    lag = len(trading_sessions(valuation_date + timedelta(days=1), date.fromisoformat(closed))) if closed > latest_price["date"] else 0
    stale = lag > 1
    reason = None if horizon == 10 else f"十年盈利覆盖率 {windows[0]['coveragePercent']}%；缺失 {windows[0]['missingEarningsSessions']} 个交易日，不能称为十年分位。"
    return {
        "algorithmVersion": ALGORITHM_VERSION, "status": "stale" if stale else "qualified" if horizon == 10 else "limited" if horizon else "current_only",
        "reason": "行情超过一个交易日未更新，暂停价格判断。" if stale else reason,
        "pe": current_pe, "percentile10y": windows[0]["percentile"] if not stale else None,
        "percentile": selected["percentile"] if selected and not stale else None,
        "horizonYears": horizon, "coverage": windows, "referencePrices": reference if not stale else [],
        "sampleCount": len(selected_samples), "historyStart": selected_samples[0]["date"], "historyEnd": selected_samples[-1]["date"],
        "earningsYieldPercent": 100 / current_pe, "priceLagSessions": lag,
        "currentPeQualified": not stale, "splitChecks": price_checks,
        "frequency": "daily", "basis": "Sum of four reported standalone diluted quarterly EPS; original publication/filing-date availability; split-adjusted",
        "asOf": latest_price["date"], "price": latest_price["close"],
        "epsTtm": earnings["eps"], "epsPeriodEnd": earnings["periodEnd"],
        "epsFiledAt": earnings["filedAt"], "forwardPe": None,
        "earningsComponents": earnings["components"], "earningsTimeline": events,
        "coverageYears": round((valuation_date - date.fromisoformat(samples[0]["date"])).days / 365.25, 2), "missingEarningsDays": len(missing_dates), "nonpositiveEarningsDays": len(loss_dates),
        "source": "Nasdaq + SEC + original company quarterly earnings releases",
        "history": selected_samples,
        "warnings": ["Quarterly diluted EPS sum convention; not annual EPS plus/minus YTD EPS.", "Historical earnings are effective the calendar day after disclosure, so after-hours publication is not used prematurely.", "Ranks are conditional on positive earnings, not forecasts or buy signals."],
    }