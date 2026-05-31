"""Stage 5 entry — drive the RCA case end-to-end with ontorag-flow.

Prereq:
* ``scripts/02_load_ontorag.py`` has been run (ABox + BN + Causal loaded).

Usage::

    uv run python scripts/05_run_flow.py
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console

from ontorag.stores.factory import create_store

from ontorag_demo.flow.runner import run_flow

app = typer.Typer(add_completion=False)
console = Console()


async def _main(output_dir: Path, defect_rate: int) -> None:
    store = create_store()
    result = await run_flow(
        store,
        initial_defect_rate_percent=defect_rate,
        output_dir=output_dir,
        console=console,
    )
    console.rule("Result")
    console.print(f"case status: [bold]{result.final_status}[/]")
    console.print(f"case uri:    {result.case_uri}")
    console.print("final state keys:")
    for key, value in sorted(result.state_snapshot.items()):
        console.print(f"  - {key}: {value}")


@app.command()
def main(
    output: Path = typer.Option(
        Path("runs/flow"),
        "--output",
        "-o",
        help="Directory for the SQLite case store + audit Turtle export.",
    ),
    defect_rate: int = typer.Option(
        25,
        "--defect-rate",
        help="Initial defect rate percentage that triggers the case.",
    ),
) -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main(output, defect_rate))


if __name__ == "__main__":
    app()
