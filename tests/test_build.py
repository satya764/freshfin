from datetime import date

from freshfin.build import build, save_build
from freshfin.edgar import filings_between
from helpers import MSFT_CIK, msft_facts, msft_submissions


class FakeEdgar:
    def filings(self, ticker, since, until, forms=("10-Q", "10-K")):
        if ticker == "BAD":
            raise LookupError("Unknown ticker BAD")
        return filings_between(msft_submissions(), MSFT_CIK, ticker, since, until, forms)

    def company_facts(self, cik, max_age=0):
        return msft_facts()


def test_build_window_and_bad_ticker(tmp_path):
    result = build(FakeEdgar(), ["MSFT", "BAD"], date(2026, 7, 1), date(2026, 10, 31))
    forms = sorted((f["form"], f["filed"]) for f in result.filings)
    assert forms == [("10-K", "2026-07-29"), ("10-Q", "2026-10-28")]
    assert len(result.questions) == 12
    assert result.skipped == ["BAD: Unknown ticker BAD"]
    save_build(tmp_path, result, date(2026, 7, 1), date(2026, 10, 31), ["MSFT", "BAD"])
    assert (tmp_path / "questions.jsonl").read_text().count("\n") == 12
    assert '"questions": 12' in (tmp_path / "meta.json").read_text()


def test_filings_between_filters_forms_and_dates():
    found = filings_between(msft_submissions(), MSFT_CIK, "msft", date(2026, 10, 1), date(2026, 10, 31), ("10-K",))
    assert found == []
    q = filings_between(msft_submissions(), MSFT_CIK, "msft", date(2026, 10, 1), date(2026, 10, 31), ("10-Q",))[0]
    assert q.ticker == "MSFT" and q.url.endswith("/000119312526436133/")
