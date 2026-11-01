import json

from freshfin.config import ModelSpec
from freshfin.questions import questions_for_filing, write_questions
from freshfin.report import Row, fmt_value, summarize, to_html, to_markdown, write_report
from freshfin.runner import Record, records_path
from helpers import msft_facts, msft_q1_filing

SPEC = ModelSpec(name="m", label="Model <A>", provider="anthropic")


def rec(outcome, latency=1000, cost=0.01, value=None, qid="q"):
    return Record(qid, "m", "closed", outcome, value, False, "", [], 10, 10, cost, latency)


def test_summarize():
    records = [rec("correct"), rec("hallucinated"), rec("abstained"), rec("abstained"), rec("error")]
    row = summarize(records, SPEC, "closed")
    assert row.questions == 4 and row.errors == 1
    assert (row.correct, row.hallucinated, row.abstained) == (25.0, 25.0, 50.0)
    assert row.precision == 50.0
    assert row.cost_usd == 0.05


def test_summarize_no_answers_has_no_precision():
    assert summarize([rec("abstained")], SPEC, "closed").precision is None


def test_fmt_value():
    assert fmt_value(92_279_000_000, "USD") == "$92.28B"
    assert fmt_value(4.92, "USD/shares") == "$4.92"
    assert fmt_value(18.8, "percent") == "18.80%"
    assert fmt_value(None, "USD") == "–"


def test_markdown_and_html_escape():
    row = Row("m", "Model <A>", "closed", 10, 50, 30, 20, 0, 0, 0, 0, 71.4, 0.12, 1.0, 2.0)
    meta = {"since": "2026-10-18", "until": "2026-11-01", "questions": 10, "filings": [{}]}
    md = to_markdown([row], meta, [])
    assert '| Model <A> | no tools, may say "don\'t know" | 50% | 30% | **20%** |' in md
    page = to_html([row], meta, [], "2026-11-01")
    assert "Model &lt;A&gt;" in page and "<A>" not in page


def test_write_report(tmp_path):
    qs = questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft")
    write_questions(tmp_path / "questions.jsonl", qs)
    (tmp_path / "meta.json").write_text(
        json.dumps({"since": "2026-10-18", "until": "2026-11-01", "questions": len(qs), "filings": [{}]})
    )
    path = records_path(tmp_path, "m", "closed")
    path.parent.mkdir(parents=True)
    from dataclasses import asdict

    record = rec("hallucinated", value=1.0, qid=qs[0].id)
    record.answer_text = '{"value": 1.0}'
    path.write_text(json.dumps(asdict(record)) + "\n")
    rows = write_report(tmp_path, {"m": SPEC}, tmp_path / "docs", "2026-11-01")
    assert len(rows) == 1
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["examples"][0]["actual"] == 92_279_000_000
    assert "Wrong numbers without tools" in (tmp_path / "docs" / "index.html").read_text()


def test_cards_sum_every_kind_of_wrong_number():
    from freshfin.report import cards_html

    plain = Row("q", "Qwen", "plain", 78, 0, 9, 9, 0, 77, 5, 0, 0.0, 0.0, 1.0, 2.0)
    tool = Row("q", "Qwen", "tool", 78, 94, 4, 1, 0, 0, 1, 0, 99.0, 0.0, 1.0, 2.0)
    page = cards_html([plain, tool])
    assert '<b class="bad">86%</b>' in page and "<b>94%</b>" in page
