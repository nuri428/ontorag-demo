"""L2 (posterior) + L3 (do / counterfactual) queries against the demo BN.

Uses ontorag's engines directly on the in-memory ``MANUFACTURING_BN`` and
``MANUFACTURING_CAUSAL`` — no graph store needed, so this layer can be
exercised in CI without Fuseki running.
"""

from __future__ import annotations

from dataclasses import dataclass

from ontorag.bayes.engine import BayesianEngine
from ontorag.causal.engine import CausalEngine

from ontorag_demo.causal.model import (
    MANUFACTURING_BN,
    MANUFACTURING_CAUSAL,
    NODES_BY_NAME,
)


@dataclass(frozen=True)
class DefectProbability:
    """Convenience wrapper holding both the full distribution and ``P(fail)``."""

    label: str
    distribution: dict[str, float]

    @property
    def p_fail(self) -> float:
        return self.distribution.get("fail", 0.0)


def _engines() -> tuple[BayesianEngine, CausalEngine]:
    """Build the engine pair once; engines are stateless wrappers."""
    bn_engine = BayesianEngine(MANUFACTURING_BN)
    causal_engine = CausalEngine(MANUFACTURING_BN, MANUFACTURING_CAUSAL)
    return bn_engine, causal_engine


def _defect_uri() -> str:
    return NODES_BY_NAME["ProductDefect"].uri


def _to_label_dict(raw: dict[str, float]) -> dict[str, float]:
    """Engines may return URIs as keys; remap them to short labels for display."""
    return raw


async def baseline(bn_engine: BayesianEngine | None = None) -> DefectProbability:
    """Marginal P(ProductDefect) under no evidence."""
    engine = bn_engine or _engines()[0]
    raw = await engine.compute_posterior(evidence={}, query=[_defect_uri()])
    dist = _to_label_dict(raw[_defect_uri()])
    return DefectProbability(label="baseline", distribution=dist)


async def observational_supplier_bad(
    bn_engine: BayesianEngine | None = None,
) -> DefectProbability:
    """P(ProductDefect | SupplierQuality=bad) — the L2 "we noticed SUP-B" view."""
    engine = bn_engine or _engines()[0]
    raw = await engine.compute_posterior(
        evidence={NODES_BY_NAME["SupplierQuality"].uri: "bad"},
        query=[_defect_uri()],
    )
    dist = _to_label_dict(raw[_defect_uri()])
    return DefectProbability(label="see(SupplierQuality=bad)", distribution=dist)


async def do_supplier_good(
    causal_engine: CausalEngine | None = None,
) -> DefectProbability:
    """P(ProductDefect | do(SupplierQuality=good)) — quarantine all bad suppliers."""
    engine = causal_engine or _engines()[1]
    raw = await engine.do_query(
        do={NODES_BY_NAME["SupplierQuality"].uri: "good"},
        query=[_defect_uri()],
        evidence={},
    )
    dist = _to_label_dict(raw[_defect_uri()])
    return DefectProbability(label="do(SupplierQuality=good)", distribution=dist)


async def do_assembly_normal(
    causal_engine: CausalEngine | None = None,
) -> DefectProbability:
    """P(ProductDefect | do(AssemblyPressure=normal)) — fix the assembly process."""
    engine = causal_engine or _engines()[1]
    raw = await engine.do_query(
        do={NODES_BY_NAME["AssemblyPressure"].uri: "normal"},
        query=[_defect_uri()],
        evidence={},
    )
    dist = _to_label_dict(raw[_defect_uri()])
    return DefectProbability(label="do(AssemblyPressure=normal)", distribution=dist)


async def do_both(
    causal_engine: CausalEngine | None = None,
) -> DefectProbability:
    """P(ProductDefect | do(SupplierQuality=good, AssemblyPressure=normal))."""
    engine = causal_engine or _engines()[1]
    raw = await engine.do_query(
        do={
            NODES_BY_NAME["SupplierQuality"].uri: "good",
            NODES_BY_NAME["AssemblyPressure"].uri: "normal",
        },
        query=[_defect_uri()],
        evidence={},
    )
    dist = _to_label_dict(raw[_defect_uri()])
    return DefectProbability(label="do(Supplier=good, Pressure=normal)", distribution=dist)


async def counterfactual_assembly_was_normal(
    causal_engine: CausalEngine | None = None,
) -> DefectProbability:
    """Given a product *that failed under low pressure*, P(pass) had pressure been normal.

    Pearl Rung 3: abduction (infer latent noise from the observation) →
    action (set AssemblyPressure=normal) → prediction. ontorag's
    ``counterfactual`` does this via the canonical independent-noise SCM.
    """
    engine = causal_engine or _engines()[1]
    raw = await engine.counterfactual(
        observed={
            NODES_BY_NAME["AssemblyPressure"].uri: "low",
            _defect_uri(): "fail",
        },
        intervention={NODES_BY_NAME["AssemblyPressure"].uri: "normal"},
        query=[_defect_uri()],
    )
    dist = _to_label_dict(raw[_defect_uri()])
    return DefectProbability(
        label="counterfactual: pressure had been normal", distribution=dist
    )
