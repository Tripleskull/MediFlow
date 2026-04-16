"""Cross-platform command-line entrypoint for MediFlow."""

from __future__ import annotations

import argparse

from .analyse import run_analysis
from .reporting import compile_curated_documents, export_overleaf_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="Cross-platform commands for the MediFlow pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyse_parser = subparsers.add_parser("analyse", help="Refresh analysis outputs, figures, and generated report snippets.")
    analyse_parser.add_argument("--skip-plots", action="store_true", help="Do not regenerate PNG figures.")
    analyse_parser.add_argument("--skip-summary", action="store_true", help="Do not rewrite analysis_foundation.md.")
    analyse_parser.add_argument("--skip-docs", action="store_true", help="Do not rewrite generated LaTeX snippets and report context.")
    analyse_parser.add_argument("--no-compile", action="store_true", help="Refresh snippets but skip PDF compilation even if a TeX engine exists.")

    render_parser = subparsers.add_parser("render-docs", help="Refresh generated report context and LaTeX snippets from the current data.")
    render_parser.add_argument("--no-compile", action="store_true", help="Refresh snippets only and skip PDF compilation.")

    subparsers.add_parser("compile-docs", help="Compile the editable report and slide entrypoints using existing generated snippets.")

    overleaf_parser = subparsers.add_parser("export-overleaf", help="Create a self-contained Overleaf upload bundle.")
    overleaf_parser.add_argument("--no-refresh", action="store_true", help="Do not rerun the analysis before exporting.")
    overleaf_parser.add_argument("--no-zip", action="store_true", help="Create the bundle folder only and skip the zip archive.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyse":
        run_analysis(
            generate_plots=not args.skip_plots,
            write_summary=not args.skip_summary,
            write_documents=not args.skip_docs,
            compile_documents=not args.no_compile,
        )
        return

    if args.command == "render-docs":
        run_analysis(
            generate_plots=True,
            write_summary=True,
            write_documents=True,
            compile_documents=not args.no_compile,
        )
        return

    if args.command == "compile-docs":
        compile_curated_documents()
        return

    if args.command == "export-overleaf":
        if not args.no_refresh:
            run_analysis(
                generate_plots=True,
                write_summary=True,
                write_documents=True,
                compile_documents=False,
            )
        export_overleaf_bundle(make_zip=not args.no_zip)
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
