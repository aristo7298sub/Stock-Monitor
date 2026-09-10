from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.financials import normalize_financials
from backend.valuation import ALGORITHM_VERSION, published_valuation
from backend.providers import SEC_SUBMISSIONS_URL, fetch_facts, fetch_valuation, sec_headers


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATABASE_PATH = DATA_DIR / "stock-monitor.db"
WEB_DIST = ROOT / "web" / "dist"
CACHE_DIR = DATA_DIR / "cache"
CNBC_URL = (
    "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
    "?symbols={symbols}&requestMethod=quick&noform=1&partnerId=2&fund=1&exthrs=1&output=json"
)
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
QUOTE_TTL = timedelta(seconds=60)
FACTS_TTL = timedelta(hours=24)
FILINGS_INTERVAL = int(os.environ.get("STOCK_MONITOR_FILINGS_SECONDS", "300"))
VALUATION_TTL = timedelta(hours=6)
MONITOR_STARTED_AT: str | None = None
MONITOR_STATE: dict[str, dict[str, Any]] = {}

DEFAULT_COMPANIES = (
    ("NVDA", "NVIDIA Corporation", "0001045810", "NASDAQ"),
    ("MSFT", "Microsoft Corporation", "0000789019", "NASDAQ"),
    ("AMZN", "Amazon.com, Inc.", "0001018724", "NASDAQ"),
    ("GOOGL", "Alphabet Inc.", "0001652044", "NASDAQ"),
    ("AAPL", "Apple Inc.", "0000320193", "NASDAQ"),
    ("TSM", "Taiwan Semiconductor Manufacturing Company Limited", "0001046179", "NYSE"),
)

_ticker_cache: tuple[datetime, list[dict[str, Any]]] | None = None
_refresh_lock = threading.Lock()
_filings_lock = threading.Lock()
_valuation_lock = threading.Lock()


class TrackRequest(BaseModel):
    symbol: str
    name: str | None = None
    cik: str | None = None
    exchange: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
                symbol TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cik TEXT,
                exchange TEXT,
                tracked_at TEXT NOT NULL,
                quote_json TEXT,
                financials_json TEXT,
                quote_updated_at TEXT,
                facts_updated_at TEXT,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS quote_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                price REAL,
                change_percent REAL,
                volume INTEGER,
                UNIQUE(symbol, captured_at)
            );
            CREATE INDEX IF NOT EXISTS idx_quote_history_symbol_time
            ON quote_history(symbol, captured_at DESC);
            CREATE TABLE IF NOT EXISTS refresh_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS filing_events (
                symbol TEXT NOT NULL,
                accession TEXT NOT NULL,
                form TEXT NOT NULL,
                filed_at TEXT NOT NULL,
                report_date TEXT,
                url TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                PRIMARY KEY(symbol, accession)
            );
            CREATE TABLE IF NOT EXISTS financial_versions (
                symbol TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                period_end TEXT,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(symbol, content_hash)
            );
            CREATE TABLE IF NOT EXISTS valuation_samples (
                symbol TEXT NOT NULL,
                observed_on TEXT NOT NULL,
                frequency TEXT NOT NULL,
                pe REAL NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY(symbol, observed_on, frequency)
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(companies)")}
        for column in ("valuation_json", "valuation_updated_at", "valuation_error", "quote_error", "facts_error", "filings_error", "filings_checked_at", "latest_filing_json"):
            if column not in columns:
                connection.execute(f"ALTER TABLE companies ADD COLUMN {column} TEXT")
        now = iso_now()
        connection.executemany(
            """
            INSERT INTO companies(symbol, name, cik, exchange, tracked_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                cik = COALESCE(companies.cik, excluded.cik),
                exchange = COALESCE(companies.exchange, excluded.exchange)
            """,
            [(*company, now) for company in DEFAULT_COMPANIES],
        )


def request_headers(source: str) -> dict[str, str]:
    if source == "sec":
        return sec_headers()
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.cnbc.com",
        "Referer": "https://www.cnbc.com/",
    }


def clean_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not text or text.lower() in {"n/a", "na", "none", "unch"}:
        return None
    try:
        value = float(text)
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def get_symbols() -> list[str]:
    with connect() as connection:
        return [row["symbol"] for row in connection.execute("SELECT symbol FROM companies ORDER BY tracked_at")]


