"""Serialise sampled entities to RDF/Turtle that ontorag can ingest as ABox."""

from __future__ import annotations

from collections.abc import Iterable

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from ontorag_demo.generator.entities import (
    ComponentInstance,
    LotInstance,
    ProcessRunInstance,
    ProductInstance,
    QCResultInstance,
    SupplierInstance,
)
from ontorag_demo.schema import NAMESPACE

MFG = Namespace(NAMESPACE)


def build_graph(
    suppliers: Iterable[SupplierInstance],
    lots: Iterable[LotInstance],
    components: Iterable[ComponentInstance],
    process_runs: Iterable[ProcessRunInstance],
    products: Iterable[ProductInstance],
    qc_results: Iterable[QCResultInstance],
) -> Graph:
    """Build an rdflib graph mirroring the schema's domains/ranges."""
    g = Graph()
    g.bind("mfg", MFG)

    for s in suppliers:
        u = URIRef(s.uri)
        g.add((u, RDF.type, MFG.Supplier))
        g.add((u, MFG.supplierId, Literal(s.supplier_id, datatype=XSD.string)))

    for lot in lots:
        u = URIRef(lot.uri)
        g.add((u, RDF.type, MFG.Lot))
        g.add((u, MFG.lotId, Literal(lot.lot_id, datatype=XSD.string)))
        g.add((URIRef(lot.supplier_uri), MFG.supplies, u))
        # quarantined defaults to False; the ontorag-flow demo flips it.
        g.add((u, MFG.quarantined, Literal(False, datatype=XSD.boolean)))

    for c in components:
        u = URIRef(c.uri)
        g.add((u, RDF.type, MFG.Component))
        g.add((u, MFG.componentId, Literal(c.component_id, datatype=XSD.string)))
        g.add((URIRef(c.lot_uri), MFG.hasComponent, u))

    for run in process_runs:
        u = URIRef(run.uri)
        g.add((u, RDF.type, MFG.ProcessRun))
        g.add((URIRef(run.component_uri), MFG.processedBy, u))
        g.add((u, MFG.atStep, URIRef(run.step_uri)))
        g.add((u, MFG.condition, Literal(run.condition, datatype=XSD.string)))

    for product in products:
        u = URIRef(product.uri)
        g.add((u, RDF.type, MFG.Product))
        g.add((u, MFG.productId, Literal(product.product_id, datatype=XSD.string)))
        for run_uri in product.process_run_uris:
            g.add((URIRef(run_uri), MFG.produces, u))

    for qc in qc_results:
        u = URIRef(qc.uri)
        g.add((u, RDF.type, MFG.QCResult))
        g.add((URIRef(qc.product_uri), MFG.hasQC, u))
        g.add((u, MFG.verdict, Literal(qc.verdict, datatype=XSD.string)))

    return g


def serialise(graph: Graph, output_path) -> int:
    """Write the graph to ``output_path`` as Turtle. Returns triple count."""
    graph.serialize(destination=output_path, format="turtle")
    return len(graph)
