# FreshFin results: filings from 2026-10-17 to 2026-10-31

104 questions from 13 filings. Every answer is the filing's own XBRL value.

| Model | Mode | Correct | Said "don't know" | Made up a number | Labeled guess | Filled in 0 | Unreadable | Right when it answered | Cost | p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Haiku 5.5 | no tools, "don't know" OK | 0% | 100% | **0%** | 0% | 0% | 0% | – | $0.01 | 1.7 s |
| Claude Sonnet 5.5 | no tools, "don't know" OK | 0% | 100% | **0%** | 0% | 0% | 0% | – | $0.11 | 1.8 s |
| Llama 3.2 3B (local) | no tools, "don't know" OK | 0% | 95% | **0%** | 0% | 0% | 5% | – | $0.00 | 0.3 s |
| Mistral 7B (local) | no tools, "don't know" OK | 0% | 99% | **0%** | 0% | 0% | 1% | – | $0.00 | 3.7 s |
| Qwen3 8B (local) | no tools, "don't know" OK | 0% | 100% | **0%** | 0% | 0% | 0% | – | $0.00 | 19.6 s |
| Claude Sonnet 5.5 | no tools, plain question | 0% | 94% | **0%** | 6% | 0% | 0% | 0% | $0.28 | 4.0 s |
| Claude Haiku 5.5 | no tools, plain question | 0% | 99% | **1%** | 0% | 0% | 0% | 0% | $0.02 | 2.7 s |
| Qwen3 8B (local) | no tools, plain question | 0% | 10% | **11%** | 0% | 71% | 9% | 0% | $0.00 | 85.1 s |
| Llama 3.2 3B (local) | no tools, plain question | 1% | 14% | **67%** | 0% | 2% | 15% | 1% | $0.00 | 0.4 s |
| Mistral 7B (local) | no tools, plain question | 0% | 0% | **99%** | 0% | 0% | 1% | 0% | $0.00 | 1.1 s |
| Claude Haiku 5.5 | lookup tool | 100% | 0% | **0%** | 0% | 0% | 0% | 100% | $0.04 | 3.3 s |
| Claude Sonnet 5.5 | lookup tool | 100% | 0% | **0%** | 0% | 0% | 0% | 100% | $0.88 | 7.5 s |
| Qwen3 8B (local) | lookup tool | 94% | 4% | **1%** | 0% | 0% | 1% | 99% | $0.00 | 87.8 s |
| Llama 3.2 3B (local) | lookup tool | 49% | 7% | **14%** | 0% | 0% | 31% | 78% | $0.00 | 4.1 s |
| Mistral 7B (local) | lookup tool | 52% | 4% | **16%** | 10% | 0% | 18% | 67% | $0.00 | 27.6 s |

## Format problems

Answers in a sentence are read for a dollar amount or percent; tool calls typed as text are run.

| Model | Mode | Answered in a sentence | Typed the tool call as text |
| --- | --- | --- | --- |
| Llama 3.2 3B (local) | lookup tool | 56% | 0% |
| Mistral 7B (local) | lookup tool | 67% | 29% |

## With the lookup tool, by question type

| Model | Latest value | Year-to-date | Growth | Margin |
| --- | --- | --- | --- | --- |
| Claude Haiku 5.5 | 67/67 | 13/13 | 13/13 | 11/11 |
| Claude Sonnet 5.5 | 67/67 | 13/13 | 13/13 | 11/11 |
| Llama 3.2 3B (local) | 43/67 | 8/13 | 0/13 | 0/11 |
| Mistral 7B (local) | 40/67 | 9/13 | 5/13 | 0/11 |
| Qwen3 8B (local) | 63/67 | 13/13 | 12/13 | 10/11 |

## Examples: what the model said vs. what the filing says

| Model | Type | Question | Said | Filing says |
| --- | --- | --- | --- | --- |
| Claude Haiku 5.5 | made up | What was Alphabet's operating margin (operating income as a percent of revenue) for the three months ended September 30, 2026, as reported in its 10-Q filed on October 29, 2026? | 32.00% | [31.81%](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000084/) |
| Claude Sonnet 5.5 | labeled guess | By what percent did Eli Lilly's revenue for the three months ended September 30, 2026 change compared with the same period a year earlier, as reported in its 10-Q filed on October 29, 2026? | 25.00% | [38.61%](https://www.sec.gov/Archives/edgar/data/59478/000005947826000108/) |
| Claude Sonnet 5.5 | labeled guess | What was Mastercard's operating margin (operating income as a percent of revenue) for the three months ended September 30, 2026, as reported in its 10-Q filed on October 29, 2026? | 58.50% | [59.77%](https://www.sec.gov/Archives/edgar/data/1141391/000114139126000124/) |
| Claude Sonnet 5.5 | labeled guess | What was Mastercard's revenue for the nine months ended September 30, 2026, as reported in its 10-Q filed on October 29, 2026? | $26.90B | [$27.48B](https://www.sec.gov/Archives/edgar/data/1141391/000114139126000124/) |
| Llama 3.2 3B (local) | made up | By what percent did Amazon's revenue for the three months ended September 30, 2026 change compared with the same period a year earlier, as reported in its 10-Q filed on October 30, 2026? | -3.20% | [12.09%](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/) |
| Llama 3.2 3B (local) | made up | What was Amazon's revenue for the nine months ended September 30, 2026, as reported in its 10-Q filed on October 30, 2026? | $497.33B | [$584.07B](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/) |
| Llama 3.2 3B (local) | made up | What were Boeing's diluted earnings per share for the three months ended September 30, 2026, as reported in its 10-Q filed on October 27, 2026? | $1.03 | [$-0.26](https://www.sec.gov/Archives/edgar/data/12927/000162828026067508/) |
| Mistral 7B (local) | made up | What were Amazon's diluted earnings per share for the three months ended September 30, 2026, as reported in its 10-Q filed on October 30, 2026? | $7.00 | [$1.89](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/) |
| Mistral 7B (local) | made up | What was Amazon's net income for the three months ended September 30, 2026, as reported in its 10-Q filed on October 30, 2026? | $36.40B | [$20.68B](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/) |
| Mistral 7B (local) | made up | What was Amazon's operating income for the three months ended September 30, 2026, as reported in its 10-Q filed on October 30, 2026? | $13.40B | [$28.08B](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/) |
| Qwen3 8B (local) | made up | What was Amazon's operating margin (operating income as a percent of revenue) for the three months ended September 30, 2026, as reported in its 10-Q filed on October 30, 2026? | 18.80% | [13.90%](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/) |
| Qwen3 8B (local) | made up | By what percent did Alphabet's revenue for the three months ended September 30, 2026 change compared with the same period a year earlier, as reported in its 10-Q filed on October 29, 2026? | 12.50% | [24.65%](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000084/) |
| Qwen3 8B (local) | made up | What was Intel's operating margin (operating income as a percent of revenue) for the three months ended September 26, 2026, as reported in its 10-Q filed on October 30, 2026? | 18.80% | [15.27%](https://www.sec.gov/Archives/edgar/data/50863/000005086326000191/) |
