"""Turn new filings into questions with exact answers taken from the filing's own XBRL facts.

Only facts for the filing's current period are used: those numbers did not exist anywhere
before the filing was published, so a model can't have seen them in training.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from .edgar import Filing
from .metrics import GROWTH_METRICS, METRICS, Metric, describe_period, fmt_date, months_between

QuestionKind = Literal["lookup", "growth", "margin"]


@dataclass(frozen=True)
class Question:
    id: str
    kind: QuestionKind
    ticker: str
    company: str
    form: str
    accession: str
    filed: date
    url: str
    metric: str
    concept: str
    period_start: date | None
    period_end: date
    question: str
    answer: float
    unit: str  # USD, USD/shares, percent

    def to_json(self) -> str:
        data = asdict(self)
        for key in ("filed", "period_start", "period_end"):
            data[key] = data[key].isoformat() if data[key] else None
        return json.dumps(data)

    @classmethod
    def from_json(cls, line: str) -> Question:
        data = json.loads(line)
        for key in ("filed", "period_start", "period_end"):
            data[key] = date.fromisoformat(data[key]) if data[key] else None
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class Fact:
    metric: str
    concept: str
    value: float
    unit: str
    start: date | None
    end: date
    accession: str


def _entries(company_facts: dict, metric: Metric):
    """Yield (concept, entry) for the metric's concepts, in priority order."""
    gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for concept in metric.concepts:
        for entry in gaap.get(concept, {}).get("units", {}).get(metric.unit, []):
            yield concept, entry


def _to_fact(metric: Metric, concept: str, entry: dict) -> Fact | None:
    start = date.fromisoformat(entry["start"]) if entry.get("start") else None
    end = date.fromisoformat(entry["end"])
    if metric.kind == "instant" and start is not None:
        return None
    if metric.kind == "duration" and (start is None or months_between(start, end) is None):
        return None
    return Fact(metric.key, concept, float(entry["val"]), metric.unit, start, end, entry["accn"])


def current_period_end(company_facts: dict, filing: Filing) -> date | None:
    """The balance-sheet date the filing reports on: its report date, or the latest period end tagged in it."""
    ends = set()
    for metric in METRICS.values():
        for _, entry in _entries(company_facts, metric):
            if entry.get("accn") == filing.accession:
                ends.add(date.fromisoformat(entry["end"]))
    if not ends:
        return None
    if filing.report_date in ends:
        return filing.report_date
    return max(ends)


def period_facts(company_facts: dict, filing: Filing) -> dict[str, list[Fact]]:
    """Every fact first reported in this filing, by metric: tagged with its accession and ending on its
    current period. A 10-Q can tag the same metric for the quarter and for year-to-date; both are kept,
    shortest period first. For each metric only the first concept with data is used."""
    end = current_period_end(company_facts, filing)
    if end is None:
        return {}
    out: dict[str, list[Fact]] = {}
    for metric in METRICS.values():
        found: dict[date | None, Fact] = {}
        for concept, entry in _entries(company_facts, metric):
            if found and next(iter(found.values())).concept != concept:
                break  # a higher-priority concept already had data
            if entry.get("accn") != filing.accession or entry["end"] != end.isoformat():
                continue
            fact = _to_fact(metric, concept, entry)
            if fact is not None:
                found.setdefault(fact.start, fact)
        if found:
            out[metric.key] = sorted(found.values(), key=lambda f: f.start or date.min, reverse=True)
    return out


def filing_facts(company_facts: dict, filing: Filing) -> list[Fact]:
    """One fact per metric: the shortest period (the quarter, not year-to-date), since that is what
    headlines report."""
    return [facts[0] for facts in period_facts(company_facts, filing).values()]


def prior_year_value(company_facts: dict, fact: Fact) -> float | None:
    """The same metric, concept and period length, one year earlier. Prefers the comparative in the same filing."""
    if fact.start is None:
        return None
    metric = METRICS[fact.metric]
    months = months_between(fact.start, fact.end)
    target = fact.end - timedelta(days=365)
    best: tuple[int, float] | None = None
    for concept, entry in _entries(company_facts, metric):
        if concept != fact.concept:
            continue
        prior = _to_fact(metric, concept, entry)
        if prior is None or prior.start is None or months_between(prior.start, prior.end) != months:
            continue
        if abs((prior.end - target).days) > 10:
            continue
        rank = 0 if prior.accession == fact.accession else 1
        if best is None or rank < best[0]:
            best = (rank, prior.value)
    return best[1] if best else None


def _question_text(company: str, metric: Metric, fact: Fact, filing: Filing, kind: QuestionKind) -> str:
    period = describe_period(fact.start, fact.end)
    source = f"as reported in its {filing.form} filed on {fmt_date(filing.filed)}"
    if kind == "growth":
        return (
            f"By what percent did {company}'s {metric.label} {period} change compared with the same "
            f"period a year earlier, {source}?"
        )
    if kind == "margin":
        return f"What was {company}'s operating margin (operating income as a percent of revenue) {period}, {source}?"
    return f"What {metric.verb} {company}'s {metric.label} {period}, {source}?"


def questions_for_filing(company_facts: dict, filing: Filing, company: str, per_filing: int = 8) -> list[Question]:
    """Lookups of the newest reported values, plus up to three harder questions:
    year-over-year growth, a year-to-date value (easy to confuse with the quarter), and operating margin."""
    by_metric = period_facts(company_facts, filing)
    facts = [f[0] for f in by_metric.values()]
    picked: list[tuple[QuestionKind, Fact, float, str]] = [("lookup", f, f.value, f.unit) for f in facts]

    growth = []
    for fact in facts:
        if fact.metric in GROWTH_METRICS:
            prior = prior_year_value(company_facts, fact)
            if prior:
                growth.append(("growth", fact, round((fact.value - prior) / abs(prior) * 100, 2), "percent"))

    ytd = [
        ("lookup", f[-1], f[-1].value, f[-1].unit)
        for m in ("revenue", "net_income")
        if len(f := by_metric.get(m, [])) > 1
    ]

    margin = []
    revenue, operating = by_metric.get("revenue", [None])[0], by_metric.get("operating_income", [None])[0]
    if revenue and operating and revenue.start == operating.start and revenue.value:
        margin.append(("margin", operating, round(operating.value / revenue.value * 100, 2), "percent"))

    # The harder questions first get a slot each; lookups fill the rest in metric order.
    extras = growth[:1] + ytd[:1] + margin[:1]
    lookups = picked[: max(per_filing - len(extras), 0)]
    chosen = lookups + extras[: per_filing - len(lookups)]

    out = []
    for kind, fact, answer, unit in chosen:
        metric = METRICS[fact.metric]
        months = months_between(fact.start, fact.end) if fact.start else 0
        out.append(
            Question(
                id=f"{filing.ticker}-{fact.end.isoformat()}-{fact.metric}-{months}m-{kind}",
                kind=kind,
                ticker=filing.ticker,
                company=company,
                form=filing.form,
                accession=filing.accession,
                filed=filing.filed,
                url=filing.url,
                metric=fact.metric,
                concept=fact.concept,
                period_start=fact.start,
                period_end=fact.end,
                question=_question_text(company, metric, fact, filing, kind),
                answer=answer,
                unit=unit,
            )
        )
    return out


def write_questions(path: Path, questions: list[Question]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(q.to_json() + "\n" for q in questions))


def read_questions(path: Path) -> list[Question]:
    return [Question.from_json(line) for line in path.read_text().splitlines() if line.strip()]
