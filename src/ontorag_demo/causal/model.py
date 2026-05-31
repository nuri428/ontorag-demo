"""Bayesian network + causal DAG definitions for the manufacturing demo.

Plan §3 spec (one causal interaction, two independent process noise
conditions) realised as a 7-node DAG:

    SupplierQuality   → LotQuality → ComponentQuality ─┐
                                                       ├→ ProductDefect
                          AssemblyPressure ────────────┘
    MachiningTemperature  (process noise — independent)
    InspectionMoisture    (process noise — independent)

The two "noise" process conditions are kept in the BN so reasoning queries
have to *discover* that only AssemblyPressure matters; otherwise the demo
would smuggle in its own answer.

URIs are stable across runs so ontorag's named-graph storage
(`urn:ontorag:probabilistic`, `urn:ontorag:causal`) can round-trip them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ontorag.core.bayes import CPD, BayesNetwork, BayesVariable
from ontorag.core.causal import CausalModel, CausalVariable

from ontorag_demo.schema import NAMESPACE

BN_URI = f"{NAMESPACE}bn:manufacturing"
"""Stable URI for the BayesNetwork instance (round-trips through ontorag)."""

CAUSAL_URI = f"{NAMESPACE}causal:manufacturing"
"""Stable URI for the CausalModel instance."""


def _v(name: str) -> str:
    """Compose a deterministic variable URI under the demo namespace."""
    return f"{NAMESPACE}{name}"


@dataclass(frozen=True)
class NodeSpec:
    """Per-node metadata shared between BN construction and the sampler."""

    name: str
    states: tuple[str, ...]
    parents: tuple[str, ...] = ()

    @property
    def uri(self) -> str:
        return _v(self.name)


NODES: tuple[NodeSpec, ...] = (
    NodeSpec("SupplierQuality", ("good", "bad")),
    NodeSpec("LotQuality", ("good", "bad"), parents=("SupplierQuality",)),
    NodeSpec("ComponentQuality", ("good", "bad"), parents=("LotQuality",)),
    NodeSpec("MachiningTemperature", ("normal", "high")),
    NodeSpec("AssemblyPressure", ("normal", "low")),
    NodeSpec("InspectionMoisture", ("normal", "high")),
    NodeSpec(
        "ProductDefect",
        ("pass", "fail"),
        parents=("ComponentQuality", "AssemblyPressure"),
    ),
)
"""Single source of truth for both the BN spec and the synthetic sampler."""

NODES_BY_NAME: dict[str, NodeSpec] = {n.name: n for n in NODES}


# ---------------------------------------------------------------------------
# CPT values
# ---------------------------------------------------------------------------
#
# The ontorag `CPD.values` layout follows pgmpy: one row per state of the
# variable, one column per joint-evidence assignment ordered with the LAST
# evidence varying fastest. The helpers below build the matrix from a flat
# {evidence-tuple -> P(state_0)} dict so the numbers stay readable.


def _binary_cpd(
    variable: str,
    evidence: tuple[str, ...],
    p_state0: dict[tuple[str, ...], float],
) -> CPD:
    """Build a 2-state CPD where ``p_state0`` gives P(state[0] | parents).

    The complementary P(state[1]) is filled in automatically so callers only
    have to specify half the table.
    """
    spec = NODES_BY_NAME[variable]
    assert len(spec.states) == 2, f"{variable} must be binary"
    if evidence:
        # Build columns in pgmpy's canonical order (last evidence varies fastest).
        parent_specs = [NODES_BY_NAME[p] for p in evidence]
        columns: list[tuple[str, ...]] = [()]
        for parent in parent_specs:
            columns = [c + (s,) for c in columns for s in parent.states]
        row0 = [p_state0[col] for col in columns]
    else:
        row0 = [p_state0[()]]
    row1 = [round(1.0 - v, 6) for v in row0]
    return CPD(
        variable=spec.uri,
        evidence=[NODES_BY_NAME[p].uri for p in evidence],
        values=[row0, row1],
    )


_CPDS: tuple[CPD, ...] = (
    _binary_cpd("SupplierQuality", (), {(): 0.75}),
    _binary_cpd(
        "LotQuality",
        ("SupplierQuality",),
        {
            ("good",): 0.95,
            ("bad",): 0.30,
        },
    ),
    _binary_cpd(
        "ComponentQuality",
        ("LotQuality",),
        {
            ("good",): 0.95,
            ("bad",): 0.10,
        },
    ),
    _binary_cpd("MachiningTemperature", (), {(): 0.70}),
    _binary_cpd("AssemblyPressure", (), {(): 0.60}),
    _binary_cpd("InspectionMoisture", (), {(): 0.80}),
    _binary_cpd(
        "ProductDefect",
        ("ComponentQuality", "AssemblyPressure"),
        # P(pass | parents). Reading column-wise:
        #   (good,normal)=.98  (good,low)=.65   strong process effect on good parts
        #   (bad, normal)=.50  (bad, low)=.15   interaction amplifies failures
        {
            ("good", "normal"): 0.98,
            ("good", "low"): 0.65,
            ("bad", "normal"): 0.50,
            ("bad", "low"): 0.15,
        },
    ),
)


def _build_bn() -> BayesNetwork:
    variables = [
        BayesVariable(uri=n.uri, label=n.name, states=list(n.states)) for n in NODES
    ]
    return BayesNetwork(variables=variables, cpds=list(_CPDS), name="manufacturing")


def _build_causal() -> CausalModel:
    variables = [
        CausalVariable(uri=n.uri, label=n.name, observed=True) for n in NODES
    ]
    edges = [
        (NODES_BY_NAME[parent].uri, n.uri)
        for n in NODES
        for parent in n.parents
    ]
    return CausalModel(
        variables=variables,
        edges=edges,
        based_on=BN_URI,
        name="manufacturing",
    )


MANUFACTURING_BN: BayesNetwork = _build_bn()
"""Quantified Bayesian network — passed to `BayesianEngine`."""

MANUFACTURING_CAUSAL: CausalModel = _build_causal()
"""DAG passed to `CausalEngine`. Same edges as BN parents, all observed."""


@dataclass(frozen=True)
class SupplierProfile:
    """Per-supplier multiplier on `SupplierQuality=bad` for data generation."""

    supplier_id: str
    bad_quality_rate: float
    is_suspect: bool = False


SUPPLIER_PROFILES: tuple[SupplierProfile, ...] = (
    SupplierProfile("SUP-A", 0.10),
    # SUP-B is the "smuggled-in" bad supplier — higher base rate but not 100%
    # so the demo doesn't trivially solve via supplier filter alone (plan §3).
    SupplierProfile("SUP-B", 0.55, is_suspect=True),
    SupplierProfile("SUP-C", 0.15),
    SupplierProfile("SUP-D", 0.12),
    SupplierProfile("SUP-E", 0.18),
)


@dataclass(frozen=True)
class GeneratorConfig:
    """Demo-scale config. Plan §4 set 300 products as the *initial* sample —
    bumped here to 600 so 12 products per lot makes the contaminated-lot
    anomaly statistically visible (5+ failures) without being trivially
    obvious from supplier-level aggregation."""

    num_suppliers: int = 5
    num_lots: int = 50
    num_products: int = 600
    # Lot-level injected anomaly: a specific lot is contaminated regardless of
    # which supplier delivered it. Stage 4/5 must surface this as the proximate
    # cause even though the supplier may be "good" on average.
    contaminated_lot_index: int = 47
    contaminated_bad_rate: float = 1.0
    random_seed: int = 20260601


DEFAULT_GENERATOR_CONFIG = GeneratorConfig()
