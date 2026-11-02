"""Summaries, a Markdown leaderboard and a static HTML page for GitHub Pages."""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import ModelSpec
from .questions import Question, read_questions
from .runner import MODES, Record, read_records, records_path
from .scoring import grade, parse_answer


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
    prose: float = 0.0  # answers written as a sentence instead of the requested JSON
    text_calls: float = 0.0  # questions where the model typed a tool call as text instead of calling it


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
        prose=_pct(sum(parse_answer(r.answer_text).prose for r in graded), n),
        text_calls=_pct(sum(any(c.get("from_text") for c in r.tool_calls) for r in graded), n),
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


QUESTION_TYPES = ("latest value", "year-to-date", "growth", "margin")


def question_type(q: Question) -> str:
    if q.kind != "lookup":
        return q.kind
    if q.period_start is not None and (q.period_end - q.period_start).days > 100:
        return "year-to-date"
    return "latest value"


def tool_accuracy_by_type(by_key, questions: dict[str, Question], labels: dict[str, str]) -> list[dict]:
    """Correct answers with the lookup tool, split by question type: where tool use goes wrong."""
    out = []
    for (model, mode), records in sorted(by_key.items()):
        if mode != "tool":
            continue
        row: dict = {"model": labels[model]}
        for t in QUESTION_TYPES:
            graded = [
                r
                for r in records
                if r.outcome != "error" and r.question_id in questions and question_type(questions[r.question_id]) == t
            ]
            row[t] = {"correct": sum(r.outcome == "correct" for r in graded), "total": len(graded)}
        out.append(row)
    return out


def _cell(c: dict) -> str:
    return f"{c['correct']}/{c['total']}" if c["total"] else "–"


def fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "percent":
        return f"{value:.2f}%"
    sign = "−" if value < 0 else ""
    v = abs(value)
    if unit == "USD/shares":
        return f"{sign}${v:.2f}"
    if v >= 1e9:
        return f"{sign}${v / 1e9:,.2f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:,.1f}M"
    return f"{sign}${v:,.0f}"


MODE_LABELS = {
    "closed": 'no tools, "don\'t know" OK',
    "plain": "no tools, plain question",
    "tool": "lookup tool",
}
MODE_ORDER = {"closed": 0, "plain": 1, "tool": 2}


def _sort(rows: list[Row]) -> list[Row]:
    return sorted(rows, key=lambda r: (MODE_ORDER.get(r.mode, 9), r.hallucinated, r.label))


def to_markdown(rows: list[Row], meta: dict, examples: list[dict], by_type: list[dict] | None = None) -> str:
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
    issues = [r for r in _sort(rows) if r.prose or r.text_calls]
    if issues:
        lines += [
            "",
            "## Format problems",
            "",
            "Answers in a sentence are read for a dollar amount or percent; tool calls typed as text are run.",
            "",
            "| Model | Mode | Answered in a sentence | Typed the tool call as text |",
            "| --- | --- | --- | --- |",
        ]
        for r in issues:
            lines.append(f"| {r.label} | {MODE_LABELS.get(r.mode, r.mode)} | {r.prose:.0f}% | {r.text_calls:.0f}% |")
    if by_type:
        lines += [
            "",
            "## With the lookup tool, by question type",
            "",
            "| Model | " + " | ".join(t.capitalize() for t in QUESTION_TYPES) + " |",
            "| --- |" + " --- |" * len(QUESTION_TYPES),
        ]
        for b in by_type:
            lines.append(f"| {b['model']} | " + " | ".join(_cell(b[t]) for t in QUESTION_TYPES) + " |")
    if examples:
        lines += [
            "",
            "## Examples: what the model said vs. what the filing says",
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
<meta name="description" content="How often AI models make up numbers about earnings reports filed after their training cutoff.">
<style>
:root {{
  --bg:#ffffff; --band:#f5f5f7; --tile:#ffffff; --ink:#1d1d1f; --muted:#6e6e73; --line:#d2d2d7;
  --link:#0066cc; --bad:#bf4800; --good:#1d1d1f;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#000000; --band:#161617; --tile:#1d1d1f; --ink:#f5f5f7; --muted:#a1a1a6; --line:#424245;
           --link:#2997ff; --bad:#ff9f0a; --good:#f5f5f7; }}
}}
* {{ box-sizing:border-box }}
html {{ -webkit-text-size-adjust:100% }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:17px/1.47 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif;
  letter-spacing:-0.01em; -webkit-font-smoothing:antialiased }}
