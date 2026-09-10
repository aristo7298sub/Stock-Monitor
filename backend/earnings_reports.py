from __future__ import annotations

import argparse
import hashlib
import json
import re
from io import BytesIO
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from backend.providers import save_json, sec_headers
from backend.financials import CONCEPTS, observations, periods_as_of, quarter_at


MONTHS = {
    name: index for index, names in enumerate(
        ((), ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
         ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
         ("september", "sept", "sep"), ("october", "oct"), ("november", "nov"), ("december", "dec"))
    ) for name in names
}
DATE_PATTERN = re.compile(r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})\s*,?\s+(20\d{2}|19\d{2})\b", re.IGNORECASE)
PRIMARY_HOSTS = {"www.sec.gov", "data.sec.gov", "www.microsoft.com", "nvidianews.nvidia.com", "www.apple.com", "investor.tsmc.com", "pr.tsmc.com", "abc.xyz", "s206.q4cdn.com", "s2.q4cdn.com", "ir.aboutamazon.com"}


def table_matrix(table) -> list[list[str]]:
    rows = [row for row in table.select("tr") if row.find_parent("table") is table]
    occupied = {}
    width = 0
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row.find_all(["td", "th"], recursive=False):
            while (row_index, column) in occupied:
                column += 1
            text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
            span = min(int(cell.get("colspan", 1)), 100)
            height = min(int(cell.get("rowspan", 1)), 100)
            for row_offset in range(height):
                for offset in range(span):
                    occupied[(row_index + row_offset, column + offset)] = text
            column += span
            width = max(width, column)
    return [[occupied.get((row, column), "") for column in range(width)] for row in range(len(rows))]


def text_dates(text: str) -> list[date]:
    dates = []
    for match in DATE_PATTERN.finditer(text):
        try:
            dates.append(date(int(match[3]), MONTHS[match[1].lower()], int(match[2])))
        except ValueError:
            continue
    return dates


def numeric_cells(cells: list[str]) -> list[float]:
    values = []
    for cell in cells:
        cleaned = cell.replace("\u2212", "-").replace("$", "").replace(",", "").strip()
        if re.fullmatch(r"\(?-?\d+(?:\.\d+)?\)?", cleaned):
            number = float(cleaned.strip("()"))
            values.append(-abs(number) if cleaned.startswith("(") else number)
    return values