def log_refresh(source: str, status: str, detail: str) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO refresh_events(source, status, detail, created_at) VALUES(?, ?, ?, ?)",
            (source, status, detail[:1000], iso_now()),
        )


def refresh_quotes(symbols: list[str] | None = None) -> int:
    symbols = symbols or get_symbols()
    if not symbols:
        return 0
    with _refresh_lock:
        try:
            url = CNBC_URL.format(symbols=quote("|".join(symbols), safe="%7C"))
            response = requests.get(url, headers=request_headers("cnbc"), timeout=25)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("FormattedQuoteResult", {}).get("FormattedQuote", [])
            if isinstance(rows, dict):
                rows = [rows]
            captured_at = iso_now()
            updated = 0
            with connect() as connection:
                for item in rows:
                    symbol = str(item.get("symbol", "")).upper()
                    if symbol not in symbols:
                        continue
                    price = clean_number(item.get("last"))
                    if price is None or price <= 0:
                        connection.execute("UPDATE companies SET quote_error=? WHERE symbol=?", ("Source returned no valid price; keeping previous quote", symbol))
                        continue
                    change_percent = clean_number(item.get("change_pct"))
                    volume_value = clean_number(item.get("volume"))
                    quote_payload = {
                        "price": price,
                        "changePercent": change_percent,
                        "open": clean_number(item.get("open")),
                        "high": clean_number(item.get("high")),
                        "low": clean_number(item.get("low")),
                        "volume": int(volume_value) if volume_value is not None else None,
                        "asOf": item.get("last_timedate") or item.get("last_time") or captured_at,
                        "source": "CNBC Quick Quote",
                        "receivedAt": captured_at,
                    }
                    connection.execute(
                        "UPDATE companies SET quote_json=?, quote_updated_at=?, quote_error=NULL WHERE symbol=?",
                        (json.dumps(quote_payload), captured_at, symbol),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO quote_history(symbol, captured_at, price, change_percent, volume) VALUES(?, ?, ?, ?, ?)",
                        (symbol, captured_at, price, change_percent, quote_payload["volume"]),
                    )
                    updated += 1
                received = {str(item.get("symbol", "")).upper() for item in rows}
                for missing in set(symbols) - received:
                    connection.execute("UPDATE companies SET quote_error=? WHERE symbol=?", ("No quote in provider response; keeping previous quote", missing))
            log_refresh("cnbc", "ok" if updated == len(symbols) else "partial", f"updated {updated}/{len(symbols)} symbols")
            return updated
        except Exception as error:
            log_refresh("cnbc", "error", str(error))
            with connect() as connection:
                connection.executemany(
                    "UPDATE companies SET quote_error=? WHERE symbol=?",
                    [(f"quote: {error}", symbol) for symbol in symbols],
                )
            return 0


