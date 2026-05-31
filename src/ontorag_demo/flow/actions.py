"""Domain actions for the manufacturing-RCA flow.

Five actions, each anchored in one of the Stage 4 capabilities:

1. ``PinpointSuspectLot``       — L1 SPARQL traceability
2. ``EvaluateIntervention``     — L3 do_query scoring
3. ``RequestQuarantineApproval``— HUMAN handoff (auto-suspends the case)
4. ``QuarantineLot``            — ABox write-back via SPARQL UPDATE
5. ``CounterfactualReplay``     — L3 counterfactual closure ("had we NOT quarantined?")

Each action requires the ontorag :class:`~ontorag.stores.base.GraphStore` and
the in-memory BN/Causal engines, so they're constructed by
``build_domain_actions(store)`` and registered into the
``ontorag_flow`` registry at the composition root (``runner.py``).
"""

from __future__ import annotations

from typing import Any, ClassVar

from ontorag.bayes.engine import BayesianEngine
from ontorag.causal.engine import CausalEngine
from ontorag.stores.base import GraphStore
from ontorag_flow.core.action import ActionResult, BaseAction, SideEffectKind
from ontorag_flow.core.state import CaseState
from pydantic import BaseModel, Field

from ontorag_demo.causal.model import (
    MANUFACTURING_BN,
    MANUFACTURING_CAUSAL,
    NODES_BY_NAME,
)
from ontorag_demo.flow.writeback import set_lot_quarantined
from ontorag_demo.verify.causal import (
    baseline,
    do_assembly_normal,
    do_both,
    do_supplier_good,
)
from ontorag_demo.verify.trace import failures_per_lot

# ---------------------------------------------------------------------------
# Action 1 — PinpointSuspectLot
# ---------------------------------------------------------------------------


class _PinpointParams(BaseModel):
    top_n: int = Field(default=3, ge=1, le=20)


class PinpointSuspectLot(BaseAction):
    """Run L1 traceability and propose the most defect-laden lot."""

    uri: ClassVar[str] = "urn:demo:manufacturing:PinpointSuspectLot"
    name: ClassVar[str] = "Pinpoint suspect lot"
    description: ClassVar[str] = (
        "Run the L1 SPARQL traceability query and propose the lot with the "
        "highest distinct failed-product count."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.CASE_STATE}
    )
    input_schema: ClassVar[type[BaseModel]] = _PinpointParams

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    async def execute(self, params: _PinpointParams, state: CaseState) -> ActionResult:  # type: ignore[override]
        ranked = await failures_per_lot(self._store, limit=params.top_n)
        if not ranked:
            return ActionResult(
                action_uri=self.uri,
                success=False,
                error="No failed products found — the case should not have been opened.",
            )
        top = ranked[0]
        return ActionResult(
            action_uri=self.uri,
            outputs={
                "top_lot_id": top.lot_id,
                "top_lot_failures": top.failure_count,
                "ranking": [
                    {"lot_id": r.lot_id, "failures": r.failure_count} for r in ranked
                ],
            },
            state_changes={
                "suspect_lot_id": top.lot_id,
                "suspect_lot_failures": top.failure_count,
                "suspect_lot_known": True,
            },
        )


# ---------------------------------------------------------------------------
# Action 2 — EvaluateIntervention
# ---------------------------------------------------------------------------


class _EvalParams(BaseModel):
    # No external params — every intervention is scored in fixed comparison.
    pass


class EvaluateIntervention(BaseAction):
    """Compare three causal interventions against the baseline and rank them.

    Reuses ``verify.causal`` so the numbers here match the standalone
    Stage 4 script exactly — no engine duplication.
    """

    uri: ClassVar[str] = "urn:demo:manufacturing:EvaluateIntervention"
    name: ClassVar[str] = "Evaluate causal intervention"
    description: ClassVar[str] = (
        "Run do(SupplierQuality=good), do(AssemblyPressure=normal), and "
        "do(both) against the demo BN; recommend the intervention with the "
        "largest expected drop in defect probability."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.CASE_STATE}
    )
    input_schema: ClassVar[type[BaseModel]] = _EvalParams

    def __init__(self) -> None:
        self._bn_engine = BayesianEngine(MANUFACTURING_BN)
        self._causal_engine = CausalEngine(MANUFACTURING_BN, MANUFACTURING_CAUSAL)

    async def execute(self, params: _EvalParams, state: CaseState) -> ActionResult:  # type: ignore[override]
        base = await baseline(self._bn_engine)
        sup = await do_supplier_good(self._causal_engine)
        pres = await do_assembly_normal(self._causal_engine)
        both = await do_both(self._causal_engine)

        candidates = {
            "supplier_only": sup.p_fail,
            "process_only": pres.p_fail,
            "supplier_and_process": both.p_fail,
        }
        # Recommend the intervention with the lowest expected defect rate.
        best_label = min(candidates, key=lambda k: candidates[k])

        return ActionResult(
            action_uri=self.uri,
            outputs={
                "baseline_p_fail": base.p_fail,
                "intervention_p_fail": candidates,
                "recommended_intervention": best_label,
            },
            state_changes={
                "baseline_p_fail": round(base.p_fail, 4),
                "intervention_p_fail": {k: round(v, 4) for k, v in candidates.items()},
                "recommended_intervention": best_label,
                "causal_evaluation_done": True,
            },
        )


# ---------------------------------------------------------------------------
# Action 3 — RequestQuarantineApproval (HUMAN — auto-suspends)
# ---------------------------------------------------------------------------