def parse_eps_tables(source: str, expected_end: date, filed_at: date, source_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(source, "html.parser")
    candidates = []
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    for table in soup.select("table"):
        cells = table_matrix(table)
        texts = [" ".join(row) for row in cells]
        whole = " ".join(texts).lower()
        if not any(term in whole for term in ("net income", "net earnings", "profit for")):
            continue
        if "diluted" not in whole or "non-gaap" in whole or "reconciliation" in whole:
            continue
        header_end = next((index for index, text in enumerate(texts) if re.match(r"^\s*(?:revenue|net sales|products|total revenue|net income)\b", text, re.IGNORECASE)), min(14, len(texts)))
        header_rows = cells[:header_end]
        header = " ".join(texts[:header_end])
        if not re.search(r"three\s+months|quarter[s]?\s+ended", header, re.IGNORECASE):
            continue
        columns = []
        for column in range(len(cells[0]) if cells else 0):
            column_header = " ".join(row[column] for row in header_rows)
            if expected_end in text_dates(column_header) and re.search(r"three\s+months|quarter[s]?\s+ended", column_header, re.IGNORECASE) and not re.search(r"twelve\s+months|year[s]?\s+ended", column_header, re.IGNORECASE):
                columns.append(column)
        if not columns:
            continue
        earnings_section = False
        for index, row in enumerate(cells):
            text = texts[index].lower()
            shares_row = "shares used" in text or "weighted-average shares" in text or "weighted average shares" in text
            if shares_row:
                earnings_section = False
            if not shares_row and re.search(r"(?:earnings|income|profit).*per.*share", text):
                earnings_section = True
            if "diluted" not in text or "shares" in text and "per" not in text:
                continue
            if not earnings_section:
                continue
            amounts = set(numeric_cells([row[column]])[0] for column in columns if numeric_cells([row[column]]))
            if len(amounts) != 1 or abs(next(iter(amounts))) > 1000:
                continue
            candidates.append({
                "end": expected_end.isoformat(), "filed": filed_at.isoformat(),
                "val": next(iter(amounts)), "unit": "USD/shares", "form": "8-K",
                "sourceUrl": source_url, "sourceHash": digest,
                "evidence": {"header": header, "row": texts[index]},
                "extraction": "GAAP standalone quarterly diluted EPS, first dated column",
            })
    if len({row["val"] for row in candidates}) > 1:
        raise ValueError(f"Conflicting GAAP EPS values for {expected_end}: {[row['val'] for row in candidates]}")
    return candidates[:1]


def cached_html(url: str, cache: Path, max_age: timedelta | None = None) -> str:
    if urlsplit(url).netloc not in PRIMARY_HOSTS:
        raise ValueError("Earnings source must be an allowlisted official site")
    digest = hashlib.sha256(url.encode()).hexdigest()
    path = cache / "reports" / f"{digest}.html"
    if path.is_file() and (max_age is None or max_age.total_seconds() > 0 and datetime.now().timestamp() - path.stat().st_mtime < max_age.total_seconds()):
        return path.read_text(encoding="utf-8")
    response = requests.get(url, headers=sec_headers() if urlsplit(url).netloc.endswith("sec.gov") else None, timeout=(10, 40))
    response.raise_for_status()
    source = response.content.decode("utf-8", errors="replace")
    if "<html" not in source.lower():
        raise ValueError("Expected a filing HTML document")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(source, encoding="utf-8", newline="")
    temporary.replace(path)
    return source


def cached_pdf(url: str, cache: Path) -> bytes:
    if urlsplit(url).netloc not in PRIMARY_HOSTS:
        raise ValueError("PDF must be on an allowlisted official source")
    path = cache / "reports" / f"{hashlib.sha256(url.encode()).hexdigest()}.pdf"
    if path.is_file():
        return path.read_bytes()
    response = requests.get(url, timeout=(10, 45))
    response.raise_for_status()
    if not response.content.startswith(b"%PDF-"):
        raise ValueError("Official PDF URL returned a non-PDF response")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_bytes(response.content)
    temporary.replace(path)
    return response.content


def parse_pdf_eps_text(text: str, expected_end: date) -> tuple[float, dict[str, str]] | None:
    lines = text.splitlines()
    normalized = [re.sub(r"\s+", " ", line).strip() for line in lines]
    lower = " ".join(normalized).lower()
    if not re.search(r"statements? of (?:income|operations)", lower) or "reconciliation" in lower or "non-gaap" in lower:
        return None
    data_start = next((index for index, line in enumerate(normalized) if re.match(r"(?:net sales|net product|revenue[s]?)\b", line, re.IGNORECASE)), None)
    if data_start is None:
        return None
    header_lines = lines[:data_start]
    quarter_headers = [(index, match.start()) for index, line in enumerate(header_lines) for match in re.finditer(r"Three\s+Months\s+Ended|Quarter\s+Ended", line, re.IGNORECASE)]
    annual_headers = [(index, match.start()) for index, line in enumerate(header_lines) for match in re.finditer(r"T\s*w\s*e\s*l\s*v\s*e\s+M\s*o\s*n\s*t\s*h\s*s\s+E\s*n\s*d\s*e\s*d|Year\s+Ended", line, re.IGNORECASE)]
    if not quarter_headers or not annual_headers:
        return None
    quarter_column = quarter_headers[0][1]
    annual_column = annual_headers[0][1]
    if quarter_column >= annual_column:
        return None
    year_lines = [(index, list(re.finditer(r"\b(?:20|19)\d{2}\b", line))) for index, line in enumerate(header_lines)]
    year_lines = [(index, matches) for index, matches in year_lines if len(matches) >= 4]
    if not year_lines:
        return None
    year_index, year_matches = year_lines[-1]
    if len(year_matches) != 4:
        return None
    quarter_years = year_matches[:2]
    candidate_indexes = [index for index, match in enumerate(quarter_years) if int(match[0]) == expected_end.year]
    if len(candidate_indexes) != 1:
        return None
    selected = candidate_indexes[0]
    date_header = " ".join(normalized[:data_start])
    partial_dates = re.findall(r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})\s*,?", date_header, re.IGNORECASE)
    matching_date = any(MONTHS[month.lower()] == expected_end.month and int(day) == expected_end.day for month, day in partial_dates)
    if not matching_date:
        return None
    eps_section = False
    for index in range(data_start, len(lines)):
        label = normalized[index].lower()
        if "shares used" in label or "weighted-average shares" in label or "weighted average shares" in label:
            eps_section = False
        elif re.search(r"(?:earnings|income).*per.*share", label):
            eps_section = True
        if not eps_section or "diluted" not in label or "calculation" in label or "weighted" in label:
            continue
        numeric_line = lines[index]
        evidence_line = normalized[index]
        amounts = list(re.finditer(r"(?<![\w.])\(?-?\d+\.\d+\)?(?![\w.])", numeric_line))
        if not amounts and index + 1 < len(lines) and "share" in label and "number of shares" not in label:
            numeric_line = lines[index + 1]
            evidence_line += " " + normalized[index + 1]
            amounts = list(re.finditer(r"(?<![\w.])\(?-?\d+\.\d+\)?(?![\w.])", numeric_line))
        if len(amounts) != 4:
            continue
        coordinates_match = all(abs(amount.end() - year.end()) <= 25 for amount, year in zip(amounts, year_matches))
        if not coordinates_match:
            continue
        amount = amounts[selected][0]
        value = float(amount.strip("()"))
        if amount.startswith("("):
            value = -abs(value)
        return value, {"header": date_header, "yearRow": normalized[year_index], "row": evidence_line, "quarterColumn": str(selected + 1)}
    return None