a {{ color:var(--link); text-decoration:none }}
a:hover {{ text-decoration:underline }}
a:focus-visible {{ outline:2px solid var(--link); outline-offset:3px; border-radius:4px }}
.wrap {{ max-width:1024px; margin:0 auto; padding:0 22px }}
header.bar {{ border-bottom:1px solid var(--line) }}
header.bar .wrap {{ display:flex; justify-content:space-between; align-items:center; height:52px; font-size:14px }}
header.bar strong {{ font-weight:600; font-size:17px; color:var(--ink) }}
.hero {{ text-align:center; padding:96px 0 72px }}
.hero h1 {{ font-family:-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size:clamp(40px, 7vw, 76px); line-height:1.05; letter-spacing:-0.025em; font-weight:700; margin:0 auto 20px; max-width:15ch }}
.hero p {{ font-size:clamp(19px, 2.4vw, 24px); line-height:1.35; color:var(--muted); margin:0 auto; max-width:34ch }}
.hero .links {{ margin-top:28px; display:flex; gap:28px; justify-content:center; font-size:19px }}
section.band {{ background:var(--band); padding:88px 0 }}
section.plain {{ padding:88px 0 }}
h2 {{ font-family:-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size:clamp(32px, 4.6vw, 48px); line-height:1.08; letter-spacing:-0.02em; font-weight:700; margin:0 0 14px; text-align:center }}
.lead {{ text-align:center; color:var(--muted); font-size:21px; line-height:1.38; margin:0 auto 48px; max-width:40ch }}
blockquote {{ margin:0 auto 56px; max-width:28ch; text-align:center;
  font-size:clamp(24px, 3.4vw, 34px); line-height:1.2; font-weight:600; letter-spacing:-0.015em }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px }}
.tile {{ background:var(--tile); border-radius:22px; padding:30px 28px 26px }}
.tile h3 {{ margin:0 0 22px; font-size:21px; font-weight:600; letter-spacing:-0.01em }}
.stat {{ display:flex; justify-content:space-between; align-items:baseline; gap:16px; padding:10px 0;
  border-top:1px solid var(--line) }}
