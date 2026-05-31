"""Stage 4 entry — run L2 posterior + L3 do/counterfactual against the demo BN.

Does NOT require Fuseki — uses ``ontorag.bayes.engine`` and
``ontorag.causal.engine`` directly on the in-memory BN/DAG. Run this first
to convince yourself the causal layer is wired correctly before trusting
the Stage 5 orchestration.
"""

from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.table import Table

from ontorag_demo.verify.causal import (
    DefectProbability,
    baseline,
    counterfactual_assembly_was_normal,
    do_assembly_normal,
    do_both,
    do_supplier_good,
    observational_supplier_bad,
)

app = typer.Typer(add_completion=False)
console = Console()


async def _run() -> None:
    base = await baseline()
    see_supplier = await observational_supplier_bad()
    intervene_supplier = await do_supplier_good()
    intervene_pressure = await do_assembly_normal()
    intervene_both = await do_both()
    cf = await counterfactual_assembly_was_normal()

    table = Table(title="L2 / L3 — P(ProductDefect = fail) under different queries")
    table.add_column("Query")
    table.add_column("P(fail)", justify="right")
    table.add_column("Δ vs baseline", justify="right")

    def _row(label: str, prob: DefectProbability) -> tuple[str, str, str]:
        delta = prob.p_fail - base.p_fail
        sign = "+" if delta >= 0 else "−"
        return (label, f"{prob.p_fail:.3f}", f"{sign}{abs(delta):.3f}")

    table.add_row(*_row("baseline (marginal)", base))
    table.add_row(*_row("see(SupplierQuality=bad)  [observational]", see_supplier))
    table.add_row(*_row("do(SupplierQuality=good)  [L3]", intervene_supplier))
    table.add_row(*_row("do(AssemblyPressure=normal)  [L3]", intervene_pressure))
    table.add_row(*_row("do(both)                     [L3]", intervene_both))
    table.add_row(*_row("counterfactual: pressure had been normal", cf))

    console.print(table)
    console.print(
        "\n[bold]Reading the table[/]\n"
        "  • The observational `see(SupplierQuality=bad)` row is *correlational* —\n"
        "    L2 alone, not enough to separate supplier from process.\n"
        "  • Compare `do(SupplierQuality=good)` vs `do(AssemblyPressure=normal)`:\n"
        "    if the assembly intervention drops P(fail) more, the process is the\n"
        "    bigger lever — exactly the kind of answer L1 traceability cannot give.\n"
        "  • Counterfactual answers a different question: 'this specific product\n"
        "    failed under low pressure — would it have passed under normal?'\n"
    )


@app.command()
def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_run())


if __name__ == "__main__":
    app()
