from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pypdf import PdfReader
import requests

from backend.earnings_reports import cached_html, cached_pdf, text_dates
from backend.financials import percent_change
from backend.quality import annual_summary
from backend.providers import save_json

REPORT_PARSER_VERSION = 2


def parse_release(text: str, year: int, quarter: int, source_url: str, digest: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text)
    publication = text_dates(normalized[:600])
    end_month = quarter * 3
    end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    dates = text_dates(normalized[:1600])
    if not publication or end not in dates or not 0 < (publication[0] - end).days < 100:
        raise ValueError("TSMC publication and quarter-end dates could not be reconciled")
    amount_pattern = r"([\d][\d., ]*)"
    pattern = r"diluted earnings per share of NT\$\s*" + amount_pattern + r"\s*\(US\$\s*" + amount_pattern + r"\s*per ADR unit\)"
    match = re.search(pattern, normalized, re.IGNORECASE)
    if not match:
        raise ValueError("No official diluted USD-per-ADR EPS found; currency conversion not guessed")
    revenue = re.search(r"revenue of NT\s*\$\s*([\d., ]+)\s*billion", normalized, re.IGNORECASE)
    income = re.search(r"net income of NT\s*\$\s*([\d., ]+)\s*billion", normalized, re.IGNORECASE)
    revenue_usd = re.search(r"In US dollars,?\s*(?:the\s+)?(?:first|second|third|fourth)[-\s]+quarter revenue was\s*\$\s*([\d.,]+)\s*billion", normalized, re.IGNORECASE)
    return {
        "start": date(year, (quarter - 1) * 3 + 1, 1).isoformat(), "end": end.isoformat(),
        "filed": publication[0].isoformat(), "val": float(match[2].replace(",", "").replace(" ", "")),
        "epsTwd": float(match[1].replace(",", "").replace(" ", "")), "unit": "USD/shares",
        "sourceUrl": source_url, "sourceHash": digest, "form": "6-K",
        "accn": f"tsmc-ir-{year}-q{quarter}", "concept": "DilutedEarningsLossPerShare",
        "shareBasis": "USD per ADR unit reported by TSMC; one ADR = five ordinary shares",
        "extraction": "Original diluted EPS sentence with explicit USD per ADR unit",
        "evidence": normalized[:1600],
        "revenueTwd": float(revenue[1].replace(",", "").replace(" ", "")) * 1e9 if revenue else None,
        "netIncomeTwd": float(income[1].replace(",", "").replace(" ", "")) * 1e9 if income else None,
        "revenueUsd": float(revenue_usd[1].replace(",", "")) * 1e9 if revenue_usd else None,
    }


def fetch_quarter(year: int, quarter: int, cache: Path) -> dict[str, Any]:
    page_url = f"https://investor.tsmc.com/english/quarterly-results/{year}/q{quarter}"
    soup = BeautifulSoup(cached_html(page_url, cache, max_age=timedelta(minutes=5)), "html.parser")
    link = next((tag["href"] for tag in soup.select("a[href]") if tag.get_text(" ", strip=True).lower() == "earnings release"), None)
    if not link:
        raise ValueError("Quarter page has no published earnings release")
    url = urljoin(page_url, link)
    content = cached_pdf(url, cache)
    reader = PdfReader(BytesIO(content))
    text = reader.pages[0].extract_text() or ""
    return parse_release(text, year, quarter, url, hashlib.sha256(content).hexdigest())