def parse_pdf_eps(content: bytes, expected_end: date, filed_at: date, source_url: str) -> list[dict[str, Any]]:
    reader = PdfReader(BytesIO(content))
    found = []
    for number, page in enumerate(reader.pages):
        text = page.extract_text(extraction_mode="layout") or ""
        parsed = parse_pdf_eps_text(text, expected_end)
        if parsed:
            value, evidence = parsed
            found.append({"end": expected_end.isoformat(), "filed": filed_at.isoformat(), "val": value, "unit": "USD/shares", "form": "8-K", "sourceUrl": source_url, "sourceHash": hashlib.sha256(content).hexdigest(), "evidence": {**evidence, "page": number + 1}, "extraction": "GAAP standalone diluted EPS from dated PDF quarter column"})
    if len({row["val"] for row in found}) > 1:
        raise ValueError(f"Conflicting quarterly diluted EPS in {source_url}")
    return found[:1]


def q4_reports(host: str, year: int, cache: Path) -> list[dict[str, Any]]:
    path = cache / "reports" / f"index-{urlsplit(host).netloc}-{year}.json"
    if path.is_file() and (year < date.today().year - 1 or datetime.now().timestamp() - path.stat().st_mtime < 300):
        return json.loads(path.read_text(encoding="utf-8"))
    response = requests.get(host + "/feed/FinancialReport.svc/GetFinancialReportList", params={"LanguageId": 1, "year": year, "pageSize": -1, "pageNumber": 0}, timeout=(10, 35))
    response.raise_for_status()
    rows = response.json()["GetFinancialReportListResult"]
    save_json(path, rows)
    return rows


def quarter_number(symbol: str, end: date) -> tuple[int, int]:
    if symbol == "AAPL":
        return end.year + (end.month == 12), {12: 1, 3: 2, 4: 2, 6: 3, 7: 3, 9: 4}[end.month]
    if symbol == "MSFT":
        return end.year + (end.month > 6), {9: 1, 12: 2, 3: 3, 6: 4}[end.month]
    if symbol == "NVDA":
        return end.year + (end.month > 2), {1: 4, 2: 4, 4: 1, 5: 1, 7: 2, 8: 2, 10: 3, 11: 3}[end.month]
    return end.year, (end.month - 1) // 3 + 1


def quarter_start(symbol: str, end: date, fallback: date) -> date:
    if symbol in {"MSFT", "GOOGL", "GOOG", "AMZN"}:
        return date(end.year, end.month - 2, 1)
    return fallback


