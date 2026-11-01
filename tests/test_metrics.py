from datetime import date

from freshfin.metrics import METRICS, describe_period, fmt_date, months_between


def test_months_between_normal_periods():
    assert months_between(date(2026, 7, 1), date(2026, 9, 30)) == 3
    assert months_between(date(2026, 1, 1), date(2026, 6, 30)) == 6
    assert months_between(date(2025, 10, 1), date(2026, 6, 30)) == 9
    assert months_between(date(2025, 7, 1), date(2026, 6, 30)) == 12


def test_months_between_rejects_odd_periods():
    assert months_between(date(2026, 1, 1), date(2026, 2, 15)) is None


def test_describe_period():
    assert describe_period(date(2026, 7, 1), date(2026, 9, 30)) == "for the three months ended September 30, 2026"
    assert describe_period(date(2025, 7, 1), date(2026, 6, 30)) == "for the fiscal year ended June 30, 2026"
    assert describe_period(None, date(2026, 9, 30)) == "as of September 30, 2026"


def test_fmt_date_has_no_leading_zero():
    assert fmt_date(date(2026, 7, 5)) == "July 5, 2026"


def test_every_metric_has_concepts():
    for metric in METRICS.values():
        assert metric.concepts
        assert metric.verb in ("was", "were")