def tsmc_quarters(cache: Path, as_of: date) -> dict[str, Any]:
    path = cache / "quarterly-eps-TSM.json"
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"quarters": []}
    quarters = {row["end"]: row for row in stored["quarters"]}
    if stored.get("parserVersion") != REPORT_PARSER_VERSION:
        for endpoint, row in list(quarters.items()):
            end = date.fromisoformat(endpoint)
            quarters[endpoint] = parse_release(row["evidence"], end.year, (end.month - 1) // 3 + 1, row["sourceUrl"], row["sourceHash"])
    failures = []
    for year in range(as_of.year - 11, as_of.year + 1):
        for quarter in range(1, 5):
            month = quarter * 3
            end = date(year, month, calendar.monthrange(year, month)[1])
            if end >= as_of or (as_of - end).days < 10 or end.isoformat() in quarters:
                continue
            try:
                row = fetch_quarter(year, quarter, cache)
                if date.fromisoformat(row["filed"]) > as_of:
                    continue
                quarters[row["end"]] = row
                print(f"TSM {row['end']} diluted EPS ${row['val']}/ADR", flush=True)
                save_json(path, {"parserVersion": REPORT_PARSER_VERSION, "quarters": [quarters[key] for key in sorted(quarters)], "failures": failures, "updatedAt": datetime.now().isoformat()})
            except (requests.RequestException, ValueError) as error:
                failures.append({"periodEnd": end.isoformat(), "reason": str(error)})
                print(f"TSM {end}: unavailable ({error})", flush=True)
    result = {"parserVersion": REPORT_PARSER_VERSION, "quarters": [quarters[key] for key in sorted(quarters)], "failures": failures, "updatedAt": datetime.now().isoformat()}
    save_json(path, result)
    return {**result, "quarters": [row for row in result["quarters"] if row["filed"] <= as_of.isoformat()]}


def tsmc_eps_document(quarters: list[dict[str, Any]]) -> dict[str, Any]:
    return {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": quarters}}}}, "shareBasis": "Reported quarterly USD ADR EPS; TSMC quarter-specific FX convention"}


def management_cash(text: str, year: int, quarter: int) -> dict[str, Any]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    marker = f"{quarter}Q{str(year)[-2:]}"
    previous = f"{quarter - 1}Q{str(year)[-2:]}" if quarter > 1 else f"4Q{str(year - 1)[-2:]}"
    expected_columns = [marker, previous, f"{quarter}Q{str(year - 1)[-2:]}"]
    sections = {"income": [], "cash": []}
    active = None
    header_valid = False
    for line in lines:
        if re.match(r"^[IVX]+(?:\s*-\s*\d+)?\.\s", line):
            active = "income" if "Operating Income Analysis" in line else "cash" if "Quarterly Cash Flow Analysis" in line else None
            header_valid = False
        if active and line.startswith("(In "):
            header_valid = line.startswith("(In NT$ billions)") and re.findall(r"\b[1-4]Q\d{2}\b", line)[:3] == expected_columns
        if active and header_valid:
            sections[active].append(line)
    values = {}
    labels = {"operatingIncome": "Operating Income", "operatingCashFlow": "Net Operating Sources/(Uses)", "capex": "Capital Expenditures"}
    for key, label in labels.items():
        found = []
        for line in sections["income" if key == "operatingIncome" else "cash"]:
            if not line.startswith(label + " "):
                continue
            numbers = re.findall(r"\(?-?\d[\d,]*\.\d+\)?", line[len(label):])
            if len(numbers) >= 3:
                amount = [float(number.strip("()").replace(",", "")) * (-1 if number.startswith("(") else 1) * 1e9 for number in numbers[:3]]
                found.append(amount)
        if len(found) != 1 or (key == "capex" and any(amount > 0 for amount in found[0])):
            raise ValueError(f"Unambiguous quarterly TSMC {label} table not found")
        values[key] = found[0]
    return values


def latest_financials(cache: Path, as_of: date) -> dict[str, Any]:
    data = tsmc_quarters(cache, as_of)
    rows = data["quarters"]
    if not rows:
        raise ValueError("No verified TSMC quarterly reports")
    latest = rows[-1]
    end = date.fromisoformat(latest["end"])
    quarter = (end.month - 1) // 3 + 1
    page_url = f"https://investor.tsmc.com/english/quarterly-results/{end.year}/q{quarter}"
    soup = BeautifulSoup(cached_html(page_url, cache), "html.parser")
    link = next((tag["href"] for tag in soup.select("a[href]") if tag.get_text(" ", strip=True).lower() == "management report"), None)
    if not link:
        raise ValueError("No TSMC management report for quarterly cash-flow verification")
    url = urljoin(page_url, link)
    content = cached_pdf(url, cache)
    report = PdfReader(BytesIO(content))
    amounts = management_cash("\n".join(page.extract_text(extraction_mode="layout") or "" for page in report.pages), end.year, quarter)
    cash, previous_cash = amounts["operatingCashFlow"][:2]
    capex, previous_capex = (abs(value) for value in amounts["capex"][:2])
    previous_year = next((row for row in rows if row["end"] == end.replace(year=end.year - 1).isoformat()), None)
    annuals = []
    for year in sorted({int(row["end"][:4]) for row in rows}):
        quarters = [row for row in rows if row["end"].startswith(str(year))]
        if len(quarters) == 4 and {row["end"][5:7] for row in quarters} == {"03", "06", "09", "12"}:
            annuals.append({"periodStart": f"{year}-01-01", "periodEnd": f"{year}-12-31", "revenue": sum(row["revenueTwd"] for row in quarters) if all(row["revenueTwd"] is not None for row in quarters) else None, "netIncome": sum(row["netIncomeTwd"] for row in quarters) if all(row["netIncomeTwd"] is not None for row in quarters) else None, "freeCashFlow": None, "sourceUrls": [row["sourceUrl"] for row in quarters]})

    return {
        "schemaVersion": 3, "currency": "TWD", "periodType": "quarter", "quarterly": True,
        "quality": {"version": 1, "currency": "TWD", "periodEnd": latest["end"], **annual_summary(annuals), "roeTtm": None, "longDebtToOcf": None, "cashPerShareProxy": None, "missingReason": "Current same-currency balance-sheet history and quarterly cash history are not yet verified; no USD conversion or missing-as-zero inference."},
        "periodStart": latest["start"], "periodEnd": latest["end"], "periodAligned": True,
        "revenue": latest["revenueTwd"], "netIncome": latest["netIncomeTwd"], "operatingIncome": amounts["operatingIncome"][0],
        "operatingCashFlow": cash, "capex": capex, "freeCashFlow": cash - capex,
        "revenueYoY": percent_change(latest["revenueTwd"], previous_year["revenueTwd"] if previous_year else None),
        "netIncomeYoY": percent_change(latest["netIncomeTwd"], previous_year["netIncomeTwd"] if previous_year else None),
        "cashDelta": cash - previous_cash, "capexDelta": capex - previous_capex,
        "fcfDelta": cash - capex - previous_cash + previous_capex,
        "marginalCoverage": (cash - previous_cash) / (capex - previous_capex) if capex > previous_capex else None,
        "netIncomeTtm": sum(row["netIncomeTwd"] for row in rows[-4:]) if all(row["netIncomeTwd"] is not None for row in rows[-4:]) else None,
        "source": "TSMC official quarterly earnings release and management report",
        "sourceUrl": latest["sourceUrl"], "cashFlowSourceUrl": url,
        "sourceHash": latest["sourceHash"], "cashFlowSourceHash": hashlib.sha256(content).hexdigest(),
        "filedAt": latest["filed"], "form": "IR quarterly report (TIFRS)", "accession": latest["accn"],
        "warning": "Financial amounts are TWD. Valuation separately uses company-reported USD diluted EPS per ADR.",
    }