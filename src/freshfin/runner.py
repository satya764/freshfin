"""Ask every question to every model, in three modes:

  closed  no tools, and the prompt says "I don't know" is fine. The honest answer is null.
  plain   no tools, and the prompt just asks for the number, the way most people ask.
          Measures what a model does by default when it doesn't know.
  tool    the model can look up reported values from the SEC's XBRL data and must pick the right one.

Results are appended to one JSONL file per model and mode, so a stopped run resumes where it left off.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from .config import ModelSpec
from .llm import Client, LLMError
from .metrics import METRICS, describe_period
from .questions import Question
from .scoring import grade

log = logging.getLogger(__name__)

Mode = Literal["closed", "plain", "tool"]
MODES: tuple[Mode, ...] = ("closed", "plain", "tool")
MAX_TOOL_STEPS = 6

ANSWER_FORMAT = (
    'Reply with only a JSON object: {"value": <number or null>, "unit": "USD" | "USD/shares" | "percent"}. '
    "Give dollar amounts in full units (92279000000, not 92.3 billion) and percents as numbers (18.8 for 18.8%)."
)

CLOSED_SYSTEM = (
    "You answer questions about US public companies' financial reports. Today's date is {today}. "
    "You have no tools and no internet access: answer only from what you already know. "
    "If you do not know the exact reported figure, set value to null. Do not estimate or guess. " + ANSWER_FORMAT
)

PLAIN_SYSTEM = (
    "You answer questions about US public companies' financial reports. "
    'Reply with only a JSON object: {"value": <number>, "unit": "USD" | "USD/shares" | "percent"}. '
    "Give dollar amounts in full units (92279000000, not 92.3 billion) and percents as numbers (18.8 for 18.8%)."
)

TOOL_SYSTEM = (
    "You answer questions about US public companies' financial reports. Today's date is {today}. "
    "Use the get_reported_values tool to look up figures from the company's SEC XBRL data. Check that the "
    "period matches the question exactly (three months vs year-to-date, the right end date). Do any arithmetic "
    "carefully. If the data doesn't contain the answer, set value to null. " + ANSWER_FORMAT
)

LOOKUP_TOOL = {
    "name": "get_reported_values",
    "description": (
        "Reported values of one financial metric from a company's SEC filings (XBRL data), newest first. "
        "Each value has its period (start and end date; instant metrics have only an end date), the form "
        "and the filing date. Values are in full units."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker, e.g. MSFT"},
            "metric": {"type": "string", "enum": list(METRICS)},
        },
        "required": ["ticker", "metric"],
    },
}


@dataclass
class Record:
    question_id: str
    model: str
    mode: Mode
    outcome: str
    value: float | None
    rescaled: bool
    answer_text: str
    tool_calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str = ""


class FactLookup:
    """Backs the get_reported_values tool with company facts (from the EDGAR cache)."""

    def __init__(self, facts_for_ticker: Callable[[str], dict], limit: int = 12):
        self.facts_for_ticker = facts_for_ticker
        self.limit = limit

    def __call__(self, ticker: str, metric: str) -> dict:
        if metric not in METRICS:
            return {"error": f"unknown metric {metric}. Use one of: {', '.join(METRICS)}"}
        spec = METRICS[metric]
        try:
            facts = self.facts_for_ticker(ticker.upper().strip())
        except Exception as err:
            return {"error": f"no data for {ticker}: {err}"}
        gaap = facts.get("facts", {}).get("us-gaap", {})
        # Companies switch tags over the years; use the concept with the most recent data.
        candidates = []
        for priority, concept in enumerate(spec.concepts):
            entries = gaap.get(concept, {}).get("units", {}).get(spec.unit, [])
            if entries:
                candidates.append((max(e["end"] for e in entries), -priority, concept, entries))
        if candidates:
            _, _, concept, entries = max(candidates)
            seen, rows = set(), []
            for e in sorted(entries, key=lambda e: (e["end"], e["filed"]), reverse=True):
                key = (e.get("start"), e["end"])
                if key in seen:
                    continue  # the same period appears in later filings as a comparative
                seen.add(key)
                start = date.fromisoformat(e["start"]) if e.get("start") else None
                rows.append(
                    {
                        "period": describe_period(start, date.fromisoformat(e["end"])),
                        "start": e.get("start"),
                        "end": e["end"],
                        "value": e["val"],
                        "form": e["form"],
                        "filed": e["filed"],
                    }
                )
                if len(rows) >= self.limit:
                    break
            return {"ticker": ticker.upper(), "metric": metric, "concept": concept, "unit": spec.unit, "values": rows}
        return {"error": f"{ticker} reports no {metric} in XBRL"}


def ask(
    client: Client, spec: ModelSpec, question: Question, mode: Mode, lookup: FactLookup | None, today: date
) -> Record:
    started = time.perf_counter()
    system = {"closed": CLOSED_SYSTEM, "plain": PLAIN_SYSTEM, "tool": TOOL_SYSTEM}[mode].replace(
        "{today}", today.isoformat()
    )
    tools = [LOOKUP_TOOL] if mode == "tool" else None
    calls: list[dict] = []
    tokens_in = tokens_out = 0
    text = ""
    try:
        session = client.start(spec.name, system, question.question, tools)
        for _ in range(MAX_TOOL_STEPS):
            reply = session.step()
            tokens_in += reply.input_tokens
            tokens_out += reply.output_tokens
            text = reply.text
            if not reply.tool_calls or mode != "tool":
                break
            results = []
            for call in reply.tool_calls:
                if call.name == LOOKUP_TOOL["name"] and lookup is not None:
                    result = lookup(str(call.args.get("ticker", "")), str(call.args.get("metric", "")))
                else:
                    result = {"error": f"unknown tool {call.name}"}
                entry = {"name": call.name, "args": call.args, "ok": "error" not in result}
                if reply.calls_from_text:
                    entry["from_text"] = True
                calls.append(entry)
                results.append((call.id, json.dumps(result)))
            session.add_tool_results(results)
    except LLMError as err:
        return Record(
            question.id,
            spec.name,
            mode,
            "error",
            None,
            False,
            text[:4000],
            calls,
            tokens_in,
            tokens_out,
            spec.cost(tokens_in, tokens_out),
            _ms(started),
            str(err)[:500],
        )

    outcome, value, rescaled = grade(question, text)
    return Record(
        question.id,
        spec.name,
        mode,
        outcome,
        value,
        rescaled,
        text[:4000],
        calls,
        tokens_in,
        tokens_out,
        spec.cost(tokens_in, tokens_out),
        _ms(started),
    )


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def records_path(run_dir: Path, model: str, mode: Mode) -> Path:
    return run_dir / "records" / f"{model.replace(':', '_').replace('/', '_')}__{mode}.jsonl"


def read_records(path: Path) -> list[Record]:
    if not path.exists():
        return []
    return [Record(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def run_model(
    client: Client,
    spec: ModelSpec,
    questions: list[Question],
    mode: Mode,
    run_dir: Path,
    lookup: FactLookup | None,
    today: date,
    max_cost: float | None = None,
    progress: Callable[[Record], None] | None = None,
) -> list[Record]:
    path = records_path(run_dir, spec.name, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {r.question_id: r for r in read_records(path) if r.outcome != "error"}
    if done:  # drop old errors so they get retried
        path.write_text("".join(json.dumps(asdict(r)) + "\n" for r in done.values()))
    todo = [q for q in questions if q.id not in done]
    if spec.fresh_after:
        stale = [q for q in todo if q.filed <= spec.fresh_after]
        if stale:
            log.warning(
                "%s: skipping %d questions filed on or before %s (may be in training data)",
                spec.name,
                len(stale),
                spec.fresh_after,
            )
        todo = [q for q in todo if q.filed > spec.fresh_after]

    lock = threading.Lock()
    spent = sum(r.cost_usd for r in done.values())
    results = list(done.values())

    def work(q: Question) -> Record | None:
        nonlocal spent
        with lock:
            if max_cost is not None and spent >= max_cost:
                return None
        record = ask(client, spec, q, mode, lookup, today)
        with lock:
            spent += record.cost_usd
            with path.open("a") as f:
                f.write(json.dumps(asdict(record)) + "\n")
            results.append(record)
        if progress:
            progress(record)
        return record

    with ThreadPoolExecutor(max_workers=max(spec.workers, 1)) as pool:
        list(pool.map(work, todo))
    if max_cost is not None and spent >= max_cost:
        log.warning("%s %s: stopped at the $%.2f budget", spec.name, mode, max_cost)
    return results
