"""Engines should reproduce the plan §1 'L3 reveals process > supplier' claim."""

from __future__ import annotations

import pytest

from ontorag_demo.verify.causal import (
    baseline,
    do_assembly_normal,
    do_both,
    do_supplier_good,
)


@pytest.mark.unit
async def test_baseline_matches_expected_marginal() -> None:
    """The marginal must hover near the data-generator's observed defect rate (~25%)."""
    b = await baseline()
    assert 0.20 < b.p_fail < 0.32


@pytest.mark.unit
async def test_assembly_intervention_helps_more_than_supplier_only() -> None:
    """Plan §1 narrative claim — verified at the engine level."""
    sup = await do_supplier_good()
    pres = await do_assembly_normal()
    assert pres.p_fail < sup.p_fail, (
        f"Expected do(pressure=normal) to outperform do(supplier=good), "
        f"got {pres.p_fail=:.3f} vs {sup.p_fail=:.3f}"
    )


@pytest.mark.unit
async def test_joint_intervention_strictly_better() -> None:
    """Intervening on both should never be worse than either alone."""
    sup = await do_supplier_good()
    pres = await do_assembly_normal()
    both = await do_both()
    assert both.p_fail < min(sup.p_fail, pres.p_fail)
