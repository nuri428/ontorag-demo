"""SPARQL UPDATE helper for the Stage 5 ABox write-back.

ontorag's stable Python API exposes ``load_rdf`` (bulk) and ``_sparql_select``
(internal). For a single-triple write — which is what ``QuarantineLot``
needs — neither fits cleanly: ``load_rdf`` would force us to re-serialise the
whole dataset, and ``_sparql_select`` only does SELECT.

So we hit Fuseki's ``/update`` endpoint directly with a SPARQL 1.1 Update
statement. This is *semantically* the same thing ``ontorag_flow``'s
``AssertTriple`` action does over MCP, just without the network hop — which
keeps the demo self-contained while still demonstrating the write-back
half of the closed loop (plan §6 row "write-back").
"""

from __future__ import annotations

import os

import httpx

from ontorag.core.ontology import data_graph_uri


def _build_update_url() -> str:
    base = os.environ.get("FUSEKI_URL", "http://localhost:3030").rstrip("/")
    dataset = os.environ.get("FUSEKI_DATASET", "ontorag")
    return f"{base}/{dataset}/update"


async def set_lot_quarantined(
    lot_uri: str,
    *,
    quarantined: bool = True,
    ontology: str | None = None,
) -> str:
    """Replace any existing ``mfg:quarantined`` triple on the lot with a new value.

    Returns the SPARQL UPDATE string that was sent (so the calling action
    can record it in the PROV-O activity for forensic replay).
    """
    graph_uri = data_graph_uri(
        ontology or os.environ.get("DEMO_ONTOLOGY", "manufacturing-demo")
    )
    new_value = "true" if quarantined else "false"
    # DELETE the prior value (whatever it was), then INSERT the new one. The
    # WHERE binds the lot at the same time so a typo in the URI fails loudly.
    update = (
        "PREFIX mfg: <https://ontorag-demo.dev/manufacturing#>\n"
        "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
        f"WITH <{graph_uri}>\n"
        "DELETE { ?lot mfg:quarantined ?old }\n"
        f'INSERT {{ ?lot mfg:quarantined "{new_value}"^^xsd:boolean }}\n'
        "WHERE  {\n"
        f"  BIND(<{lot_uri}> AS ?lot)\n"
        "  OPTIONAL { ?lot mfg:quarantined ?old }\n"
        "}"
    )

    async with httpx.AsyncClient(
        auth=(
            os.environ.get("FUSEKI_USER", "admin"),
            os.environ.get("FUSEKI_PASSWORD", "admin"),
        ),
        timeout=30.0,
    ) as client:
        response = await client.post(_build_update_url(), data={"update": update})
        response.raise_for_status()

    return update
