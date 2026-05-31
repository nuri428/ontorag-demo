"""Sample synthetic supply-chain instances from the demo's BN.

Why hand-write the sampler instead of letting pgmpy do forward sampling?

* We need per-lot / per-supplier *anomaly injection* that the aggregate BN
  doesn't express directly (supplier B's elevated bad-quality rate, lot
  #47's deliberate contamination). Plan §3 calls this "noise injection
  to avoid tautology".
* We need to record latent variables (`supplier_quality`, `lot_quality`,
  `component_quality`) for the ground-truth answer key — pgmpy's sampler
  would only return what we ask for and would not preserve the per-entity
  attribution we need for verification.

The sampler still respects the BN's CPDs exactly: every conditional draw
uses the same probabilities encoded in ``causal.model._CPDS``, so the
generative process matches the model ontorag is asked to reason about
(plan §3 "same model generates and infers — ground truth is self-evident").
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from ontorag_demo.causal.model import (
    DEFAULT_GENERATOR_CONFIG,
    NODES_BY_NAME,
    SUPPLIER_PROFILES,
    GeneratorConfig,
)
from ontorag_demo.generator.entities import (
    ComponentInstance,
    GroundTruth,
    LotInstance,
    ProcessRunInstance,
    ProductInstance,
    QCResultInstance,
    SupplierInstance,
)
from ontorag_demo.schema import NAMESPACE

# ---------------------------------------------------------------------------
# Probability lookups — extracted from `causal.model` so the sampler and the
# BN consume the same numbers. If `_CPDS` changes, these stay in sync because
# they re-derive from `NODES_BY_NAME` (which is the same source).
# ---------------------------------------------------------------------------

from ontorag_demo.causal.model import _CPDS  # noqa: E402 — internal re-use


def _state_index(node_name: str, state: str) -> int:
    return list(NODES_BY_NAME[node_name].states).index(state)


def _cpd_for(node_name: str):
    target_uri = NODES_BY_NAME[node_name].uri
    for cpd in _CPDS:
        if cpd.variable == target_uri:
            return cpd
    raise KeyError(f"No CPD for {node_name!r}")  # pragma: no cover


def _conditional_prob(node_name: str, state: str, parent_assignment: tuple[str, ...]) -> float:
    """P(node = state | parents = assignment) from the BN's CPT.

    ``parent_assignment`` is a tuple of states in the same order as the CPD's
    ``evidence`` list (which mirrors ``NodeSpec.parents``).
    """
    cpd = _cpd_for(node_name)
    node = NODES_BY_NAME[node_name]
    parent_specs = [NODES_BY_NAME[p] for p in node.parents]
    # Compute the flat column index using pgmpy's "last evidence varies fastest" rule.
    col = 0
    for spec, parent_state in zip(parent_specs, parent_assignment, strict=True):
        col = col * len(spec.states) + list(spec.states).index(parent_state)
    row = _state_index(node_name, state)
    return cpd.values[row][col]


def _sample_binary(rng: random.Random, node_name: str, parent_assignment: tuple[str, ...]) -> str:
    """Draw a state for a binary node given its parents' assignment."""
    states = NODES_BY_NAME[node_name].states
    p_first = _conditional_prob(node_name, states[0], parent_assignment)
    return states[0] if rng.random() < p_first else states[1]


# ---------------------------------------------------------------------------
# Public sampler
# ---------------------------------------------------------------------------


def _supplier_uri(supplier_id: str) -> str:
    return f"{NAMESPACE}supplier/{supplier_id}"


def _lot_uri(index: int) -> str:
    return f"{NAMESPACE}lot/LOT-{index:04d}"


def _component_uri(index: int) -> str:
    return f"{NAMESPACE}component/CMP-{index:05d}"


def _process_run_uri(component_index: int, step_key: str) -> str:
    return f"{NAMESPACE}run/CMP-{component_index:05d}-{step_key}"


def _product_uri(index: int) -> str:
    return f"{NAMESPACE}product/PRD-{index:05d}"


def _qc_uri(product_index: int) -> str:
    return f"{NAMESPACE}qc/PRD-{product_index:05d}"


_STEP_URIS = {
    "machining": f"{NAMESPACE}StepMachining",
    "assembly": f"{NAMESPACE}StepAssembly",
    "inspection": f"{NAMESPACE}StepInspection",
}


def _step_condition_node(step_key: str) -> str:
    """The BN node whose state we record on the ProcessRun for this step."""
    return {
        "machining": "MachiningTemperature",
        "assembly": "AssemblyPressure",
        "inspection": "InspectionMoisture",
    }[step_key]


def _attribute_failure(
    component_quality: str,
    assembly_pressure: str,
    lot_is_contaminated: bool,
    supplier_is_suspect: bool,
) -> str:
    """Heuristic 'dominant cause' tag for the ground-truth answer key.

    The BN itself doesn't expose a single cause per failure (the CPT mixes
    them probabilistically), but for the demo's didactic purposes we record
    the most parsimonious explanation the sampler observed. This is *not*
    used by ontorag — only by Stage 4's verification report.
    """
    if assembly_pressure == "low" and component_quality == "good":
        return "process_only"
    if assembly_pressure == "normal" and component_quality == "bad":
        if lot_is_contaminated:
            return "contaminated_lot"
        return "supplier_chain" if supplier_is_suspect else "random_component"
    if assembly_pressure == "low" and component_quality == "bad":
        return "interaction"
    return "random_noise"


