# FreshFin

How often do AI models make up numbers about financial reports they've never seen?

FreshFin builds questions from 10-Q and 10-K filings published in the last few days, after a model's
training data ends, takes the exact answer from the SEC's XBRL data, and asks each model three ways:

1. **No tools, told "I don't know" is fine.** The model can't know the answer, so the honest reply is null.
2. **No tools, plain question.** Just "what was the revenue?", the way most people ask. This shows what a
   model does by default when it doesn't know.
3. **With a lookup tool.** The model can pull reported values from the SEC's data and has to pick the right
   one: the right quarter, not year-to-date, the right end date.

The questions refresh every week, so the benchmark can't leak into training data, and nobody labels
answers by hand: every expected value is the number the company itself tagged in its filing.

## Results

<!-- results -->
First run: 78 questions from 13 10-Qs filed October 17–31, 2026 (Microsoft, Amazon, Alphabet, Meta, Tesla,
Intel, Netflix, Mastercard, Procter & Gamble, Coca-Cola, Johnson & Johnson, Eli Lilly, Boeing). Every model
answered every question in all three modes.

| Model | Mode | Correct | Said "don't know" | Made up | Labeled guess | Filled in 0 | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Haiku 5.5 | no tools, "don't know" allowed | 0% | 100% | 0% | 0% | 0% | $0.01 |
| Claude Sonnet 5.5 | no tools, "don't know" allowed | 0% | 100% | 0% | 0% | 0% | $0.09 |
| Qwen3 8B, local | no tools, "don't know" allowed | 0% | 100% | 0% | 0% | 0% | $0 |
| Claude Haiku 5.5 | no tools, plain question | 0% | 100% | 0% | 0% | 0% | $0.01 |
| Claude Sonnet 5.5 | no tools, plain question | 0% | 97% | 0% | 3% | 0% | $0.20 |
| Qwen3 8B, local | no tools, plain question | 0% | 9% | **9%** | 0% | **77%** | $0 |
| Claude Haiku 5.5 | lookup tool | 100% | 0% | 0% | 0% | 0% | $0.03 |
| Claude Sonnet 5.5 | lookup tool | 100% | 0% | 0% | 0% | 0% | $0.59 |
| Qwen3 8B, local | lookup tool | 94% | 4% | 1% | 0% | 0% | $0 |

Full table: [`results/2026-10-31/leaderboard.md`](results/2026-10-31/leaderboard.md). Every answer, tool call
and grade: [`results/2026-10-31/records/`](results/2026-10-31/records/).

**One sentence decides whether a small model invents numbers.** When the prompt said "don't know" was fine,
Qwen3 8B said it 78 times out of 78. Asked the same questions plainly, it gave a number 86% of the time: $0 for
60 answers, and 7 invented values, like Johnson & Johnson's EPS as $2.74 (actual $0.09) and Microsoft's
operating income as $24.5B (actual $45.9B). A pipeline that trusts the JSON would store all of them.

**Claude didn't make numbers up either way.** Haiku said "don't know" to all 156 no-tool questions. Sonnet did
too, except two growth questions where it estimated from company guidance and said so: Netflix 13.5% (actual
11.85%) and Eli Lilly 25% (actual 38.61%). Those count as labeled guesses, not made-up numbers.

**With a lookup tool, all three are reliable, and the misses are tool-use mistakes.** Both Claude models got
78/78. Qwen3 got 73/78: it copied Meta's net income with an extra zero ($98.6B for $9.86B), and for three
Mastercard questions it looked up the wrong ticker (MSTR, MRK, MC), found nothing that matched, and said so.

**Cost.** All 234 answers cost $0.05 on Haiku and $0.88 on Sonnet, 18x more for the same result. Qwen3 is free
but took up to 88 seconds per answer on a MacBook.

**If you run a model over financial data:** give it an explicit way to say it doesn't know, treat a 0 for
revenue as missing data rather than a value, and validate tickers in your lookup tool.
<!-- /results -->

## Why

Finance teams are putting LLMs in front of earnings data. The failure that costs money isn't a model saying
"I don't know", it's a model stating a confident, plausible, wrong number. Static benchmarks can't measure
that for new filings, because their questions end up in the next model's training data. FreshFin only asks
about filings that didn't exist when the model was trained.

## How it works

