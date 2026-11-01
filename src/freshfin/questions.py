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

QuestionKind = Literal["lookup", "growth"]


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


def filing_facts(company_facts: dict, filing: Filing) -> list[Fact]:
    """Facts first reported in this filing: tagged with its accession and ending on its current period.

    For each metric only the first concept with data is used, and for duration metrics the
    shortest period (the quarter, not year-to-date), since that is what headlines report.
    """
    end = current_period_end(company_facts, filing)
    if end is None:
        return []
    out = []
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
            out.append(max(found.values(), key=lambda f: f.start or date.min))  # latest start = shortest period
    return out


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
    return f"What {metric.verb} {company}'s {metric.label} {period}, {source}?"


def questions_for_filing(company_facts: dict, filing: Filing, company: str, per_filing: int = 6) -> list[Question]:
    facts = filing_facts(company_facts, filing)
    picked: list[tuple[QuestionKind, Fact, float, str]] = []
    for fact in facts:
        picked.append(("lookup", fact, fact.value, fact.unit))
    growth = []
    for fact in facts:
        if fact.metric in GROWTH_METRICS:
            prior = prior_year_value(company_facts, fact)
            if prior:
                growth.append(("growth", fact, round((fact.value - prior) / abs(prior) * 100, 2), "percent"))
    # Keep one growth question in the mix when there's room, then fill with lookups in metric order.
    lookups = picked[: max(per_filing - min(len(growth), 1), 0)]
    chosen = lookups + growth[: per_filing - len(lookups)]

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
