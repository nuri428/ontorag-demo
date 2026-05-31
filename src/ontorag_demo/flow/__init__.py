"""Stage 5 — ontorag-flow decision loop wrapping the Stage 4 reasoning.

Domain actions wire ontorag's Python API directly (rather than via MCP) so
the demo runs in one process. This matches the supply_chain_rca pattern
in ``vendor/ontorag-flow/examples/`` — the runtime contract is the same;
only the transport changes.
"""

from __future__ import annotations

from ontorag_demo.flow.actions import build_domain_actions
from ontorag_demo.flow.runner import run_flow

__all__ = ["build_domain_actions", "run_flow"]