def sample(config: GeneratorConfig = DEFAULT_GENERATOR_CONFIG) -> tuple[
    list[SupplierInstance],
    list[LotInstance],
    list[ComponentInstance],
    list[ProcessRunInstance],
    list[ProductInstance],
    list[QCResultInstance],
    GroundTruth,
]:
    """Draw a full instance graph from the BN with anomaly injection.

    Returns six instance lists (in the order the RDF writer needs them) plus
    a ``GroundTruth`` answer key.
    """
    rng = random.Random(config.random_seed)

    # ----- Suppliers -----------------------------------------------------
    profiles = SUPPLIER_PROFILES[: config.num_suppliers]
    suppliers: list[SupplierInstance] = [
        SupplierInstance(
            uri=_supplier_uri(p.supplier_id),
            supplier_id=p.supplier_id,
            is_suspect=p.is_suspect,
        )
        for p in profiles
    ]
    supplier_by_uri = {s.uri: s for s in suppliers}

    # ----- Lots ----------------------------------------------------------
    lots: list[LotInstance] = []
    for i in range(1, config.num_lots + 1):
        profile = profiles[(i - 1) % len(profiles)]
        # SupplierQuality is sampled with per-supplier bias (anomaly layer
        # on top of the BN's averaged P(bad)=0.25).
        supplier_quality = "bad" if rng.random() < profile.bad_quality_rate else "good"
        # LotQuality is conditional on supplier quality — pulled straight from
        # the BN's CPT so the data matches the inference model.
        is_contaminated = i == config.contaminated_lot_index
        if is_contaminated:
            lot_quality = "bad" if rng.random() < config.contaminated_bad_rate else "good"
        else:
            lot_quality = _sample_binary(rng, "LotQuality", (supplier_quality,))
        lots.append(
            LotInstance(
                uri=_lot_uri(i),
                lot_id=f"LOT-{i:04d}",
                supplier_uri=_supplier_uri(profile.supplier_id),
                supplier_quality=supplier_quality,
                lot_quality=lot_quality,
                is_contaminated=is_contaminated,
            )
        )

    # ----- Products + intermediate entities -----------------------------
    # Each product gets a freshly drawn component (so component count =
    # product count); the component's lot is chosen round-robin to keep the
    # supplier mix balanced.
    components: list[ComponentInstance] = []
    process_runs: list[ProcessRunInstance] = []
    products: list[ProductInstance] = []
    qc_results: list[QCResultInstance] = []

    failures_by_cause: dict[str, list[str]] = defaultdict(list)
    failures_by_supplier: Counter[str] = Counter()
    failures_by_lot: Counter[str] = Counter()

    for k in range(1, config.num_products + 1):
        lot = lots[(k - 1) % len(lots)]
        component_quality = _sample_binary(rng, "ComponentQuality", (lot.lot_quality,))
        comp = ComponentInstance(
            uri=_component_uri(k),
            component_id=f"CMP-{k:05d}",
            lot_uri=lot.uri,
            component_quality=component_quality,
        )
        components.append(comp)

        # Three process runs per component. Conditions are drawn from each
        # step's marginal CPD; only AssemblyPressure feeds back into the
        # defect calculation per the BN structure.
        step_conditions: dict[str, str] = {}
        for step_key, step_uri in _STEP_URIS.items():
            cond_node = _step_condition_node(step_key)
            condition = _sample_binary(rng, cond_node, ())
            step_conditions[step_key] = condition
            process_runs.append(
                ProcessRunInstance(
                    uri=_process_run_uri(k, step_key),
                    component_uri=comp.uri,
                    step_uri=step_uri,
                    condition=condition,
                )
            )

        product = ProductInstance(
            uri=_product_uri(k),
            product_id=f"PRD-{k:05d}",
            process_run_uris=tuple(
                _process_run_uri(k, step_key) for step_key in _STEP_URIS
            ),
        )
        products.append(product)

        # Defect verdict via the BN's CPT.
        verdict_state = _sample_binary(
            rng,
            "ProductDefect",
            (component_quality, step_conditions["assembly"]),
        )
        qc_results.append(
            QCResultInstance(
                uri=_qc_uri(k),
                product_uri=product.uri,
                verdict=verdict_state,
            )
        )

        if verdict_state == "fail":
            cause = _attribute_failure(
                component_quality=component_quality,
                assembly_pressure=step_conditions["assembly"],
                lot_is_contaminated=lot.is_contaminated,
                supplier_is_suspect=supplier_by_uri[lot.supplier_uri].is_suspect,
            )
            failures_by_cause[cause].append(product.product_id)
            failures_by_supplier[supplier_by_uri[lot.supplier_uri].supplier_id] += 1
            failures_by_lot[lot.lot_id] += 1

    ground_truth = GroundTruth(
        suspect_supplier_id=next(p.supplier_id for p in profiles if p.is_suspect),
        contaminated_lot_id=f"LOT-{config.contaminated_lot_index:04d}",
        causal_process_step_uri=_STEP_URIS["assembly"],
        failures_by_cause=dict(failures_by_cause),
        failures_by_supplier=dict(failures_by_supplier),
        failures_by_lot=dict(failures_by_lot),
        total_products=len(products),
        total_failures=sum(1 for q in qc_results if q.verdict == "fail"),
    )

    return suppliers, lots, components, process_runs, products, qc_results, ground_truth
