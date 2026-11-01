"""Read a model's answer and grade it against the filing.

Outcomes:
  correct      the number matches the filing
  abstained    the model said it doesn't know (value null)
  hallucinated the model stated a wrong number as fact
  estimated    the model gave a wrong number but said it was an estimate or guess
  placeholder  the model answered 0 for a figure that isn't 0: it didn't know, but filled in a number
  invalid      no readable answer
  error        the API call failed (not counted in rates)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from .questions import Question

Outcome = Literal["correct", "abstained", "hallucinated", "estimated", "placeholder", "invalid", "error"]

REL_TOLERANCE = 0.005  # amounts: within 0.5%
EPS_TOLERANCE = 0.011  # per-share amounts: within about a cent
PCT_TOLERANCE = 0.15  # growth: within 0.15 percentage points
SCALES = (1e3, 1e6, 1e9)  # thousands, millions, billions

ABSTAIN_PATTERN = re.compile(
    r"\b(don't know|do not know|not (?:yet )?available|no (?:reliable )?information|not enough information"
    r"|(?:cannot|can't|can not) (?:find|provide|determine|answer|give)|unable to|not able to|unknown|beyond my"
    r"|after my (?:knowledge|training))\b",
    re.I,
)

# A number in a sentence: "$36,629,000,000", "$45.5 billion", "18.8%". Bare numbers are skipped,
# since prose is full of dates ("September 30, 2026").
PROSE_NUMBER = re.compile(
    r"(?:\$|\bUSD)\s?(?P<num>-?\d[\d,]*(?:\.\d+)?)\s*(?P<scale>trillion|billion|million|thousand)?"
    r"|(?P<num2>-?\d[\d,]*(?:\.\d+)?)\s*(?P<unit2>%|percent|trillion|billion|million|USD\b)",
    re.I,
)
SCALE_WORDS = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}


ESTIMATE_PATTERN = re.compile(
    r"\b(estimate[ds]?|estimating|approximat\w*|my guess|a guess|projected|projection|not the reported"
    r"|rather than a reported|based on (?:its |the company's )?guidance)\b",
    re.I,
)


@dataclass
class Parsed:
    value: float | None
    abstained: bool
    readable: bool
    prose: bool = False  # answered in a sentence instead of the requested JSON


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _to_number(raw) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip().replace(",", "").replace("$", "").replace("%", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _json_object(text: str) -> dict | None:
    """The last {...} in the text that parses as JSON (models sometimes explain first)."""
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text, flags=re.S))):
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _prose_number(text: str) -> float | None:
    """The last money amount or percent written in a sentence."""
    found = None
    for m in PROSE_NUMBER.finditer(text):
        if m.group("num"):
            value = float(m.group("num").replace(",", ""))
            scale = (m.group("scale") or "").lower()
        else:
            value = float(m.group("num2").replace(",", ""))
            scale = m.group("unit2").lower()  # "usd" and "%" have no multiplier
        found = value * SCALE_WORDS.get(scale, 1)
    return found


def parse_answer(text: str) -> Parsed:
    text = _strip_thinking(text or "")
    obj = _json_object(text)
    if obj is not None and "value" in obj:
        if obj["value"] is None or (isinstance(obj["value"], str) and obj["value"].strip().lower() in ("null", "")):
            return Parsed(None, abstained=True, readable=True)
        number = _to_number(obj["value"])
        if number is not None:
            return Parsed(number, abstained=False, readable=True)
        return Parsed(None, abstained=bool(ABSTAIN_PATTERN.search(text)), readable=False)
    if ABSTAIN_PATTERN.search(text):
        return Parsed(None, abstained=True, readable=True)
    number = _prose_number(text)
    if number is not None:
        return Parsed(number, abstained=False, readable=True, prose=True)
    return Parsed(None, abstained=False, readable=False)


def matches(question: Question, value: float) -> tuple[bool, bool]:
    """(correct, needed_rescale). A right number in the wrong scale (millions for dollars,
    a fraction for a percent) counts as correct but is flagged."""
    truth = question.answer
    if question.unit == "percent":
        if abs(value - truth) <= PCT_TOLERANCE:
            return True, False
        return abs(value * 100 - truth) <= PCT_TOLERANCE, True
    if question.unit == "USD/shares":
        return abs(value - truth) <= EPS_TOLERANCE, False

    def close(v: float) -> bool:
        return truth != 0 and abs(v - truth) / abs(truth) <= REL_TOLERANCE

    if close(value):
        return True, False
    for scale in SCALES:
        if close(value * scale):
            return True, True
    return False, False


def grade(question: Question, text: str) -> tuple[Outcome, float | None, bool]:
    """Returns (outcome, value read from the answer, needed_rescale)."""
    parsed = parse_answer(text)
    if parsed.abstained:
        return "abstained", None, False
    if parsed.value is None:
        return "invalid", None, False
    correct, rescaled = matches(question, parsed.value)
    if correct:
        return "correct", parsed.value, rescaled
    if parsed.value == 0 and question.answer != 0:
        return "placeholder", parsed.value, False
    if ESTIMATE_PATTERN.search(_strip_thinking(text or "")):
        return "estimated", parsed.value, False
    return "hallucinated", parsed.value, False
