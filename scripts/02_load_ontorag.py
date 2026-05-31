"""Stage 4 entry — load schema + instances + BN + causal DAG into ontorag.

Requires Fuseki to be running (``docker compose up -d``). Reads connection
details from environment variables — see ``.env.example``.

Usage::

    uv run python scripts/02_load_ontorag.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import typer
from rich.console import Console

from ontorag.stores.factory import create_store

from ontorag_demo.causal.model import MANUFACTURING_BN, MANUFACTURING_CAUSAL
from ontorag_demo.schema import SCHEMA_PATH

app = typer.Typer(add_completion=False)
console = Console()
logger = logging.getLogger(__name__)


async def _load(schema_path: Path, data_path: Path, ontology: str | None) -> None:
    store = create_store()
    console.print(f"[dim]GRAPH_STORE = {os.environ.get('GRAPH_STORE', 'fuseki')}, "
                  f"ontology scope = {ontology!r}[/dim]\n")

    schema_result = await store.load_rdf(
        path=str(schema_path), mode="schema", ontology=ontology
    )
    console.print(f"  TBox  → {schema_result.triples_loaded} triples ({schema_path})")

    data_result = await store.load_rdf(
        path=str(data_path), mode="data", ontology=ontology
    )
    console.print(f"  ABox  → {data_result.triples_loaded} triples ({data_path})")

    bn_count = await store.put_bayes_network(MANUFACTURING_BN, ontology=ontology)
    console.print(f"  BN    → {bn_count} CPT statements stored")

    causal_count = await store.put_causal_model(MANUFACTURING_CAUSAL, ontology=ontology)
    console.print(f"  Causal → {causal_count} DAG statements stored")


@app.command()
def main(
    schema: Path = typer.Option(
        Path(SCHEMA_PATH),
        "--schema",
        help="Path to the TBox Turtle file (default: packaged manufacturing.ttl).",
    ),
    data: Path = typer.Option(
        Path("data/generated/manufacturing-instances.ttl"),
        "--data",
        help="Path to the ABox Turtle file produced by 01_generate_data.py.",
    ),
    ontology: str | None = typer.Option(
        os.environ.get("DEMO_ONTOLOGY", "manufacturing-demo"),
        "--ontology",
        help="Named-graph scope for the load. None = default schema/data graphs.",
    ),
) -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_load(schema_path=schema, data_path=data, ontology=ontology))


if __name__ == "__main__":
    app()
