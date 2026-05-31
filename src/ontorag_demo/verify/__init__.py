"""Stage 4 — ontorag standalone verification primitives.

Two independent layers that the runner scripts compose:

* ``trace.py`` — SPARQL traceability over Fuseki (requires the store to be loaded).
* ``causal.py`` — pgmpy posterior / do / counterfactual over the in-memory BN
  (no graph store needed).
"""

from __future__ import annotations
