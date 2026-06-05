"""CLI entry point for the Luotea data pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from pipeline.bronze.connectors import ALL_SOURCES, SOURCE_ALIASES, ingest_all, ingest_source
from pipeline.bronze.ingest import IngestResult


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(message)s",
    )


def _print_ingest_result(result: IngestResult) -> None:
    print(f"\n{'=' * 72}")
    print(f"Source: {result.source_name} ({result.source_system})")
    print(f"Output: {result.output_dir}")
    print(f"Files:  {len(result.files)}")
    for f in result.files:
        rows = f.row_count if f.row_count is not None else "n/a"
        print(f"  • {f.dest_path.name:<55} {rows:>10} rows  ({f.byte_size:,} bytes)")
    total = result.total_row_count
    print(f"Total rows: {total if total is not None else 'n/a'}")
    print(f"Manifest:   {result.output_dir / '_manifest.json'}")


def cmd_ingest(args: argparse.Namespace) -> int:
    ingest_date = args.date or date.today().isoformat()
    sources = ALL_SOURCES if args.source == "all" else [args.source]

    results: list[IngestResult] = []
    for source in sources:
        results.append(ingest_source(source, ingest_date))

    for result in results:
        _print_ingest_result(result)

    print(f"\n{'=' * 72}")
    print(f"Ingested {len(results)} source(s) → bronze partition date {ingest_date}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    known = sorted(set(ALL_SOURCES) | set(SOURCE_ALIASES) | {"all"})
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Luotea Hackathon 2026 data pipeline",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Land raw source files in Bronze")
    ingest.add_argument(
        "--source",
        required=True,
        choices=known,
        help="Source family to ingest (or 'all')",
    )
    ingest.add_argument(
        "--date",
        help="Ingest partition date YYYY-MM-DD (default: today)",
    )
    ingest.set_defaults(func=cmd_ingest)

    transform = sub.add_parser("transform", help="Run Silver/Gold transforms")
    transform.add_argument(
        "--layer",
        choices=["silver", "gold"],
        default="silver",
        help="Pipeline layer to transform",
    )
    transform.add_argument(
        "--domain",
        choices=["erp", "iot", "all"],
        default="erp",
        help="Silver domain: erp, iot, or all",
    )
    transform.add_argument(
        "--date",
        help="Bronze ingest partition date YYYY-MM-DD (default: today)",
    )
    transform.set_defaults(func=cmd_transform)

    run = sub.add_parser("run", help="Run full pipeline DAG")
    run.add_argument(
        "--full",
        action="store_true",
        help="Bronze ingest → Silver → Gold → quality checks",
    )
    run.add_argument(
        "--date",
        help="Ingest partition date YYYY-MM-DD (default: today)",
    )
    run.set_defaults(func=cmd_run)

    validate = sub.add_parser("validate", help="Run spec-driven validation checks")
    validate.add_argument(
        "--date",
        help="Bronze ingest partition date YYYY-MM-DD (for reporting; default: today)",
    )
    validate.set_defaults(func=cmd_validate)

    qa = sub.add_parser("qa", help="Full pipeline run with QA gate")
    qa.add_argument(
        "--date",
        help="Ingest partition date YYYY-MM-DD (default: today)",
    )
    qa.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Validate existing outputs only (skip bronze ingest)",
    )
    qa.add_argument(
        "--verbose",
        action="store_true",
        help="Print every check",
    )
    qa.set_defaults(func=cmd_qa)

    return parser


def cmd_transform(args: argparse.Namespace) -> int:
    ingest_date = args.date or date.today().isoformat()
    domain = args.domain

    if args.layer == "gold":
        from pipeline.gold.run_gold import print_gold_summary, print_site_samples, run_gold

        results = run_gold(as_of_date=date.fromisoformat(ingest_date))
        print_gold_summary(results)
        print_site_samples(["site_valmet_l11", "site_aurora"])
        print(f"Gold build complete (as_of_date {ingest_date})")
        return 0

    if domain in ("erp", "all"):
        from pipeline.silver.run_erp import print_validation_stats, run_erp_silver

        print_validation_stats(run_erp_silver(ingest_date))

    if domain in ("iot", "all"):
        from pipeline.silver.run_iot import print_iot_validation_stats, run_iot_silver

        print_iot_validation_stats(run_iot_silver(ingest_date))

    print(f"Silver transform complete (domain={domain}, bronze date {ingest_date})")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.full:
        print("Specify --full to run the complete pipeline DAG.")
        return 2

    ingest_date = args.date or date.today().isoformat()
    as_of = date.fromisoformat(ingest_date)

    print(f"\n{'=' * 72}")
    print(f"Full pipeline run (ingest_date={ingest_date})")
    print(f"{'=' * 72}")

    print("\n[1/5] Bronze ingest (all sources)")
    ingest_results = ingest_all(ingest_date)
    for result in ingest_results:
        _print_ingest_result(result)

    print("\n[2/5] Silver ERP transforms")
    from pipeline.silver.run_erp import print_validation_stats, run_erp_silver

    print_validation_stats(run_erp_silver(ingest_date))

    print("\n[3/5] Silver IoT transforms")
    from pipeline.silver.run_iot import print_iot_validation_stats, run_iot_silver

    print_iot_validation_stats(run_iot_silver(ingest_date))

    print("\n[4/5] Gold marts")
    from pipeline.gold.run_gold import print_gold_summary, print_site_samples, run_gold

    print_gold_summary(run_gold(as_of_date=as_of))
    print_site_samples(["site_valmet_l11", "site_aurora"])

    print("\n[5/5] Quality checks")
    from pipeline.quality.checks import print_quality_report, run_all_checks

    report = run_all_checks()
    print_quality_report(report)

    print(f"\n{'=' * 72}")
    if report.passed:
        print("Pipeline run complete — all quality checks passed.")
        return 0
    print(f"Pipeline run finished with {report.error_count} quality error(s).")
    return 1


def cmd_validate(args: argparse.Namespace) -> int:
    ingest_date = args.date or date.today().isoformat()
    from pipeline.quality.report import QAResult, print_qa_summary, write_qa_report
    from pipeline.quality.runner import run_qa_checks

    checks = run_qa_checks(ingest_date)
    qa_result = QAResult.from_checks(
        ingest_date=ingest_date,
        checks=checks,
        pipeline_steps={"ingest": {"status": "skipped"}, "silver": {"status": "skipped"}, "gold": {"status": "skipped"}},
        duration_seconds=0,
    )
    write_qa_report(qa_result)
    print_qa_summary(qa_result)
    return 0 if qa_result.overall == "PASS" else 1


def cmd_qa(args: argparse.Namespace) -> int:
    import time

    ingest_date = args.date or date.today().isoformat()
    as_of = date.fromisoformat(ingest_date)
    start = time.perf_counter()
    pipeline_steps: dict = {}
    checks: list = []

    try:
        if args.skip_ingest:
            pipeline_steps["ingest"] = {"status": "skipped"}
        else:
            ingest_results = ingest_all(ingest_date)
            pipeline_steps["ingest"] = {"status": "ok", "sources": len(ingest_results)}

        from pipeline.gold.run_gold import run_gold
        from pipeline.quality.runner import run_qa_checks, snapshot_row_counts
        from pipeline.silver.run_erp import run_erp_silver
        from pipeline.silver.run_iot import run_iot_silver

        erp_results = run_erp_silver(ingest_date)
        iot_results = run_iot_silver(ingest_date)
        pipeline_steps["silver"] = {"status": "ok", "tables": len(erp_results) + len(iot_results)}

        gold_results = run_gold(as_of_date=as_of)
        pipeline_steps["gold"] = {"status": "ok", "tables": len(gold_results)}

        counts_before = snapshot_row_counts()
        run_erp_silver(ingest_date)
        run_iot_silver(ingest_date)
        run_gold(as_of_date=as_of)
        counts_after = snapshot_row_counts()

        checks = run_qa_checks(
            ingest_date,
            idempotent_before=counts_before,
            idempotent_after=counts_after,
            verbose=args.verbose,
        )
    except Exception as exc:
        logging.exception("QA pipeline step failed")
        pipeline_steps["error"] = {"status": "failed", "message": str(exc)}
        if not checks:
            from pipeline.quality.runner import run_qa_checks

            checks = run_qa_checks(ingest_date, verbose=args.verbose)

    from pipeline.quality.report import QAResult, print_qa_summary, write_qa_report

    duration = time.perf_counter() - start
    qa_result = QAResult.from_checks(
        ingest_date=ingest_date,
        checks=checks,
        pipeline_steps=pipeline_steps,
        duration_seconds=duration,
    )
    write_qa_report(qa_result)
    print_qa_summary(qa_result, verbose=args.verbose)
    return 0 if qa_result.overall == "PASS" else 1


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    code = args.func(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
