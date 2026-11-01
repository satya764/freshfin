import json
from datetime import date

from freshfin.config import ModelSpec
from freshfin.llm import LLMError, Reply, ToolCall
from freshfin.questions import questions_for_filing
from freshfin.runner import FactLookup, ask, read_records, records_path, run_model
from helpers import msft_facts, msft_q1_filing

SPEC = ModelSpec(name="fake", label="Fake", provider="anthropic", price_in=1.0, price_out=1.0, workers=1)
TODAY = date(2026, 11, 1)


class ScriptedSession:
    def __init__(self, replies):
        self.replies = list(replies)
        self.tool_results = []

    def step(self):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def add_tool_results(self, results):
        self.tool_results.append(results)


class ScriptedClient:
    """Each start() gets the next script; a script is a list of Reply objects or exceptions."""

    def __init__(self, script_for):
        self.script_for = script_for
        self.started = []

    def start(self, model, system, user, tools):
        self.started.append((model, system, user, tools))
        return ScriptedSession(self.script_for(user, tools))


def questions():
    return questions_for_filing(msft_facts(), msft_q1_filing(), "Microsoft")


def lookup():
    return FactLookup(lambda ticker: msft_facts())


def test_closed_book_abstain():
    client = ScriptedClient(lambda user, tools: [Reply('{"value": null}', input_tokens=100, output_tokens=10)])
    record = ask(client, SPEC, questions()[0], "closed", None, TODAY)
    assert record.outcome == "abstained"
    assert record.cost_usd == 110 / 1_000_000
    assert client.started[0][3] is None  # no tools in closed mode
    assert "2026-11-01" in client.started[0][1]


def test_tool_mode_looks_up_then_answers():
    q = questions()[0]

    def script(user, tools):
        assert tools and tools[0]["name"] == "get_reported_values"
        return [
            Reply("", [ToolCall("t1", "get_reported_values", {"ticker": "MSFT", "metric": "revenue"})]),
            Reply('{"value": 92279000000, "unit": "USD"}'),
        ]

    record = ask(ScriptedClient(script), SPEC, q, "tool", lookup(), TODAY)
    assert record.outcome == "correct"
    assert record.tool_calls == [
        {"name": "get_reported_values", "args": {"ticker": "MSFT", "metric": "revenue"}, "ok": True}
    ]


def test_api_error_is_recorded():
    client = ScriptedClient(lambda user, tools: [LLMError("HTTP 529: overloaded")])
    record = ask(client, SPEC, questions()[0], "closed", None, TODAY)
    assert record.outcome == "error" and "529" in record.error


def test_fact_lookup_newest_first_without_duplicates():
    result = lookup()("msft", "revenue")
    values = result["values"]
    assert result["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert values[0]["end"] >= values[-1]["end"]
    keys = [(v["start"], v["end"]) for v in values]
    assert len(keys) == len(set(keys))
    assert any(v["value"] == 92_279_000_000 and v["start"] == "2026-07-01" for v in values)


def test_fact_lookup_unknown_metric():
    assert "error" in lookup()("MSFT", "vibes")


def test_run_model_resumes_and_retries_errors(tmp_path):
    qs = questions()
    calls = {"n": 0}

    def script(user, tools):
        calls["n"] += 1
        if user == qs[1].question and calls["n"] <= len(qs):
            return [LLMError("HTTP 500")]
        return [Reply('{"value": null}')]

    client = ScriptedClient(script)
    run_model(client, SPEC, qs, "closed", tmp_path, None, TODAY)
    first = read_records(records_path(tmp_path, "fake", "closed"))
    assert len(first) == len(qs) and sum(r.outcome == "error" for r in first) == 1

    run_model(client, SPEC, qs, "closed", tmp_path, None, TODAY)
    second = read_records(records_path(tmp_path, "fake", "closed"))
    assert len(second) == len(qs) and all(r.outcome == "abstained" for r in second)
    assert calls["n"] == len(qs) + 1  # only the failed question was asked again


def test_run_model_skips_filings_the_model_may_have_seen(tmp_path):
    stale = ModelSpec(name="old", label="Old", provider="anthropic", fresh_after=date(2026, 12, 31), workers=1)
    client = ScriptedClient(lambda user, tools: [Reply('{"value": null}')])
    assert run_model(client, stale, questions(), "closed", tmp_path, None, TODAY) == []
    assert client.started == []


def test_run_model_budget(tmp_path):
    client = ScriptedClient(lambda user, tools: [Reply('{"value": null}', input_tokens=600_000)])
    results = run_model(client, SPEC, questions(), "closed", tmp_path, None, TODAY, max_cost=1.0)
    assert len(results) == 2  # $0.60 each; stops once $1.00 is spent


def test_records_are_json_lines(tmp_path):
    client = ScriptedClient(lambda user, tools: [Reply('{"value": 1}')])
    run_model(client, SPEC, questions()[:2], "closed", tmp_path, None, TODAY)
    lines = records_path(tmp_path, "fake", "closed").read_text().splitlines()
    assert all(json.loads(line)["model"] == "fake" for line in lines)


def test_fact_lookup_prefers_the_concept_with_recent_data():
    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2018-01-01",
                                "end": "2018-12-31",
                                "val": 1,
                                "form": "10-K",
                                "filed": "2019-02-01",
                            }
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2026-07-01",
                                "end": "2026-09-30",
                                "val": 9,
                                "form": "10-Q",
                                "filed": "2026-10-29",
                            }
                        ]
                    }
                },
            }
        }
    }
    result = FactLookup(lambda t: facts)("GOOGL", "revenue")
    assert result["concept"] == "Revenues"
    assert result["values"][0]["value"] == 9


def test_plain_mode_gives_no_permission_to_abstain():
    client = ScriptedClient(lambda user, tools: [Reply('{"value": 90000000000, "unit": "USD"}')])
    record = ask(client, SPEC, questions()[0], "plain", None, TODAY)
    system = client.started[0][1]
    assert "null" not in system and "guess" not in system and client.started[0][3] is None
    assert record.outcome == "hallucinated"
