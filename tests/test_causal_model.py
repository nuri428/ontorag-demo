"""Smoke + invariant tests for the demo BN/Causal model."""

from __future__ import annotations

import pytest

from ontorag_demo.causal.model import (
    MANUFACTURING_BN,
    MANUFACTURING_CAUSAL,
    NODES,
    NODES_BY_NAME,
)


@pytest.mark.unit
def test_bn_has_one_cpd_per_node() -> None:
    """Every declared node must have exactly one CPD; otherwise pgmpy will reject it."""
    cpd_uris = {cpd.variable for cpd in MANUFACTURING_BN.cpds}
    node_uris = {n.uri for n in NODES}
    assert cpd_uris == node_uris


@pytest.mark.unit
def test_cpd_rows_sum_to_one() -> None:
    """Probabilities must sum to 1.0 down each column of a CPT."""
    for cpd in MANUFACTURING_BN.cpds:
        for col in range(len(cpd.values[0])):
            total = sum(row[col] for row in cpd.values)
            assert total == pytest.approx(1.0, abs=1e-6), (
                f"CPD for {cpd.variable!r} column {col} sums to {total}, not 1.0"
            )


@pytest.mark.unit
def test_causal_dag_matches_bn_parents() -> None:
    """The CausalModel edges must mirror the BN's parent declarations."""
    expected_edges = {
        (NODES_BY_NAME[parent].uri, n.uri)
        for n in NODES
        for parent in n.parents
    }
    actual_edges = set(MANUFACTURING_CAUSAL.edges)
    assert actual_edges == expected_edges


@pytest.mark.unit
def test_product_defect_cpt_interaction() -> None:
    """The (bad, low) joint must produce the highest fail probability."""
    from ontorag_demo.causal.model import _CPDS  # noqa: PLC0415

    target_uri = NODES_BY_NAME["ProductDefect"].uri
    cpd = next(c for c in _CPDS if c.variable == target_uri)
    # row 0 = pass, row 1 = fail; columns ordered (last evidence varies fastest):
    # (good,normal) (good,low) (bad,normal) (bad,low)
    p_fail = cpd.values[1]
    assert p_fail[3] > p_fail[2] > p_fail[1] > p_fail[0], (
        f"Defect probability must monotonically increase with worse conditions; got {p_fail}"
    )
