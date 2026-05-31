"""Stage 4 — multi-hop traceability queries against an ontorag graph store.

Every query is written in SPARQL even though ontorag has higher-level L1
helpers; the demo's pedagogical point is that the schema in Stage 1 was
designed precisely so this multi-hop walk works directly. Using
``query_pattern`` would hide that structure.

The queries are async because ontorag's store APIs are async — the runner
scripts wrap them in ``asyncio.run``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ontorag.stores.base import GraphStore

from ontorag_demo.schema import NAMESPACE

# Shared SPARQL prefix block so each query stays focused on its WHERE.
_PREFIXES = f"""
PREFIX mfg:  <{NAMESPACE}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""


@dataclass(frozen=True)
class LotFailureCount:
    lot_id: str
    failure_count: int


@dataclass(frozen=True)
class SupplierFailureCount:
    supplier_id: str
    failure_count: int


async def failures_per_lot(
    store: GraphStore, limit: int = 10
) -> list[LotFailureCount]:
    """Trace every failed product back to its source lot and rank by count.

    The walk follows the schema's relations strictly:

        QCResult ← Product ← ProcessRun ← Component ← Lot

    so a multi-hop SPARQL JOIN is the natural expression. The "produces"
    relation goes ProcessRun → Product, hence the patterns read backwards
    from the failure side.
    """
    sparql = _PREFIXES + """
        SELECT ?lotId (COUNT(DISTINCT ?product) AS ?failures) WHERE {
            ?product mfg:hasQC ?qc .
            ?qc      mfg:verdict "fail" .
            ?run     mfg:produces ?product .
            ?component mfg:processedBy ?run .
            ?lot     mfg:hasComponent ?component .
            ?lot     mfg:lotId ?lotId .
        }
        GROUP BY ?lotId
        ORDER BY DESC(?failures)
    """ + f"LIMIT {int(limit)}\n"

    result = await store._sparql_select(sparql)  # noqa: SLF001
    rows = _iter_rows(result)
    return [
        LotFailureCount(lot_id=row["lotId"], failure_count=int(row["failures"]))
        for row in rows
    ]


async def failures_per_supplier(
    store: GraphStore,
) -> list[SupplierFailureCount]:
    """Continue the chain one hop further: Lot ← Supplier."""
    sparql = _PREFIXES + """
        SELECT ?supplierId (COUNT(DISTINCT ?product) AS ?failures) WHERE {
            ?product mfg:hasQC ?qc .
            ?qc      mfg:verdict "fail" .
            ?run     mfg:produces ?product .
            ?component mfg:processedBy ?run .
            ?lot     mfg:hasComponent ?component .
            ?supplier mfg:supplies ?lot .
            ?supplier mfg:supplierId ?supplierId .
        }
        GROUP BY ?supplierId
        ORDER BY DESC(?failures)
    """

    result = await store._sparql_select(sparql)  # noqa: SLF001
    rows = _iter_rows(result)
    return [
        SupplierFailureCount(
            supplier_id=row["supplierId"], failure_count=int(row["failures"])
        )
        for row in rows
    ]


async def failures_per_assembly_condition(store: GraphStore) -> dict[str, int]:
    """Count failures grouped by the assembly-step condition.

    This is the SPARQL-side analog of the L3 question: at the *correlative*
    level, what does the data say about assembly pressure? A real ops team
    would run this *first*; ontorag's L3 layer then justifies whether the
    correlation reflects causation.
    """
    sparql = _PREFIXES + """
        SELECT ?condition (COUNT(DISTINCT ?product) AS ?failures) WHERE {
            ?product mfg:hasQC ?qc .
            ?qc      mfg:verdict "fail" .
            ?run     mfg:produces ?product .
            ?run     mfg:atStep mfg:StepAssembly .
            ?run     mfg:condition ?condition .
        }
        GROUP BY ?condition
        ORDER BY DESC(?failures)
    """

    result = await store._sparql_select(sparql)  # noqa: SLF001
    rows = _iter_rows(result)
    return {row["condition"]: int(row["failures"]) for row in rows}


async def products_from_lot(store: GraphStore, lot_id: str) -> list[str]:
    """All product IDs traceable to a given lot — verifies the inverse path."""
    sparql = _PREFIXES + f"""
        SELECT DISTINCT ?productId WHERE {{
            ?lot mfg:lotId "{lot_id}" .
            ?lot mfg:hasComponent ?component .
            ?component mfg:processedBy ?run .
            ?run mfg:produces ?product .
            ?product mfg:productId ?productId .
        }}
        ORDER BY ?productId
    """

    result = await store._sparql_select(sparql)  # noqa: SLF001
    return [row["productId"] for row in _iter_rows(result)]


def _iter_rows(result: dict) -> list[dict[str, str]]:
    """Normalise ontorag's SPARQL-JSON-shaped result to plain ``[{var: value}]``.

    Fuseki's ``_sparql_select`` returns the SPARQL 1.1 JSON results format:
    ``{"head": {"vars": [...]}, "results": {"bindings": [{var: {value, ...}}, ...]}}``.
    """
    bindings = result.get("results", {}).get("bindings", [])
    return [
        {var: binding[var]["value"] for var in binding}
        for binding in bindings
    ]
