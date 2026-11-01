from datetime import date

from freshfin.edgar import Filing
from freshfin.questions import (
    Question,
    filing_facts,
    prior_year_value,
    questions_for_filing,
    read_questions,
    write_questions,
)
from helpers import MSFT_CIK, msft_facts, msft_q1_filing


def test_filing_facts_are_the_current_quarter():
    facts = {f.metric: f for f in filing_facts(msft_facts(), msft_q1_filing())}
    assert facts["revenue"].value == 92_279_000_000
    assert facts["revenue"].start == date(2026, 7, 1)
    assert facts["total_assets"].start is None
    assert facts["total_assets"].end == date(2026, 9, 30)
    # cash flow is only reported year-to-date in a Q1 10-Q, which is also three months
    assert facts["operating_cash_flow"].value == 58_000_000_000


def test_prior_year_value_uses_same_period_length():
    revenue = next(f for f in filing_facts(msft_facts(), msft_q1_filing()) if f.metric == "revenue")
    prior = prior_year_value(msft_facts(), revenue)
    assert prior is not None
    assert round((revenue.value - prior) / prior * 100, 1) == 18.8


def test_questions_for_filing():
    qs = questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft", per_filing=6)
    assert len(qs) == 6
    assert len({q.id for q in qs}) == 6
    first = qs[0]
    assert first.question == (
        "What was Microsoft's revenue for the three months ended September 30, 2026, "
        "as reported in its 10-Q filed on October 28, 2026?"
    )
    assert first.answer == 92_279_000_000 and first.unit == "USD"
    growth = [q for q in qs if q.kind == "growth"]
    assert len(growth) == 1 and growth[0].unit == "percent" and growth[0].answer == 18.8
    assets = next(q for q in qs if q.metric == "total_assets")
    assert "were Microsoft's total assets as of September 30, 2026" in assets.question


def test_per_filing_limit():
    assert len(questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft", per_filing=3)) == 3


def test_filing_without_facts_gives_no_questions():
    unknown = Filing(MSFT_CIK, "MSFT", "10-Q", "0000000000-26-000000", date(2026, 10, 30), date(2026, 9, 30))
    assert questions_for_filing(msft_facts(), unknown, "Microsoft") == []


def test_round_trip(tmp_path):
    qs = questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft")
    path = tmp_path / "q.jsonl"
    write_questions(path, qs)
    back = read_questions(path)
    assert back == qs
    assert isinstance(back[0], Question) and back[0].filed == date(2026, 10, 28)
