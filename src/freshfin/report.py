"""Summaries, a Markdown leaderboard and a static HTML page for GitHub Pages."""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import ModelSpec
from .questions import Question, read_questions
from .runner import MODES, Record, read_records, records_path
from .scoring import grade


@dataclass
class Row:
    model: str
    label: str
    mode: str
    questions: int
    correct: float
    abstained: float
    hallucinated: float
    estimated: float
    placeholder: float
    invalid: float
    errors: int
    precision: float | None  # correct / answers given: how often a number it states is right
    cost_usd: float
    p50_s: float
    p95_s: float


def _pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def _quantile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(int(q * len(s)), len(s) - 1)] / 1000, 1)


def summarize(records: list[Record], spec: ModelSpec, mode: str) -> Row | None:
    graded = [r for r in records if r.outcome != "error"]
    if not graded:
        return None
    n = len(graded)
    outcomes = ("correct", "abstained", "hallucinated", "estimated", "placeholder", "invalid")
    count = {o: sum(r.outcome == o for r in graded) for o in outcomes}
    answered = count["correct"] + count["hallucinated"] + count["estimated"] + count["placeholder"]
    return Row(
        model=spec.name,
        label=spec.label,
        mode=mode,
        questions=n,
        correct=_pct(count["correct"], n),
        abstained=_pct(count["abstained"], n),
        hallucinated=_pct(count["hallucinated"], n),
        estimated=_pct(count["estimated"], n),
        placeholder=_pct(count["placeholder"], n),
        invalid=_pct(count["invalid"], n),
        errors=len(records) - n,
        precision=_pct(count["correct"], answered) if answered else None,
        cost_usd=round(sum(r.cost_usd for r in records), 4),
        p50_s=_quantile([r.latency_ms for r in graded], 0.5),
        p95_s=_quantile([r.latency_ms for r in graded], 0.95),
    )


def regrade(records: list[Record], questions: dict[str, Question]) -> list[Record]:
    """Grade saved answers again with the current scoring rules, so rule changes don't need new API calls."""
    for r in records:
        q = questions.get(r.question_id)
        if q is not None and r.outcome != "error":
            r.outcome, r.value, r.rescaled = grade(q, r.answer_text)
    return records


def collect(
    run_dir: Path, models: dict[str, ModelSpec], questions: dict[str, Question]
) -> tuple[list[Row], dict[tuple[str, str], list[Record]]]:
    rows, by_key = [], {}
    for spec in models.values():
        for mode in MODES:
            records = regrade(read_records(records_path(run_dir, spec.name, mode)), questions)
            row = summarize(records, spec, mode)
            if row:
                rows.append(row)
                by_key[(spec.name, mode)] = records
    return rows, by_key


def hallucination_examples(by_key, questions: dict[str, Question], labels: dict[str, str], per_model: int = 3):
    """A few no-tools wrong answers from each model, so every model shows up."""
    out = []
    for (model, mode), records in sorted(by_key.items()):
        if mode == "tool":
            continue
        picked = [r for r in records if r.outcome in ("hallucinated", "estimated") and r.question_id in questions]
        picked.sort(key=lambda r: r.question_id)
        for r in picked[:per_model]:
            q = questions[r.question_id]
            out.append(
                {
                    "model": labels[model],
                    "mode": mode,
                    "kind": "made up" if r.outcome == "hallucinated" else "labeled guess",
                    "question": q.question,
                    "said": r.value,
                    "actual": q.answer,
                    "unit": q.unit,
                    "source": q.url,
                }
            )
    return out


def fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "percent":
        return f"{value:.2f}%"
    if unit == "USD/shares":
        return f"${value:.2f}"
    if abs(value) >= 1e9:
        return f"${value / 1e9:,.2f}B"
    if abs(value) >= 1e6:
        return f"${value / 1e6:,.1f}M"
    return f"${value:,.0f}"


MODE_LABELS = {
    "closed": 'no tools, "don\'t know" OK',
    "plain": "no tools, plain question",
    "tool": "lookup tool",
}
MODE_ORDER = {"closed": 0, "plain": 1, "tool": 2}


