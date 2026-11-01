"""Build a benchmark run: find filings in a date window and write their questions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .edgar import Edgar
from .questions import Question, questions_for_filing, write_questions
from .universe import display_name

log = logging.getLogger(__name__)


@dataclass
class BuildResult:
    questions: list[Question]
    filings: list[dict]
    skipped: list[str]


def build(edgar: Edgar, tickers: list[str], since: date, until: date, per_filing: int = 6) -> BuildResult:
    questions: list[Question] = []
    filings: list[dict] = []
    skipped: list[str] = []
    for ticker in tickers:
        try:
            found = edgar.filings(ticker, since, until)
        except Exception as err:  # one bad ticker shouldn't stop the run
            log.warning("%s: %s", ticker, err)
            skipped.append(f"{ticker}: {err}")
            continue
        if not found:
            continue
        facts = edgar.company_facts(found[0].cik)
        for filing in found:
            qs = questions_for_filing(facts, filing, display_name(ticker), per_filing)
            if not qs:
                # XBRL facts can lag the filing by a day; tomorrow's run picks it up.
                skipped.append(f"{ticker} {filing.form} {filing.filed}: no XBRL facts yet")
                continue
            questions.extend(qs)
            filings.append(
                {
                    "ticker": filing.ticker,
                    "form": filing.form,
                    "filed": filing.filed.isoformat(),
                    "accession": filing.accession,
                    "url": filing.url,
                    "questions": len(qs),
                }
            )
        log.info("%s: %d filings", ticker, len(found))
    return BuildResult(questions, filings, skipped)


def save_build(run_dir: Path, result: BuildResult, since: date, until: date, tickers: list[str]) -> None:
    write_questions(run_dir / "questions.jsonl", result.questions)
    meta = {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "tickers": tickers,
        "filings": result.filings,
        "skipped": result.skipped,
        "questions": len(result.questions),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