class _ApprovalParams(BaseModel):
    reason: str


class RequestQuarantineApproval(BaseAction):
    """Open the human-approval gate. The case auto-suspends until ``resume``."""

    uri: ClassVar[str] = "urn:demo:manufacturing:RequestQuarantineApproval"
    name: ClassVar[str] = "Request quarantine approval"
    description: ClassVar[str] = (
        "Pause the case for operator review before any ABox write-back. "
        "Mirrors ApproveCompensation in supply_chain_rca."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.HUMAN, SideEffectKind.CASE_STATE}
    )
    auto_execute_disabled: ClassVar[bool] = True
    input_schema: ClassVar[type[BaseModel]] = _ApprovalParams

    async def execute(self, params: _ApprovalParams, state: CaseState) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            outputs={"reason": params.reason},
            state_changes={
                "approval_pending": True,
                "approval_reason": params.reason,
            },
        )


# ---------------------------------------------------------------------------
# Action 4 — QuarantineLot (ABOX_WRITE)
# ---------------------------------------------------------------------------


class _QuarantineParams(BaseModel):
    lot_uri: str = Field(min_length=1)


class QuarantineLot(BaseAction):
    """Set ``mfg:quarantined true`` on the lot in ontorag's data graph."""

    uri: ClassVar[str] = "urn:demo:manufacturing:QuarantineLot"
    name: ClassVar[str] = "Quarantine lot"
    description: ClassVar[str] = (
        "Write `mfg:quarantined = true` on the selected lot via SPARQL UPDATE "
        "(the self-contained equivalent of `AssertTriple` over MCP)."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.ABOX_WRITE, SideEffectKind.CASE_STATE}
    )
    auto_execute_disabled: ClassVar[bool] = True
    input_schema: ClassVar[type[BaseModel]] = _QuarantineParams

    async def execute(self, params: _QuarantineParams, state: CaseState) -> ActionResult:  # type: ignore[override]
        sparql = await set_lot_quarantined(params.lot_uri, quarantined=True)
        return ActionResult(
            action_uri=self.uri,
            outputs={
                "lot_uri": params.lot_uri,
                "sparql_update": sparql,
            },
            state_changes={
                "quarantined": True,
                "quarantined_lot_uri": params.lot_uri,
            },
        )


# ---------------------------------------------------------------------------
# Action 5 — CounterfactualReplay (closes the loop)
# ---------------------------------------------------------------------------


class _ReplayParams(BaseModel):
    pass


class CounterfactualReplay(BaseAction):
    """Run a Pearl Rung 3 query: had AssemblyPressure stayed normal, P(fail)?

    The answer attaches the "what-if" trace to the case so forensic review
    has both the *what we did* (quarantine) and *what we'd have predicted
    had we not* on record.
    """

    uri: ClassVar[str] = "urn:demo:manufacturing:CounterfactualReplay"
    name: ClassVar[str] = "Counterfactual replay"
    description: ClassVar[str] = (
        "Counterfactual P(ProductDefect | observed=(pressure=low, defect=fail), "
        "intervention=(pressure=normal)) — closes the RCA loop with a Pearl Rung 3 trace."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.CASE_STATE}
    )
    input_schema: ClassVar[type[BaseModel]] = _ReplayParams

    def __init__(self) -> None:
        self._engine = CausalEngine(MANUFACTURING_BN, MANUFACTURING_CAUSAL)

    async def execute(self, params: _ReplayParams, state: CaseState) -> ActionResult:  # type: ignore[override]
        defect_uri = NODES_BY_NAME["ProductDefect"].uri
        pressure_uri = NODES_BY_NAME["AssemblyPressure"].uri
        raw = await self._engine.counterfactual(
            observed={pressure_uri: "low", defect_uri: "fail"},
            intervention={pressure_uri: "normal"},
            query=[defect_uri],
        )
        dist = raw[defect_uri]
        return ActionResult(
            action_uri=self.uri,
            outputs={"counterfactual_distribution": dist},
            state_changes={
                "counterfactual_p_fail": round(dist.get("fail", 0.0), 4),
                "rca_complete": True,
            },
        )


# ---------------------------------------------------------------------------
# Composition helper
# ---------------------------------------------------------------------------


def build_domain_actions(store: GraphStore) -> tuple[BaseAction, ...]:
    """Instantiate the five domain actions with their injected dependencies."""
    return (
        PinpointSuspectLot(store),
        EvaluateIntervention(),
        RequestQuarantineApproval(),
        QuarantineLot(),
        CounterfactualReplay(),
    )


# Convenience exports for runner.py state-key references.
SUSPECT_LOT_KEY: str = "suspect_lot_id"
QUARANTINED_KEY: str = "quarantined"


def lot_uri_for(lot_id: str) -> str:
    """Recover the URI the generator assigned to a lot_id (e.g. ``LOT-0047``)."""
    from ontorag_demo.schema import NAMESPACE

    return f"{NAMESPACE}lot/{lot_id}"


__all__ = [
    "CounterfactualReplay",
    "EvaluateIntervention",
    "PinpointSuspectLot",
    "QuarantineLot",
    "QUARANTINED_KEY",
    "RequestQuarantineApproval",
    "SUSPECT_LOT_KEY",
    "build_domain_actions",
    "lot_uri_for",
]


# pyright: reportUnusedImport=false
_ANY_HINT: Any = None  # noqa: E305 — silences "import not used" for mypy strict