```mermaid
flowchart LR
    E[EDGAR: filings from the last N days] --> F[XBRL facts first reported in each filing]
    F --> Q[Questions + exact answers]
    Q --> C[No tools, may say don't know]
    Q --> P[No tools, plain question]
    Q --> T[With lookup tool]
    C --> G[Grade: correct / don't know / made up / labeled guess / filled in 0]
    P --> G
    T --> G
    G --> R[Leaderboard, JSON, web page]
```

- **Questions.** For each new filing, facts tagged with that filing's accession number and its current period
  end: revenue, net income, diluted EPS, operating income, total assets, cash, and year-over-year revenue
  growth. These are the company's newest reported numbers, from after the model's training data ends.
- **Freshness per model.** `models.toml` has a `fresh_after` date per model (its training cutoff, or its
  release date when the cutoff isn't published). Questions from filings on or before that date are skipped
  for that model.
- **Answers.** Models reply with `{"value": number or null}`. Amounts must be within 0.5%, EPS within a cent,
  growth within 0.15 points. A right number in the wrong scale (millions instead of dollars) counts but is flagged.
- **Outcomes.** correct; said "don't know"; made up a number (a wrong number stated as fact); labeled guess
  (a wrong number the model said was an estimate); filled in 0 (it didn't know, but put 0 where the format asked
  for a number, which a pipeline would store as a real value); unreadable. "Right when it answered" is correct divided
  by every number given: how far you can trust a number the model does give you. `report` re-grades saved
  answers, so a change to the scoring rules never needs new API calls.
- **Tool mode.** One tool, `get_reported_values(ticker, metric)`, returns the last 12 reported periods for
  the metric, newest first, each with its period in words. Picking the right row is the test.

## Run it

You need [uv](https://docs.astral.sh/uv/). No other dependencies: plain Python, standard library only.

```bash
cp .env.example .env                 # set SEC_USER_AGENT, and ANTHROPIC_API_KEY for Claude
cp models.example.toml models.toml   # pick models, check prices and fresh_after dates
uv sync
uv run pytest

uv run freshfin build --days 14                            # questions from the last 14 days of filings
uv run freshfin run results/2026-11-01 --max-cost 0.50     # every model in models.toml, all three modes
uv run freshfin report results/2026-11-01                  # leaderboard.md, summary.json, docs/index.html
```

Useful options: `build --tickers AAPL MSFT`, `run --models qwen3-16k --modes closed,plain --limit 10`,
`run --restart` to ask again instead of resuming. Runs resume: stop with Ctrl+C and run the same command
again. Failed API calls are retried on the next run.

Local models work through any OpenAI-compatible endpoint. For Ollama:

```bash
ollama pull qwen3:8b
printf 'FROM qwen3:8b\nPARAMETER num_ctx 16384\n' > Modelfile && ollama create qwen3-16k -f Modelfile && rm Modelfile
```

## Weekly runs

`.github/workflows/benchmark.yml` builds questions from the last 7 days, runs the Claude models with a budget,
and commits the results and the web page. Set the repo variable `SEC_USER_AGENT`, the secret
`ANTHROPIC_API_KEY`, and `FRESHFIN_SCHEDULE=on` to run it every Monday. Serve `docs/` with GitHub Pages.

## Project layout

```
src/freshfin/
  edgar.py      SEC EDGAR client: recent filings, XBRL company facts (rate limited, cached)
  metrics.py    which XBRL tags become questions, and how periods are worded
  questions.py  facts first reported in a filing -> questions with exact answers
  build.py      a run's question set for a date window
  llm.py        Anthropic and OpenAI-compatible chat with tool use, plain HTTP
  runner.py     the three modes, resumable, budget, freshness check
  scoring.py    read the answer, grade it
  report.py     leaderboard, JSON, static page
  cli.py        freshfin build | run | report
results/        one folder per run: questions, raw records, summary, leaderboard
docs/           the latest leaderboard page
```

## Limits

- Only facts companies tag in XBRL, and only US filers. Banks and insurers use different revenue tags, so
  they produce fewer questions.
- A filing's XBRL data can show up a day after the filing; those filings are picked up by the next run.
- `fresh_after` dates come from published cutoffs or release dates. If a provider's cutoff is later than
  stated, a model could have seen a filing; the default 7–14 day window keeps that unlikely.
- Lookup questions test recall of a single number. They don't test reading comprehension or analysis.

## License

MIT
