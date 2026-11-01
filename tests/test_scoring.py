from datetime import date

from freshfin.questions import Question
from freshfin.scoring import grade, parse_answer


def q(answer: float, unit: str = "USD") -> Question:
    return Question(
        "id",
        "lookup",
        "MSFT",
        "Microsoft",
        "10-Q",
        "a",
        date(2026, 10, 28),
        "u",
        "revenue",
        "Revenues",
        date(2026, 7, 1),
        date(2026, 9, 30),
        "?",
        answer,
        unit,
    )


def test_exact_json():
    assert grade(q(92_279_000_000), '{"value": 92279000000, "unit": "USD"}') == ("correct", 92_279_000_000, False)


def test_null_is_abstain():
    assert grade(q(1e9), '{"value": null, "unit": "USD"}')[0] == "abstained"
    assert grade(q(1e9), '{"value": "null"}')[0] == "abstained"


def test_wrong_number_is_hallucination():
    outcome, value, _ = grade(q(92_279_000_000), '{"value": 77700000000, "unit": "USD"}')
    assert outcome == "hallucinated" and value == 77_700_000_000


def test_tolerance():
    assert grade(q(1_000_000_000), '{"value": 1004000000}')[0] == "correct"
    assert grade(q(1_000_000_000), '{"value": 1010000000}')[0] == "hallucinated"


def test_wrong_scale_counts_but_is_flagged():
    assert grade(q(92_279_000_000), '{"value": 92279, "unit": "USD"}') == ("correct", 92279, True)
    assert grade(q(92_279_000_000), '{"value": 92.279}') == ("correct", 92.279, True)


def test_percent_and_fraction():
    assert grade(q(18.8, "percent"), '{"value": 18.85, "unit": "percent"}')[0] == "correct"
    assert grade(q(18.8, "percent"), '{"value": 0.188}') == ("correct", 0.188, True)
    assert grade(q(18.8, "percent"), '{"value": 17.5}')[0] == "hallucinated"


def test_eps():
    assert grade(q(4.92, "USD/shares"), '{"value": 4.92}')[0] == "correct"
    assert grade(q(4.92, "USD/shares"), '{"value": 4.95}')[0] == "hallucinated"


def test_text_around_json_and_strings():
    text = 'Revenue was about $92.3B.\n{"value": "92,279,000,000", "unit": "USD"}'
    assert grade(q(92_279_000_000), text)[0] == "correct"


def test_thinking_tags_are_ignored():
    assert grade(q(5.0, "USD/shares"), '<think>{"value": 1}</think>{"value": 5.0}')[0] == "correct"


def test_plain_text_refusal():
    assert parse_answer("I don't know the figures from that filing.").abstained


def test_unreadable():
    assert grade(q(1e9), "Revenue grew strongly.")[0] == "invalid"


def test_labeled_estimate_is_not_counted_as_made_up():
    text = 'I can\'t see the 10-Q, so this is an estimate based on guidance.\n{"value": 13.5, "unit": "percent"}'
    assert grade(q(11.85, "percent"), text)[0] == "estimated"


def test_right_number_labeled_estimate_still_correct():
    assert grade(q(11.85, "percent"), 'An estimate: {"value": 11.9}')[0] == "correct"