.stat span {{ color:var(--muted); font-size:15px; line-height:1.3 }}
.stat b {{ font-size:34px; font-weight:600; letter-spacing:-0.02em; font-variant-numeric:tabular-nums; white-space:nowrap }}
.stat b.bad {{ color:var(--bad) }}
.note {{ text-align:center; color:var(--muted); font-size:14px; margin:28px auto 0; max-width:60ch }}
.table {{ overflow-x:auto; margin:0 0 56px }}
table {{ border-collapse:collapse; width:100%; font-size:14px }}
th, td {{ text-align:left; padding:12px 10px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ color:var(--muted); font-weight:500; vertical-align:bottom }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums }}
td.num {{ white-space:nowrap }}
td.model, td.mode {{ white-space:nowrap }}
td.bad {{ color:var(--bad); font-weight:600 }}
h3.sub {{ font-size:24px; font-weight:600; letter-spacing:-0.015em; margin:0 0 8px }}
p.sub {{ color:var(--muted); margin:0 0 18px; max-width:70ch }}
footer {{ border-top:1px solid var(--line); color:var(--muted); font-size:12px; line-height:1.5; padding:22px 0 40px }}
footer p {{ margin:0 0 6px; max-width:90ch }}
</style>
</head>
<body>
<header class="bar"><div class="wrap"><strong>FreshFin</strong><a href="https://github.com/satya764/freshfin">Source on GitHub</a></div></header>
<main>
<section class="hero"><div class="wrap">
<h1>{headline}</h1>
<p>{subhead}</p>
<div class="links"><a href="#results">See the results</a><a href="#method">How it works</a></div>
</div></section>
<section class="band"><div class="wrap">
<h2>Same questions. One line different.</h2>
<p class="lead">Every model got the same questions twice with no tools: once with this line in the prompt, once without it.</p>
<blockquote>&ldquo;If you do not know the exact reported figure, set value to null.&rdquo;</blockquote>
<div class="tiles">{tiles}</div>
<p class="note">A wrong number is any figure that isn't the filed value: one stated as fact, one labeled as an estimate, or a 0 filled in. Lookup tool: the model can fetch the SEC's data and has to pick the right row.</p>
</div></section>
<section class="plain" id="results"><div class="wrap">
<h2>Every result.</h2>
<p class="lead">{intro}</p>
<div class="table"><table>
<tr><th>Model</th><th>Mode</th><th class="num">Correct</th><th class="num">Don't know</th><th class="num">Made up</th><th class="num">Labeled guess</th><th class="num">Filled in 0</th><th class="num">Right when answered</th><th class="num">Cost</th><th class="num">p95</th></tr>
{rows}
</table></div>
{by_type}
{issues}
{examples}
</div></section>
</main>
<footer id="method"><div class="wrap">
<p>How it works: questions come from 10-Q and 10-K filings published after each model's training data ends. Every answer is the value the company tagged in its own XBRL data, so nothing is labeled by hand. Amounts must be within 0.5%, per-share figures within a cent, percents within 0.15 points.</p>
<p>Source, raw answers and method: <a href="https://github.com/satya764/freshfin">github.com/satya764/freshfin</a>. Data from SEC EDGAR. Updated {updated}.</p>
</div></footer>
</body>
</html>
"""


def _wrong(row: Row | None) -> float | None:
    """Share of answers that put a wrong number on the record: made up, labeled guess or a placeholder 0."""
    return None if row is None else round(row.hallucinated + row.estimated + row.placeholder, 1)


def _by_model(rows: list[Row]) -> dict[str, dict[str, Row]]:
    out: dict[str, dict[str, Row]] = {}
    for r in rows:
        out.setdefault(r.label, {})[r.mode] = r
    return out


def cards_html(rows: list[Row]) -> str:
    """One tile per model: wrong numbers with and without the sentence, and accuracy with the tool."""
    e = html.escape
    out = []
    for label, modes in _by_model(rows).items():
        stats = []
        for mode, name in (("closed", "Wrong numbers, with the sentence"), ("plain", "Wrong numbers, without it")):
            w = _wrong(modes.get(mode))
            if w is not None:
                cls = ' class="bad"' if w > 0 else ""
                stats.append(f"<div class=stat><span>{e(name)}</span><b{cls}>{w:.0f}%</b></div>")
        if "tool" in modes:
            stats.append(
                f"<div class=stat><span>Correct with a lookup tool</span><b>{modes['tool'].correct:.0f}%</b></div>"
            )
        out.append(f"<div class=tile><h3>{e(label)}</h3>{''.join(stats)}</div>")
    return "".join(out)


def headline_text(rows: list[Row]) -> tuple[str, str]:
    """The page's headline, from the model whose wrong-number rate moved most between the two no-tool modes."""
    best = None
    for label, modes in _by_model(rows).items():
        closed, plain = _wrong(modes.get("closed")), _wrong(modes.get("plain"))
        if closed is not None and plain is not None and (best is None or plain - closed > best[0]):
            best = (plain - closed, label, closed, plain)
    if best is None or best[0] < 10:
        return (
            "How often do AI models make up financial numbers?",
            "Questions from earnings reports filed after each model's training data ends.",
        )
    _, label, closed, plain = best
    return (
        "One sentence decides whether AI makes up numbers.",
        f"Without it, {label} put a wrong number on {plain:.0f}% of answers about new earnings reports. "
        f"With it, {closed:.0f}%.",
    )