def primary_eps(symbol: str, end: date, filed: date, cache: Path) -> list[dict[str, Any]]:
    fiscal_year, quarter = quarter_number(symbol, end)
    word = ("first", "second", "third", "fourth")[quarter - 1]
    if symbol == "MSFT":
        url = f"https://www.microsoft.com/en-us/Investor/earnings/FY-{fiscal_year}-Q{quarter}/press-release-webcast"
        return parse_eps_tables(cached_html(url, cache), end, filed, url)
    if symbol == "NVDA":
        slug = f"nvidia-announces-financial-results-for-{word}-quarter{'-and' if quarter == 4 else ''}-fiscal-{fiscal_year}"
        url = "https://nvidianews.nvidia.com/news/" + slug
        return parse_eps_tables(cached_html(url, cache), end, filed, url)
    if symbol == "AAPL":
        url = f"https://www.apple.com/newsroom/{filed.year}/{filed.month:02d}/apple-reports-{word}-quarter-results/"
        source = cached_html(url, cache)
        values = parse_eps_tables(source, end, filed, url)
        if values:
            return values
        soup = BeautifulSoup(source, "html.parser")
        links = [urljoin(url, tag["href"]) for tag in soup.select("a[href]") if tag["href"].lower().endswith(".pdf") and "financial" in (tag.get_text() + tag["href"]).lower()]
        for target in links[:2]:
            values = parse_pdf_eps(cached_pdf(target, cache), end, filed, target)
            if values:
                return values
        return []
    if symbol in {"GOOGL", "GOOG", "AMZN"}:
        host = "https://ir.aboutamazon.com" if symbol == "AMZN" else "https://abc.xyz"
        reports = q4_reports(host, end.year, cache)
        wanted = word.title() + " Quarter"
        links = [doc["DocumentPath"] for report in reports if report["ReportSubType"] == wanted for doc in report.get("Documents", []) if "news" in (doc.get("DocumentCategory") or "") and (doc.get("DocumentFileType") or "").upper() == "PDF"]
        for target in links[:2]:
            values = parse_pdf_eps(cached_pdf(target, cache), end, filed, target)
            if values:
                return values
        return []
    return []


def supplement_quarterly_eps(symbol: str, cik: str, document: dict[str, Any], cache: Path, as_of: date) -> dict[str, Any]:
    path = cache / f"quarterly-eps-{symbol}.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"quarters": []}
    supplements = {row["end"]: row for row in existing.get("quarters", [])}
    for row in supplements.values():
        row["start"] = quarter_start(symbol, date.fromisoformat(row["end"]), date.fromisoformat(row["start"])).isoformat()
    source_eps = observations(document, CONCEPTS["eps"], "USD/shares")
    revenue_periods = periods_as_of(observations(document, CONCEPTS["revenue"]), as_of)
    start = as_of.replace(year=as_of.year - 12)
    targets = [quarter for end in sorted({item["end"] for item in revenue_periods if start <= item["end"] <= as_of}) if (quarter := quarter_at(revenue_periods, end))]
    missing = [quarter for quarter in targets if not any(row["start"] == quarter["start"] and row["end"] == quarter["end"] and 0 <= (row["filed"] - row["end"]).days <= 100 for row in source_eps)]
    releases = submissions(cik, cache, start=start) if any(item["end"].isoformat() not in supplements for item in missing) else []
    failures = []
    for quarter in missing:
        key = quarter["end"].isoformat()
        if key in supplements:
            continue
        candidates = [row for row in releases if row["form"] == "8-K" and "2.02" in row["items"] and 0 < (date.fromisoformat(row["filingDate"]) - quarter["end"]).days <= 100]
        candidates.sort(key=lambda row: row["filingDate"])
        if not candidates:
            failures.append({"periodEnd": key, "reason": "Original earnings filing date unavailable"})
            continue
        release = candidates[0]
        try:
            values = primary_eps(symbol, quarter["end"], date.fromisoformat(release["filingDate"]), cache)
            if not values:
                raise ValueError("No unambiguous dated standalone GAAP EPS column found")
            supplement = {**values[0], "start": quarter_start(symbol, quarter["end"], quarter["start"]).isoformat(), "accn": release["accessionNumber"], "priority": -1, "concept": "EarningsPerShareDiluted"}
            supplements[key] = supplement
            print(f"EPS {symbol} {key}: {supplement['val']} ({supplement['sourceUrl']})", flush=True)
            save_json(path, {"quarters": [supplements[key] for key in sorted(supplements)], "failures": failures, "updatedAt": datetime.now().isoformat()})
        except (requests.RequestException, ValueError) as error:
            failures.append({"periodEnd": key, "reason": str(error)})
            print(f"EPS {symbol} {key}: unavailable ({error})", flush=True)
    save_json(path, {"quarters": [supplements[key] for key in sorted(supplements)], "failures": failures, "updatedAt": datetime.now().isoformat()})
    augmented = json.loads(json.dumps(document))
    eps = augmented.setdefault("facts", {}).setdefault("us-gaap", {}).setdefault("EarningsPerShareDiluted", {}).setdefault("units", {}).setdefault("USD/shares", [])
    eps.extend(supplements.values())
    augmented["supplementalEps"] = {"count": len(supplements), "failures": failures}
    return augmented