def refresh_company_facts(symbol: str, cik: str | None) -> bool:
    if not cik:
        return False
    try:
        if symbol == "TSM":
            from backend.tsmc import latest_financials
            financials = latest_financials(CACHE_DIR, utc_now().date())
        else:
            document = fetch_facts(cik, CACHE_DIR)
            financials = normalize_financials(document)
            from backend.quality import financial_quality
            financials["quality"] = financial_quality(document, financials, utc_now().date())
            financials["sourceUrl"] = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
        payload = json.dumps(financials, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with connect() as connection:
            previous = connection.execute("SELECT financials_json FROM companies WHERE symbol=?", (symbol,)).fetchone()
            changed = not previous or json.loads(previous["financials_json"] or "null") != financials
            connection.execute(
                "UPDATE companies SET financials_json=?, facts_updated_at=?, facts_error=NULL WHERE symbol=?",
                (payload, iso_now(), symbol),
            )
            connection.execute("INSERT OR IGNORE INTO financial_versions(symbol,content_hash,period_end,observed_at,payload) VALUES(?,?,?,?,?)", (symbol, digest, financials["periodEnd"], iso_now(), payload))
            if changed:
                connection.execute("UPDATE companies SET valuation_updated_at=NULL WHERE symbol=?", (symbol,))
        return True
    except Exception as error:
        with connect() as connection:
            connection.execute("UPDATE companies SET facts_error=? WHERE symbol=?", (f"sec: {error}", symbol))
        return False


def refresh_stale_facts(symbols: list[str] | None = None, force: bool = False) -> int:
    clauses = ""
    params: tuple[Any, ...] = ()
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        clauses = f"WHERE symbol IN ({placeholders})"
        params = tuple(symbols)
    with connect() as connection:
        rows = list(connection.execute(f"SELECT symbol, cik, facts_updated_at, financials_json FROM companies {clauses}", params))
    updated = 0
    failed = 0
    for row in rows:
        last_update = parse_iso(row["facts_updated_at"])
        snapshot = json.loads(row["financials_json"] or "{}")
        if not force and snapshot.get("schemaVersion") == 3 and snapshot.get("quality", {}).get("version") == 1 and last_update and utc_now() - last_update < FACTS_TTL:
            continue
        if refresh_company_facts(row["symbol"], row["cik"]):
            updated += 1
        else:
            failed += 1
    log_refresh("sec", "partial" if failed else "ok", f"updated {updated}; failed {failed}; checked {len(rows)} companies")
    return updated


def parse_filings(payload: dict[str, Any], cik: str) -> list[dict[str, Any]]:
    recent = payload.get("filings", {}).get("recent", {})
    fields = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items")
    events = []
    for index, form in enumerate(recent.get("form", [])):
        record = {field: recent.get(field, [])[index] if index < len(recent.get(field, [])) else "" for field in fields}
        base_form = str(form).removesuffix("/A")
        is_report = base_form in {"10-Q", "10-K", "20-F", "40-F"}
        is_earnings_release = base_form == "8-K" and "2.02" in record["items"]
        is_foreign_report = base_form == "6-K" and bool(re.search(r"fsx|earn|result|quarter", record["primaryDocument"], re.IGNORECASE))
        if not (is_report or is_earnings_release or is_foreign_report):
            continue
        if not record["accessionNumber"] or not record["filingDate"]:
            continue
        accession = record["accessionNumber"]
        events.append({
            "accession": accession, "form": form, "filedAt": record["filingDate"],
            "reportDate": record["reportDate"],
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{record['primaryDocument']}",
        })
    return sorted(events, key=lambda item: (item["filedAt"], item["accession"]), reverse=True)


def financial_report_pending(latest: dict[str, Any] | None, financials: dict[str, Any] | None) -> bool:
    if not latest:
        return False
    if not financials or not financials.get("periodEnd"):
        return True
    form = latest.get("form", "")
    if form.removesuffix("/A") == "8-K" or form.endswith("/A"):
        return (latest.get("filedAt") or "") > (financials.get("filedAt") or "")
    return (latest.get("reportDate") or "") > financials["periodEnd"]


def check_earnings(symbols: list[str] | None = None) -> int:
    if not _filings_lock.acquire(blocking=False):
        return 0
    changed = []
    failed = 0
    try:
        with connect() as connection:
            companies = list(connection.execute("SELECT symbol,cik,latest_filing_json,financials_json,facts_error FROM companies"))
        for company in companies:
            symbol, cik = company["symbol"], company["cik"]
            if not cik or (symbols and symbol not in symbols):
                continue
            try:
                response = requests.get(SEC_SUBMISSIONS_URL.format(cik=str(cik).zfill(10)), headers=sec_headers(), timeout=(10, 30))
                response.raise_for_status()
                events = parse_filings(response.json(), cik)
                previous = json.loads(company["latest_filing_json"] or "{}")
                financials = json.loads(company["financials_json"] or "{}")
                latest = events[0] if events else None
                with connect() as connection:
                    for event in events:
                        connection.execute("INSERT OR IGNORE INTO filing_events(symbol,accession,form,filed_at,report_date,url,discovered_at) VALUES(?,?,?,?,?,?,?)", (symbol, event["accession"], event["form"], event["filedAt"], event["reportDate"], event["url"], iso_now()))
                    connection.execute("UPDATE companies SET latest_filing_json=?,filings_checked_at=?,filings_error=NULL WHERE symbol=?", (json.dumps(latest), iso_now(), symbol))
                    if latest and latest["accession"] != previous.get("accession"):
                        connection.execute("UPDATE companies SET valuation_updated_at=NULL WHERE symbol=?", (symbol,))
                report_pending = financial_report_pending(latest, financials)
                if latest and (latest["accession"] != previous.get("accession") or report_pending or company["facts_error"]):
                    if refresh_company_facts(symbol, cik):
                        changed.append(symbol)
                    else:
                        failed += 1
            except Exception as error:
                failed += 1
                with connect() as connection:
                    connection.execute("UPDATE companies SET filings_error=? WHERE symbol=?", (str(error), symbol))
        refresh_stale_facts(symbols)
        if changed:
            refresh_valuations(changed)
        log_refresh("filings", "partial" if failed else "ok", f"refreshed financial reports {len(changed)}; failed checks {failed}")
        return len(changed)
    finally:
        _filings_lock.release()


def refresh_valuations(symbols: list[str] | None = None, force: bool = False) -> int:
    if not _valuation_lock.acquire(blocking=False):
        return 0
    updated = 0
    failed = 0
    try:
        with connect() as connection:
            companies = list(connection.execute("SELECT symbol,cik,exchange,valuation_updated_at,financials_json,valuation_json,latest_filing_json,valuation_error FROM companies"))
        for company in companies:
            symbol = company["symbol"]
            if symbols and symbol not in symbols:
                continue
            last_update = parse_iso(company["valuation_updated_at"])
            cached = json.loads(company["valuation_json"] or "{}")
            pending = financial_report_pending(json.loads(company["latest_filing_json"] or "null"), json.loads(company["financials_json"] or "null"))
            retrying = pending or company["valuation_error"] or cached.get("status") in {"incomplete", "stale", "withdrawn"}
            ttl = timedelta(minutes=5) if retrying else VALUATION_TTL
            if not force and cached.get("algorithmVersion") == ALGORITHM_VERSION and last_update and utc_now() - last_update < ttl:
                continue
            try:
                result = fetch_valuation(symbol, company["cik"], company["exchange"] or "NASDAQ", utc_now().date(), CACHE_DIR)
                result["calculatedAt"] = iso_now()
                with connect() as connection:
                    current = connection.execute("SELECT financials_json,latest_filing_json FROM companies WHERE symbol=?", (symbol,)).fetchone()
                    if not current:
                        continue
                    if current["financials_json"] != company["financials_json"] or current["latest_filing_json"] != company["latest_filing_json"]:
                        connection.execute("UPDATE companies SET valuation_updated_at=NULL WHERE symbol=?", (symbol,))
                        continue
                    connection.execute("UPDATE companies SET valuation_json=?,valuation_updated_at=?,valuation_error=NULL WHERE symbol=?", (json.dumps(result), iso_now(), symbol))
                    connection.executemany("INSERT INTO valuation_samples(symbol,observed_on,frequency,pe,source) VALUES(?,?,?,?,?) ON CONFLICT(symbol,observed_on,frequency) DO UPDATE SET pe=excluded.pe,source=excluded.source", [(symbol, item["date"], result["frequency"], item["pe"], result["source"]) for item in result["history"]])
                updated += 1
            except Exception as error:
                failed += 1
                with connect() as connection:
                    connection.execute("UPDATE companies SET valuation_error=? WHERE symbol=?", (str(error), symbol))
        log_refresh("valuation", "partial" if failed else "ok", f"updated {updated}; failed {failed}")
        return updated
    finally:
        _valuation_lock.release()


def get_ticker_catalog() -> list[dict[str, Any]]:
    global _ticker_cache
    if _ticker_cache and utc_now() - _ticker_cache[0] < timedelta(hours=24):
        return _ticker_cache[1]
    headers = request_headers("sec")
    headers["Host"] = "www.sec.gov"
    response = requests.get(SEC_TICKERS_URL, headers=headers, timeout=35)
    response.raise_for_status()
    payload = response.json()
    rows = list(payload.values()) if isinstance(payload, dict) else payload
    catalog = [
        {
            "symbol": str(row.get("ticker", "")).upper(),
            "name": str(row.get("title", "")).title(),
            "cik": str(row.get("cik_str", "")).zfill(10),
            "exchange": "US",
        }
        for row in rows
        if row.get("ticker") and row.get("title")
    ]
    _ticker_cache = (utc_now(), catalog)
    return catalog


def search_catalog(query: str, limit: int = 8) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if needle == "aws":
        needle = "amzn"
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for row in get_ticker_catalog():
        symbol = row["symbol"].lower()
        name = row["name"].lower()
        if needle == symbol:
            rank = 0
        elif name == needle:
            rank = 1
        elif symbol.startswith(needle):
            rank = 2
        elif name.startswith(needle):
            rank = 3
        elif needle in symbol or needle in name:
            rank = 4
        else:
            continue
        matches.append((rank, len(name), row))
    matches.sort(key=lambda item: (item[0], item[1], item[2]["symbol"]))
    return [item[2] for item in matches[:limit]]


def company_valuation(row: sqlite3.Row, include_history: bool = False) -> dict[str, Any] | None:
    value = published_valuation(json.loads(row["valuation_json"] or "null"), include_history=include_history)
    financials = json.loads(row["financials_json"] or "null")
    latest = json.loads(row["latest_filing_json"] or "null")
    if value and value.get("currentPeQualified") and (
        financial_report_pending(latest, financials)
        or (financials or {}).get("periodEnd", "") > value.get("epsPeriodEnd", "")
    ):
        value.update({"status": "incomplete", "currentPeQualified": False, "percentile": None, "percentile10y": None, "referencePrices": [], "reason": "已发现更新财报，当前四季盈利尚未追上；暂停使用旧盈利判断价格。"})
    return value


def company_payload(row: sqlite3.Row) -> dict[str, Any]:
    quote_payload = json.loads(row["quote_json"]) if row["quote_json"] else None
    financials = json.loads(row["financials_json"]) if row["financials_json"] else None
    valuation = company_valuation(row)
    latest_filing = json.loads(row["latest_filing_json"] or "null")
    pending_report = financial_report_pending(latest_filing, financials)
    errors = {stage: row[f"{stage}_error"] for stage in ("quote", "facts", "filings", "valuation") if row[f"{stage}_error"]}
    return {
        "symbol": row["symbol"],
        "name": row["name"],
        "cik": row["cik"],
        "exchange": row["exchange"] or "US",
        "quote": quote_payload,
        "financials": financials,
        "valuation": valuation,
        "valuationUpdatedAt": row["valuation_updated_at"],
        "earnings": {"lastCheckedAt": row["filings_checked_at"], "latestFiling": latest_filing, "pendingStructuredData": pending_report},
        "quoteUpdatedAt": row["quote_updated_at"],
        "factsUpdatedAt": row["facts_updated_at"],
        "lastError": "; ".join(f"{stage}: {error}" for stage, error in errors.items()) or None,
        "errors": errors,
    }


def database_companies() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM companies ORDER BY tracked_at, symbol").fetchall()
    return [company_payload(row) for row in rows]


def quote_cache_stale() -> bool:
    with connect() as connection:
        latest = connection.execute("SELECT MAX(quote_updated_at) AS latest FROM companies").fetchone()["latest"]
    timestamp = parse_iso(latest)
    return timestamp is None or utc_now() - timestamp > QUOTE_TTL


async def periodic_job(name: str, interval: int, callback) -> None:
    while True:
        MONITOR_STATE[name] = {**MONITOR_STATE.get(name, {}), "status": "running", "intervalSeconds": interval, "startedAt": iso_now()}
        try:
            count = await asyncio.to_thread(callback)
            MONITOR_STATE[name].update({"status": "waiting", "lastCompletedAt": iso_now(), "updated": count, "error": None})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            MONITOR_STATE[name].update({"status": "error", "lastCompletedAt": iso_now(), "error": str(error)})
            log_refresh(name, "error", str(error))
        await asyncio.sleep(max(1, interval))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global MONITOR_STARTED_AT
    init_database()
    MONITOR_STARTED_AT = iso_now()
    monitors = [
        asyncio.create_task(periodic_job("quotes", 60, refresh_quotes)),
        asyncio.create_task(periodic_job("filings", FILINGS_INTERVAL, check_earnings)),
        asyncio.create_task(periodic_job("valuation", 60, refresh_valuations)),
    ]
    try:
        yield
    finally:
        for monitor in monitors:
            monitor.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)
        MONITOR_STARTED_AT = None


