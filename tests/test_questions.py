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
    qs = questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft")
    assert len(qs) == 8
    assert len({q.id for q in qs}) == 8
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


def test_operating_margin_question():
    qs = questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft")
    margin = next(q for q in qs if q.kind == "margin")
    assert margin.answer == round(45_915_000_000 / 92_279_000_000 * 100, 2)
    assert "operating margin (operating income as a percent of revenue)" in margin.question


def test_year_to_date_question_when_the_filing_has_one():
    facts = msft_facts()
    filing = msft_q1_filing()
    # Add a nine-month revenue fact to the same filing, as a Q3 10-Q would have.
    entries = facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    entries.append(
        {
            "start": "2026-01-01",
            "end": "2026-09-30",
            "val": 250_000_000_000,
            "accn": filing.accession,
            "form": "10-Q",
            "filed": "2026-10-28",
        }
    )
    ytd = [q for q in questions_for_filing(facts, filing, "Microsoft") if q.id.endswith("-9m-lookup")]
    assert len(ytd) == 1 and ytd[0].answer == 250_000_000_000
    assert "nine months ended September 30, 2026" in ytd[0].question


def test_earlier_question_ids_stay_the_same():
    """Growing the question set must keep old ids, so finished runs resume instead of starting over."""
    six = {q.id for q in questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft", per_filing=6)}
    eight = {q.id for q in questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft", per_filing=8)}
    assert six <= eight


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