def filing_url(cik: str, record: dict[str, str]) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{record['accessionNumber'].replace('-', '')}/{record['primaryDocument']}"


def filing_rows(recent: dict[str, Any]) -> list[dict[str, str]]:
    fields = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items")
    return [{field: recent.get(field, [])[index] if index < len(recent.get(field, [])) else "" for field in fields} for index in range(len(recent.get("form", [])))]


def submissions(cik: str, cache: Path, start: date | None = None) -> list[dict[str, str]]:
    response = requests.get(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json", headers=sec_headers(), timeout=(10, 40))
    response.raise_for_status()
    payload = response.json()
    rows = filing_rows(payload["filings"]["recent"])
    if start is not None:
        for archive in payload["filings"].get("files", []):
            if archive.get("filingTo", "") < start.isoformat():
                continue
            path = cache / "submissions" / archive["name"]
            if path.is_file():
                archived = json.loads(path.read_text(encoding="utf-8"))
            else:
                response = requests.get(f"https://data.sec.gov/submissions/{archive['name']}", headers=sec_headers(), timeout=(10, 40))
                response.raise_for_status()
                archived = response.json()
                save_json(path, archived)
            rows.extend(filing_rows(archived))
    return rows


def exhibits(cik: str, record: dict[str, str], cache: Path) -> list[tuple[str, str]]:
    url = filing_url(cik, record)
    source = cached_html(url, cache)
    soup = BeautifulSoup(source, "html.parser")
    urls = []
    for tag in soup.select("a[href]"):
        href = tag["href"]
        if href.startswith("#") or not re.search(r"99|earnings|release", href, re.IGNORECASE):
            continue
        target = urljoin(url, href)
        if urlsplit(target).netloc == "www.sec.gov" and target not in urls and target.endswith((".htm", ".html")):
            urls.append(target)
    return [(target, cached_html(target, cache)) for target in urls[:3]]


def inspect_report(symbol: str, cik: str, month: str, end: str, cache: Path) -> None:
    records = [row for row in submissions(cik, cache) if row["form"] == "8-K" and row["filingDate"].startswith(month) and "2.02" in row["items"]]
    print(symbol, "candidates", len(records), flush=True)
    for record in records[:1]:
        for url, source in exhibits(cik, record, cache):
            extracted = parse_eps_tables(source, date.fromisoformat(end), date.fromisoformat(record["filingDate"]), url)
            print(url, json.dumps(extracted, ensure_ascii=False), flush=True)
            if not extracted:
                soup = BeautifulSoup(source, "html.parser")
                for table in soup.select("table"):
                    text = table.get_text(" | ", strip=True)
                    if "diluted" in text.lower() and "net income" in text.lower():
                        print(text[:6500], flush=True)
                        break


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect primary quarterly EPS exhibits without modifying financial data")
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    if not args.inspect:
        return
    cache = Path(__file__).resolve().parents[1] / "data" / "cache"
    for symbol, cik, month, end in (("MSFT", "0000789019", "2026-07", "2026-06-30"), ("NVDA", "0001045810", "2026-02", "2026-01-25"), ("AMZN", "0001018724", "2026-02", "2025-12-31"), ("GOOGL", "0001652044", "2026-02", "2025-12-31")):
        try:
            inspect_report(symbol, cik, month, end, cache)
        except (requests.RequestException, ValueError) as error:
            print(symbol, "CHECK_FAILED", str(error), flush=True)


if __name__ == "__main__":
    main()