def to_html(rows: list[Row], meta: dict, examples: list[dict], updated: str, by_type: list[dict] | None = None) -> str:
    e = html.escape
    headline, subhead = headline_text(rows)
    intro = (
        f"{meta['questions']} questions from {len(meta['filings'])} 10-Q and 10-K filings, filed "
        f"{meta['since']} to {meta['until']}. Each model only sees filings published after its training data ends."
    )
    body = []
    for r in _sort(rows):
        precision = f"{r.precision:.0f}%" if r.precision is not None else "–"
        bad = " bad" if r.hallucinated else ""
        body.append(
            f"<tr><td class=model>{e(r.label)}</td><td class=mode>{e(MODE_LABELS.get(r.mode, r.mode))}</td>"
            f"<td class=num>{r.correct:.0f}%</td><td class=num>{r.abstained:.0f}%</td>"
            f'<td class="num{bad}">{r.hallucinated:.0f}%</td><td class=num>{r.estimated:.0f}%</td>'
            f"<td class=num>{r.placeholder:.0f}%</td><td class=num>{precision}</td>"
            f"<td class=num>${r.cost_usd:.2f}</td><td class=num>{r.p95_s:.1f} s</td></tr>"
        )
    bt = ""
    if by_type:
        head = "".join(f"<th class=num>{e(t.capitalize())}</th>" for t in QUESTION_TYPES)
        trs = "".join(
            f"<tr><td class=model>{e(b['model'])}</td>"
            + "".join(f"<td class=num>{_cell(b[t])}</td>" for t in QUESTION_TYPES)
            + "</tr>"
            for b in by_type
        )
        bt = (
            '<h3 class="sub">With a lookup tool, by question type</h3>'
            '<p class="sub">Year-to-date questions test whether the model picks the right period. '
            "Growth and margin need a calculation.</p>"
            f'<div class="table"><table><tr><th>Model</th>{head}</tr>{trs}</table></div>'
        )
    iss = ""
    issue_rows = [r for r in _sort(rows) if r.prose or r.text_calls]
    if issue_rows:
        trs = "".join(
            f"<tr><td class=model>{e(r.label)}</td><td class=mode>{e(MODE_LABELS.get(r.mode, r.mode))}</td>"
            f"<td class=num>{r.prose:.0f}%</td><td class=num>{r.text_calls:.0f}%</td></tr>"
            for r in issue_rows
        )
        iss = (
            '<h3 class="sub">Format problems</h3>'
            '<p class="sub">Some models answer in a sentence instead of JSON, or type a tool call as text instead of '
            "making one. Sentences are read for a dollar amount or percent and typed tool calls are run, so these "
            "models are graded on their answers, not their formatting.</p>"
            '<div class="table"><table><tr><th>Model</th><th>Mode</th><th class=num>Answered in a sentence</th>'
            f"<th class=num>Typed the tool call as text</th></tr>{trs}</table></div>"
        )
    ex = ""
    if examples:
        items = "".join(
            f"<tr><td class=model>{e(x['model'])}</td><td>{e(x['kind'])}</td><td>{e(x['question'])}</td>"
            f'<td class="num bad">{e(fmt_value(x["said"], x["unit"]))}</td>'
            f'<td class=num><a href="{e(x["source"])}">{e(fmt_value(x["actual"], x["unit"]))}</a></td></tr>'
            for x in examples
        )
        ex = (
            '<h3 class="sub">Examples: what the model said vs. what the filing says</h3>'
            '<p class="sub">Click a filing number to check it on the SEC site. A labeled guess is a wrong number '
            "the model said was an estimate.</p>"
            '<div class="table"><table><tr><th>Model</th><th>Type</th><th>Question</th>'
            f"<th class=num>Said</th><th class=num>Filing says</th></tr>{items}</table></div>"
        )
    return PAGE.format(
        headline=e(headline),
        subhead=e(subhead),
        tiles=cards_html(rows),
        intro=e(intro),
        rows="\n".join(body),
        by_type=bt,
        issues=iss,
        examples=ex,
        updated=e(updated),
    )


def write_report(run_dir: Path, models: dict[str, ModelSpec], pages_dir: Path | None, updated: str) -> list[Row]:
    meta = json.loads((run_dir / "meta.json").read_text())
    questions = {q.id: q for q in read_questions(run_dir / "questions.jsonl")}
    rows, by_key = collect(run_dir, models, questions)
    labels = {s.name: s.label for s in models.values()}
    examples = hallucination_examples(by_key, questions, labels)
    by_type = tool_accuracy_by_type(by_key, questions, labels)
    summary = {"meta": meta, "rows": [asdict(r) for r in rows], "by_type": by_type, "examples": examples}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (run_dir / "leaderboard.md").write_text(to_markdown(rows, meta, examples, by_type))
    if pages_dir is not None:
        pages_dir.mkdir(parents=True, exist_ok=True)
        (pages_dir / "index.html").write_text(to_html(rows, meta, examples, updated, by_type))
    return rows
