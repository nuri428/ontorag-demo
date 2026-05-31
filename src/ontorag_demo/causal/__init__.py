"""Stage 2 — Bayesian network + causal DAG for the manufacturing demo.

The same network is used three ways:
* `sampler.py` draws synthetic instances from it (data generation),
* `ontorag.bayes.engine.BayesianEngine` consumes it for L2 posteriors,
* `ontorag.causal.engine.CausalEngine` consumes the DAG for L3 do/CF.

Keeping a single source of truth (`model.MANUFACTURING_BN`) prevents the
"data generator drifts from inference model" failure mode flagged in
``ontorag_flow_demo_plan.md`` §3.
"""

from __future__ import annotations

from ontorag_demo.causal.model import (
    BN_URI,
    CAUSAL_URI,
    MANUFACTURING_BN,
    MANUFACTURING_CAUSAL,
    NODES,
)

__all__ = [
    "BN_URI",
    "CAUSAL_URI",
    "MANUFACTURING_BN",
    "MANUFACTURING_CAUSAL",
    "NODES",
]