def _sort(rows: list[Row]) -> list[Row]:
    return sorted(rows, key=lambda r: (MODE_ORDER.get(r.mode, 9), r.hallucinated, r.label))


def to_markdown(rows: list[Row], meta: dict, examples: list[dict]) -> str:
    lines = [
        f"# FreshFin results: filings from {meta['since']} to {meta['until']}",
        "",
        f"{meta['questions']} questions from {len(meta['filings'])} filings. Every answer is the filing's own XBRL value.",
        "",
        '| Model | Mode | Correct | Said "don\'t know" | Made up a number | Labeled guess | Filled in 0 | Unreadable | Right when it answered | Cost | p95 |',
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in _sort(rows):
        mode = MODE_LABELS.get(r.mode, r.mode)
        precision = f"{r.precision:.0f}%" if r.precision is not None else "–"
        lines.append(
            f"| {r.label} | {mode} | {r.correct:.0f}% | {r.abstained:.0f}% | **{r.hallucinated:.0f}%** | "
            f"{r.estimated:.0f}% | {r.placeholder:.0f}% | {r.invalid:.0f}% | {precision} | ${r.cost_usd:.2f} | {r.p95_s:.1f} s |"
        )
    if examples:
        lines += [
            "",
            "## Wrong numbers without tools",
            "",
            "| Model | Type | Question | Said | Filing says |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in examples:
            lines.append(
                f"| {e['model']} | {e['kind']} | {e['question']} | {fmt_value(e['said'], e['unit'])} | "
                f"[{fmt_value(e['actual'], e['unit'])}]({e['source']}) |"
            )
    return "\n".join(lines) + "\n"


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FreshFin</title>
<style>
:root {{ --bg:#f6f5f1; --fg:#141a26; --muted:#4a5568; --line:#dedad0; --accent:#b04d14; --card:#fff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141a26; --fg:#f5f3ee; --muted:#b8c2d3; --line:#2b3447; --accent:#f08a3c; --card:#1e2738; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 -apple-system, system-ui, "Segoe UI", sans-serif }}
main {{ max-width:1160px; margin:0 auto; padding:48px 16px }}
h1 {{ font-size:36px; line-height:1.15; margin:0 0 8px }}
h2 {{ font-size:22px; margin:40px 0 12px }}
p {{ color:var(--muted); margin:0 0 12px }}
.wrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px }}
table {{ border-collapse:collapse; width:100%; font-size:13px }}
th, td {{ text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top }}
td.mode, td.model {{ white-space:nowrap }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:12px; margin:24px 0 8px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px }}
.card h3 {{ font-size:15px; margin:0 0 10px }}
.stat {{ display:flex; justify-content:space-between; gap:12px; font-size:14px; padding:4px 0; color:var(--muted) }}
.stat b {{ color:var(--fg); font-variant-numeric:tabular-nums }}
.stat b.bad {{ color:var(--accent) }}
th {{ color:var(--muted); font-weight:600 }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums }}
td.num {{ white-space:nowrap }}
th {{ vertical-align:bottom }}
.bad {{ color:var(--accent); font-weight:700 }}
a {{ color:inherit }}
footer {{ margin-top:40px; font-size:14px; color:var(--muted) }}
</style>
</head>
<body>
<main>
<h1>How often do AI models make up financial numbers?</h1>
<p>{intro}</p>
<div class="cards">{cards}</div>
<h2>Results</h2>
<div class="wrap"><table>
<tr><th>Model</th><th>Mode</th><th class="num">Correct</th><th class="num">Don't know</th><th class="num">Made up</th><th class="num">Labeled guess</th><th class="num">Filled in 0</th><th class="num">Right when answered</th><th class="num">Cost</th><th class="num">p95</th></tr>
{rows}
</table></div>
{examples}
<footer>Questions and answers are generated from SEC EDGAR XBRL data. Source and method: <a href="https://github.com/satya764/freshfin">github.com/satya764/freshfin</a>. Updated {updated}.</footer>
</main>
</body>
</html>
"""


def _wrong(row: Row | None) -> float | None:
    """Share of answers that put a wrong number on the record: made up, labeled guess or a placeholder 0."""
    return None if row is None else round(row.hallucinated + row.estimated + row.placeholder, 1)


def cards_html(rows: list[Row]) -> str:
    e = html.escape
    by_model: dict[str, dict[str, Row]] = {}
    for r in rows:
        by_model.setdefault(r.label, {})[r.mode] = r
    out = []
    for label, modes in by_model.items():
        stats = []
        for mode, name in (
            ("closed", 'Wrong numbers, "don\'t know" allowed'),
            ("plain", "Wrong numbers, plain question"),
        ):
            w = _wrong(modes.get(mode))
            if w is not None:
                cls = ' class="bad"' if w > 0 else ""
                stats.append(f"<div class=stat><span>{e(name)}</span><b{cls}>{w:.0f}%</b></div>")
        if "tool" in modes:
            stats.append(
                f"<div class=stat><span>Correct with lookup tool</span><b>{modes['tool'].correct:.0f}%</b></div>"
            )
        out.append(f"<div class=card><h3>{e(label)}</h3>{''.join(stats)}</div>")
    return "".join(out)


def to_html(rows: list[Row], meta: dict, examples: list[dict], updated: str) -> str:
    e = html.escape
    intro = (
        f"Every question comes from a 10-Q or 10-K filed between {meta['since']} and {meta['until']}. "
        "A model is only asked about filings published after its training data ends, so it can't know the "
        f"answers. {meta['questions']} questions from {len(meta['filings'])} filings. Each model answers three ways: "
        'with no tools and told that "I don\'t know" is fine; with no tools and a plain question, the way most '
        "people ask; and with a tool that looks up the SEC's data."
    )
    body = []
    for r in _sort(rows):
        mode = e(MODE_LABELS.get(r.mode, r.mode))
        precision = f"{r.precision:.0f}%" if r.precision is not None else "–"
        body.append(
            f"<tr><td class=model>{e(r.label)}</td><td class=mode>{mode}</td><td class=num>{r.correct:.0f}%</td>"
            f'<td class=num>{r.abstained:.0f}%</td><td class="num bad">{r.hallucinated:.0f}%</td>'
            f"<td class=num>{r.estimated:.0f}%</td><td class=num>{r.placeholder:.0f}%</td>"
            f"<td class=num>{precision}</td><td class=num>${r.cost_usd:.2f}</td><td class=num>{r.p95_s:.1f} s</td></tr>"
        )
    ex = ""
    if examples:
        items = "".join(
            f'<tr><td>{e(x["model"])}</td><td>{e(x["kind"])}</td><td>{e(x["question"])}</td><td class="num bad">{e(fmt_value(x["said"], x["unit"]))}</td>'
            f'<td class=num><a href="{e(x["source"])}">{e(fmt_value(x["actual"], x["unit"]))}</a></td></tr>'
            for x in examples
        )
        ex = (
            "<h2>Wrong numbers without tools</h2><p>Answers given with no tools, where the model gave a number "
            "instead of saying it didn't know. A labeled guess is one the model said was an estimate.</p>"
            '<div class="wrap"><table><tr><th>Model</th><th>Type</th><th>Question</th>'
            f"<th class=num>Said</th><th class=num>Filing says</th></tr>{items}</table></div>"
        )
    return PAGE.format(intro=e(intro), cards=cards_html(rows), rows="\n".join(body), examples=ex, updated=e(updated))


def write_report(run_dir: Path, models: dict[str, ModelSpec], pages_dir: Path | None, updated: str) -> list[Row]:
    meta = json.loads((run_dir / "meta.json").read_text())
    questions = {q.id: q for q in read_questions(run_dir / "questions.jsonl")}
    rows, by_key = collect(run_dir, models, questions)
    labels = {s.name: s.label for s in models.values()}
    examples = hallucination_examples(by_key, questions, labels)
    (run_dir / "summary.json").write_text(
        json.dumps({"meta": meta, "rows": [asdict(r) for r in rows], "examples": examples}, indent=2) + "\n"
    )
    (run_dir / "leaderboard.md").write_text(to_markdown(rows, meta, examples))
    if pages_dir is not None:
        pages_dir.mkdir(parents=True, exist_ok=True)
        (pages_dir / "index.html").write_text(to_html(rows, meta, examples, updated))
    return rows
