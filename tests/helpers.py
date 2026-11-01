import json
from datetime import date
from pathlib import Path

from freshfin.edgar import Filing, filings_between

FIXTURES = Path(__file__).parent / "fixtures"
MSFT_CIK = "0000789019"


def msft_facts() -> dict:
    return json.loads((FIXTURES / "msft_facts.json").read_text())


def msft_submissions() -> dict:
    return json.loads((FIXTURES / "msft_submissions.json").read_text())


def msft_q1_filing() -> Filing:
    """Microsoft's 10-Q for the quarter ended Sept 30, 2026, filed Oct 28, 2026."""
    found = filings_between(msft_submissions(), MSFT_CIK, "MSFT", date(2026, 10, 1), date(2026, 10, 31), ("10-Q",))
    assert len(found) == 1
    return found[0]
