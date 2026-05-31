"""Stage 3 entry point — sample synthetic data and write Turtle + ground truth.

Usage::

    uv run python scripts/01_generate_data.py [--output data/generated]
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ontorag_demo.causal.model import DEFAULT_GENERATOR_CONFIG
from ontorag_demo.generator import generate

app = typer.Typer(add_completion=False, help="Generate synthetic manufacturing data.")
console = Console()


@app.command()
def main(
    output: Path = typer.Option(
        Path("data/generated"),
        "--output",
        "-o",
        help="Directory for the generated Turtle and ground-truth JSON.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)
    result = generate(config=DEFAULT_GENERATOR_CONFIG, output_dir=output)

    console.rule("Generation summary")
    console.print(
        f"Turtle:        [green]{result.turtle_path}[/]  ({result.triple_count} triples)\n"
        f"Ground truth:  [green]{result.ground_truth_path}[/]\n"
    )

    gt = result.ground_truth
    console.print(
        f"products: [bold]{gt.total_products}[/]   failures: [bold red]{gt.total_failures}[/]"
        f"   ({gt.total_failures / gt.total_products:.1%} defect rate)"
    )
    console.print(
        f"suspect supplier: [yellow]{gt.suspect_supplier_id}[/]   "
        f"contaminated lot: [yellow]{gt.contaminated_lot_id}[/]"
    )

    table = Table(title="Failures by attributed cause (heuristic)")
    table.add_column("Cause")
    table.add_column("Count", justify="right")
    for cause, products in sorted(gt.failures_by_cause.items(), key=lambda kv: -len(kv[1])):
        table.add_row(cause, str(len(products)))
    console.print(table)

    table = Table(title="Failures by supplier")
    table.add_column("Supplier")
    table.add_column("Failures", justify="right")
    for supplier, count in sorted(gt.failures_by_supplier.items(), key=lambda kv: -kv[1]):
        table.add_row(supplier, str(count))
    console.print(table)


if __name__ == "__main__":
    app()