app = FastAPI(title="Stock Monitor", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "name": "Stock Monitor", "time": iso_now(), "monitorStartedAt": MONITOR_STARTED_AT, "jobs": MONITOR_STATE}


@app.get("/api/companies")
def companies() -> dict[str, Any]:
    return {"companies": database_companies(), "generatedAt": iso_now(), "monitor": {"running": MONITOR_STARTED_AT is not None, "filingsIntervalSeconds": FILINGS_INTERVAL, "jobs": MONITOR_STATE}}


@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=80)) -> dict[str, Any]:
    try:
        return {"results": search_catalog(q)}
    except requests.RequestException as error:
        raise HTTPException(status_code=503, detail=f"SEC ticker search unavailable: {error}") from error


@app.post("/api/track")
def track(request: TrackRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    symbol = request.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        raise HTTPException(status_code=400, detail="Invalid US ticker symbol")
    catalog_match = next((row for row in get_ticker_catalog() if row["symbol"] == symbol), None)
    name = request.name or (catalog_match or {}).get("name") or symbol
    cik = request.cik or (catalog_match or {}).get("cik")
    exchange = request.exchange or (catalog_match or {}).get("exchange") or "US"
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO companies(symbol, name, cik, exchange, tracked_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name=excluded.name,
                cik=COALESCE(companies.cik, excluded.cik),
                exchange=COALESCE(companies.exchange, excluded.exchange)
            """,
            (symbol, name, cik, exchange, iso_now()),
        )
        row = connection.execute("SELECT * FROM companies WHERE symbol=?", (symbol,)).fetchone()
    background_tasks.add_task(refresh_quotes, [symbol])
    if cik:
        background_tasks.add_task(check_earnings, [symbol])
        background_tasks.add_task(refresh_valuations, [symbol])
    return {"company": company_payload(row)}


@app.post("/api/refresh", status_code=202)
def refresh(background_tasks: BackgroundTasks) -> dict[str, Any]:
    background_tasks.add_task(refresh_quotes)
    background_tasks.add_task(check_earnings)
    background_tasks.add_task(refresh_stale_facts, force=True)
    background_tasks.add_task(refresh_valuations, force=True)
    return {"status": "queued", "requestedAt": iso_now()}


@app.get("/api/valuation/{symbol}")
def valuation_details(symbol: str) -> dict[str, Any]:
    with connect() as connection:
        row = connection.execute("SELECT * FROM companies WHERE symbol=?", (symbol.upper(),)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Company is not tracked")
    return {"symbol": symbol.upper(), "valuation": company_valuation(row, include_history=True), "error": row["valuation_error"]}


@app.get("/api/filings/{symbol}")
def filing_history(symbol: str) -> dict[str, Any]:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM filing_events WHERE symbol=? ORDER BY filed_at DESC LIMIT 20", (symbol.upper(),)).fetchall()
    return {"symbol": symbol.upper(), "filings": [dict(row) for row in rows]}


@app.get("/api/history/{symbol}")
def history(symbol: str, limit: int = Query(default=240, ge=1, le=2000)) -> dict[str, Any]:
    normalized = symbol.upper()
    with connect() as connection:
        rows = connection.execute(
            "SELECT captured_at, price, change_percent, volume FROM quote_history WHERE symbol=? ORDER BY captured_at DESC LIMIT ?",
            (normalized, limit),
        ).fetchall()
    return {"symbol": normalized, "points": [dict(row) for row in reversed(rows)]}


@app.get("/{path:path}", include_in_schema=False)
def web(path: str) -> FileResponse:
    requested = WEB_DIST / path
    if path and requested.is_file() and WEB_DIST.resolve() in requested.resolve().parents:
        return FileResponse(requested, headers={"Cache-Control": "no-store"} if requested.suffix == ".html" else None)
    index = WEB_DIST / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=503, detail="Web build missing. Run npm run build in web/.")
