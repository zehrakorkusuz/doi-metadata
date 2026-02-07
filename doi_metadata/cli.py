"""CLI entry point using Typer."""

# NOTE: do NOT use `from __future__ import annotations` — breaks typer runtime inspection

import asyncio
import logging
import sys
from enum import Enum
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(name="doi-metadata", help="Aggregate scholarly metadata from 11 APIs for a given DOI.")
console = Console()


class OutputFormat(str, Enum):
    summary = "summary"
    json = "json"


@app.command()
def lookup(
    doi: str = typer.Argument(help="The DOI to look up (e.g. 10.1038/s41586-020-2649-2)"),
    format: OutputFormat = typer.Option(OutputFormat.summary, "--format", "-f", help="Output format"),
    include_raw: bool = typer.Option(False, "--include-raw", help="Include raw API responses in JSON output"),
    no_follow: bool = typer.Option(False, "--no-follow", help="Skip Phase 3 link following"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Look up metadata for a DOI across all scholarly infrastructure sources."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)-8s %(name)s: %(message)s", stream=sys.stderr)

    # Suppress noisy HTTP logs unless verbose
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    from doi_metadata.orchestrator import lookup as do_lookup

    result = asyncio.run(do_lookup(doi, include_raw=include_raw, follow_links=not no_follow))

    if format == OutputFormat.json:
        from doi_metadata.output import to_json

        console.print_json(to_json(result))
    else:
        from doi_metadata.output import to_summary

        console.print(to_summary(result))


if __name__ == "__main__":
    app()
