"""Command line: freshfin build | run | report"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from .config import ModelSpec, Settings, load_models


def _date(text: str) -> date:
    return date.fromisoformat(text)


def cmd_build(args: argparse.Namespace) -> int:
    from .build import build, save_build
    from .edgar import Edgar
    from .universe import COMPANIES

    settings = Settings.from_env()
    until = args.until or date.today()
    since = args.since or until - timedelta(days=args.days)
    tickers = [t.upper() for t in args.tickers] if args.tickers else list(COMPANIES)
    edgar = Edgar(settings.sec_user_agent, settings.cache_dir)
    result = build(edgar, tickers, since, until, args.per_filing)
    run_dir = args.out or Path("results") / until.isoformat()
    save_build(run_dir, result, since, until, tickers)
    print(f"{len(result.questions)} questions from {len(result.filings)} filings -> {run_dir}")
    for line in result.skipped:
        print(f"  skipped {line}")
    return 0 if result.questions else 1


def _client(spec: ModelSpec, settings: Settings):
    import os

    from .llm import AnthropicClient, OpenAICompatibleClient

    if spec.provider == "anthropic":
        return AnthropicClient(settings.anthropic_api_key)
    key = os.environ.get(spec.api_key_env, "") if spec.api_key_env else ""
    return OpenAICompatibleClient(spec.base_url or "http://localhost:11434/v1", key)


def _pick_models(names: str | None, models: dict[str, ModelSpec]) -> list[ModelSpec]:
    if not names:
        return list(models.values())
    picked = []
    for name in names.split(","):
        name = name.strip()
        if name not in models:
            raise SystemExit(f"Unknown model {name}. In models.toml: {', '.join(models)}")
        picked.append(models[name])
    return picked


def cmd_run(args: argparse.Namespace) -> int:
    from .edgar import Edgar
    from .questions import read_questions
    from .runner import FactLookup, records_path, run_model

    settings = Settings.from_env()
    models = load_models(settings.models_file)
    questions = read_questions(args.run_dir / "questions.jsonl")
    if args.limit:
        questions = questions[: args.limit]
    edgar = Edgar(settings.sec_user_agent, settings.cache_dir)
    # Tool lookups read cached facts; a week-old cache is fine since the filings are already in it.
    lookup = FactLookup(lambda t: edgar.company_facts(edgar.cik(t), max_age=7 * 24 * 3600))
    modes = [m.strip() for m in args.modes.split(",")]

    for spec in _pick_models(args.models, models):
        client = _client(spec, settings)
        for mode in modes:
            if args.restart:  # throw away earlier answers for this model and mode
                path = records_path(args.run_dir, spec.name, mode)
                if path.exists():
                    path.write_text("")
            print(f"{spec.label}, {mode}: {len(questions)} questions")

            def show(r, _mode=mode):
                print(
                    f"  {r.question_id:<55} {r.outcome:<12} {r.latency_ms / 1000:5.1f}s ${r.cost_usd:.4f}", flush=True
                )

            run_model(client, spec, questions, mode, args.run_dir, lookup, date.today(), args.max_cost, show)
    print(f"Done. Next: freshfin report {args.run_dir}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report import to_markdown, write_report

    settings = Settings.from_env()
    models = load_models(settings.models_file)
    pages = None if args.no_pages else args.pages
    rows = write_report(args.run_dir, models, pages, date.today().isoformat())
    if not rows:
        print("No results yet. Run: freshfin run", args.run_dir)
        return 1
    import json

    meta = json.loads((args.run_dir / "meta.json").read_text())
    print(to_markdown(rows, meta, []))
    print(f"Wrote {args.run_dir / 'leaderboard.md'}" + (f" and {pages / 'index.html'}" if pages else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", help="log progress")
    parser = argparse.ArgumentParser(prog="freshfin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", parents=[common], help="find new filings and write questions")
    b.add_argument("--since", type=_date, help="first filing date (default: --days before --until)")
    b.add_argument("--until", type=_date, help="last filing date (default: today)")
    b.add_argument("--days", type=int, default=14)
    b.add_argument("--tickers", nargs="*", help="default: the built-in list of large companies")
    b.add_argument("--per-filing", type=int, default=8)
    b.add_argument("--out", type=Path, help="run folder (default: results/<until>)")
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("run", parents=[common], help="ask the questions to each model")
    r.add_argument("run_dir", type=Path)
    r.add_argument("--models", help="comma-separated names from models.toml (default: all)")
    r.add_argument("--modes", default="closed,plain,tool")
    r.add_argument("--limit", type=int, help="only the first N questions")
    r.add_argument("--max-cost", type=float, help="stop a model and mode once it has spent this many USD")
    r.add_argument("--restart", action="store_true", help="ask again instead of resuming earlier answers")
    r.set_defaults(func=cmd_run)

    p = sub.add_parser("report", parents=[common], help="write leaderboard.md, summary.json and the HTML page")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--pages", type=Path, default=Path("docs"))
    p.add_argument("--no-pages", action="store_true")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as err:  # setup problems: show the fix, not a traceback
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
