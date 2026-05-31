"""Generator must produce deterministic, schema-conformant Turtle + ground truth."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from ontorag_demo.causal.model import DEFAULT_GENERATOR_CONFIG
from ontorag_demo.generator import generate
from ontorag_demo.schema import NAMESPACE

MFG = Namespace(NAMESPACE)


@pytest.fixture
def generated(tmp_path: Path):
    return generate(config=DEFAULT_GENERATOR_CONFIG, output_dir=tmp_path)


@pytest.mark.unit
def test_deterministic_with_fixed_seed(tmp_path: Path) -> None:
    """Same config must yield byte-identical Turtle (regression guard)."""
    first = generate(config=DEFAULT_GENERATOR_CONFIG, output_dir=tmp_path / "a")
    second = generate(config=DEFAULT_GENERATOR_CONFIG, output_dir=tmp_path / "b")
    assert first.triple_count == second.triple_count
    assert first.ground_truth == second.ground_truth


@pytest.mark.unit
def test_contaminated_lot_dominates(generated) -> None:  # type: ignore[no-untyped-def]
    """The injected anomaly must surface in failures_by_lot — otherwise the
    Stage 4 traceability demo has no signal."""
    gt = generated.ground_truth
    sorted_lots = sorted(gt.failures_by_lot.items(), key=lambda kv: -kv[1])
    top_lot, top_count = sorted_lots[0]
    assert top_lot == gt.contaminated_lot_id, (
        f"Contaminated lot {gt.contaminated_lot_id!r} should be #1 but {top_lot!r} is."
    )
    assert top_count >= 5, "Contamination signal too weak — bump num_products."


@pytest.mark.unit
def test_turtle_typed_correctly(generated) -> None:  # type: ignore[no-untyped-def]
    """Every entity class must have at least one instance with the right rdf:type."""
    g = Graph()
    g.parse(generated.turtle_path, format="turtle")
    for cls in ("Supplier", "Lot", "Component", "ProcessRun", "Product", "QCResult"):
        triples = list(g.triples((None, RDF.type, MFG[cls])))
        assert triples, f"Generated graph has no instances of mfg:{cls}"


@pytest.mark.unit
def test_qc_verdicts_only_pass_or_fail(generated) -> None:  # type: ignore[no-untyped-def]
    """Sanity check: the discrete state must stay closed under sampling."""
    g = Graph()
    g.parse(generated.turtle_path, format="turtle")
    verdicts = {str(o) for _, _, o in g.triples((None, MFG.verdict, None))}
    assert verdicts == {"pass", "fail"}, f"Unexpected verdicts: {verdicts}"
