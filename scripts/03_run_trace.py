"""Stage 4 entry — run L1 traceability queries against Fuseki.

Compares results to ``data/generated/ground_truth.json``. Requires Fuseki
to be loaded by ``02_load_ontorag.py`` first.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ontorag.stores.factory import create_store

from ontorag_demo.verify.trace import (
    failures_per_assembly_condition,
    failures_per_lot,
    failures_per_supplier,
    products_from_lot,
)

app = typer.Typer(add_completion=False)
console = Console()


async def _run(ground_truth_path: Path, top_n: int) -> None:
    gt = json.loads(ground_truth_path.read_text())
    store = create_store()

    console.rule("L1 SPARQL — failures per lot (top {0})".format(top_n))
    rows = await failures_per_lot(store, limit=top_n)
    table = Table()
    table.add_column("Rank", justify="right")
    table.add_column("Lot")
    table.add_column("SPARQL count", justify="right")
    table.add_column("Ground truth", justify="right")
    table.add_column("Match")
    contaminated = gt["contaminated_lot_id"]
    for rank, r in enumerate(rows, start=1):
        gt_count = gt["failures_by_lot"].get(r.lot_id, 0)
        match = "[green]✓[/]" if gt_count == r.failure_count else "[red]✗[/]"
        flag = " [yellow](contaminated)[/]" if r.lot_id == contaminated else ""
        table.add_row(str(rank), r.lot_id + flag, str(r.failure_count), str(gt_count), match)
    console.print(table)

    console.rule("L1 SPARQL — failures per supplier")
    sup_rows = await failures_per_supplier(store)
    table = Table()
    table.add_column("Supplier")
    table.add_column("SPARQL count", justify="right")
    table.add_column("Ground truth", justify="right")
    suspect = gt["suspect_supplier_id"]
    for s in sup_rows:
        gt_count = gt["failures_by_supplier"].get(s.supplier_id, 0)
        flag = " [yellow](suspect)[/]" if s.supplier_id == suspect else ""
        table.add_row(s.supplier_id + flag, str(s.failure_count), str(gt_count))
    console.print(table)

    console.rule("L1 SPARQL — assembly-step condition vs failures (observational)")
    by_cond = await failures_per_assembly_condition(store)
    table = Table()
    table.add_column("Assembly condition")
    table.add_column("Failures", justify="right")
    for cond, n in sorted(by_cond.items(), key=lambda kv: -kv[1]):
        table.add_row(cond, str(n))
    console.print(table)
    console.print(
        "\n[dim]Note: this is *correlation*. Whether 'low' assembly pressure"
        " is the causal driver — that's the Stage 4-causal question.[/]\n"
    )

    console.rule(f"Sanity check — products traceable to {contaminated}")
    pids = await products_from_lot(store, contaminated)
    console.print(f"  {len(pids)} products: {', '.join(pids[:6])}{'...' if len(pids) > 6 else ''}")


@app.command()
def main(
    ground_truth: Path = typer.Option(
        Path("data/generated/ground_truth.json"), "--ground-truth"
    ),
    top_n: int = typer.Option(5, "--top", help="How many top lots to print."),
) -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_run(ground_truth, top_n))


if __name__ == "__main__":
    app()
