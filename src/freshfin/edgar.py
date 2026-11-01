"""Small SEC EDGAR client: company list, recent filings, XBRL company facts.

SEC rules: send a User-Agent with your name and email, stay under 10 requests per second.
Responses are cached on disk so a rerun the same day makes no requests.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DAY = 24 * 3600
RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Filing:
    cik: str
    ticker: str
    form: str
    accession: str
    filed: date
    report_date: date | None

    @property
    def url(self) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/{self.accession.replace('-', '')}/"


class Edgar:
    def __init__(self, user_agent: str, cache_dir: Path | None = None, min_interval: float = 0.12):
        if not user_agent or "@" not in user_agent:
            raise ValueError("Set SEC_USER_AGENT to 'Your Name your@email.com' (SEC requires it).")
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self._last = 0.0
        self._ciks: dict[str, str] | None = None

    # ---- HTTP -------------------------------------------------------------

    def _fetch(self, url: str) -> str:
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body.decode("utf-8")
            except urllib.error.HTTPError as err:
                if err.code in RETRY_STATUS and attempt < 3:
                    log.warning("SEC returned %s for %s, retrying", err.code, url)
                    time.sleep(2**attempt)
                    continue
                raise
        raise RuntimeError("unreachable")

    def _get_json(self, url: str, cache_name: str, max_age: float) -> dict:
        path = self.cache_dir / cache_name if self.cache_dir else None
        if path and path.exists() and time.time() - path.stat().st_mtime < max_age:
            return json.loads(path.read_text())
        text = self._fetch(url)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return json.loads(text)

    # ---- data -------------------------------------------------------------

    def cik(self, ticker: str) -> str:
        if self._ciks is None:
            raw = self._get_json(TICKERS_URL, "company_tickers.json", 7 * DAY)
            self._ciks = {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in raw.values()}
        try:
            return self._ciks[ticker.upper()]
        except KeyError:
            raise LookupError(f"Unknown ticker {ticker}") from None

    def submissions(self, cik: str, max_age: float = DAY) -> dict:
        return self._get_json(SUBMISSIONS_URL.format(cik=cik), f"submissions_{cik}.json", max_age)

    def company_facts(self, cik: str, max_age: float = DAY) -> dict:
        return self._get_json(FACTS_URL.format(cik=cik), f"facts_{cik}.json", max_age)

    def filings(self, ticker: str, since: date, until: date, forms: tuple[str, ...] = ("10-Q", "10-K")) -> list[Filing]:
        cik = self.cik(ticker)
        return filings_between(self.submissions(cik), cik, ticker, since, until, forms)


def filings_between(
    submissions: dict, cik: str, ticker: str, since: date, until: date, forms: tuple[str, ...]
) -> list[Filing]:
    recent = submissions["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        filed = date.fromisoformat(recent["filingDate"][i])
        if not since <= filed <= until:
            continue
        report = recent["reportDate"][i]
        out.append(
            Filing(
                cik=cik,
                ticker=ticker.upper(),
                form=form,
                accession=recent["accessionNumber"][i],
                filed=filed,
                report_date=date.fromisoformat(report) if report else None,
            )
        )
    return out
