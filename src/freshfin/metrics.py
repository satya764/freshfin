"""Which XBRL facts become questions, and how their periods are described in plain words."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Kind = Literal["duration", "instant"]


@dataclass(frozen=True)
class Metric:
    key: str
    label: str  # "revenue", "total assets"
    verb: str  # "was" or "were", so questions read naturally
    concepts: tuple[str, ...]  # tried in order; companies use different tags
    unit: str = "USD"
    kind: Kind = "duration"


# Order matters: questions are drawn from the top of this list first.
METRICS: dict[str, Metric] = {
    m.key: m
    for m in [
        Metric(
            "revenue",
            "revenue",
            "was",
            (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
            ),
        ),
        Metric("net_income", "net income", "was", ("NetIncomeLoss", "ProfitLoss")),
        Metric(
            "eps_diluted",
            "diluted earnings per share",
            "were",
            ("EarningsPerShareDiluted",),
            unit="USD/shares",
        ),
        Metric("operating_income", "operating income", "was", ("OperatingIncomeLoss",)),
        Metric("total_assets", "total assets", "were", ("Assets",), kind="instant"),
        Metric(
            "cash",
            "cash and cash equivalents",
            "were",
            ("CashAndCashEquivalentsAtCarryingValue",),
            kind="instant",
        ),
        Metric(
            "operating_cash_flow",
            "net cash provided by operating activities",
            "was",
            ("NetCashProvidedByUsedInOperatingActivities",),
        ),
        Metric(
            "research_and_development",
            "research and development expense",
            "was",
            ("ResearchAndDevelopmentExpense",),
        ),
        Metric("gross_profit", "gross profit", "was", ("GrossProfit",)),
        Metric(
            "capital_expenditures",
            "spending on property, plant and equipment",
            "was",
            ("PaymentsToAcquirePropertyPlantAndEquipment",),
        ),
        Metric(
            "stockholders_equity",
            "total stockholders' equity",
            "was",
            ("StockholdersEquity",),
            kind="instant",
        ),
    ]
}

# Growth questions (current period vs the same period a year earlier) for these metrics.
GROWTH_METRICS = ("revenue", "net_income")

MONTH_WORDS = {3: "three", 6: "six", 9: "nine", 12: "twelve"}


def months_between(start: date, end: date) -> int | None:
    """Length of a reporting period in months, or None if it isn't a normal quarter/half/9-month/year."""
    days = (end - start).days
    for months, (lo, hi) in {3: (80, 100), 6: (170, 190), 9: (260, 285), 12: (350, 380)}.items():
        if lo <= days <= hi:
            return months
    return None


def fmt_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def describe_period(start: date | None, end: date) -> str:
    if start is None:
        return f"as of {fmt_date(end)}"
    months = months_between(start, end)
    if months == 12:
        return f"for the fiscal year ended {fmt_date(end)}"
    return f"for the {MONTH_WORDS.get(months or 0, str(months))} months ended {fmt_date(end)}"
