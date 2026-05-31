"""Stage 3 — synthetic data generator.

The sampler walks the BN top-down, applies per-lot anomaly injection
(plan §3 "noise" — supplier B has a lifted base rate, lot #47 is
deliberately contaminated regardless of supplier), then materialises the
result as both an RDF Turtle file (for ontorag to ingest) and a
``ground_truth.json`` answer key (for Stage 4 verification).

Public entry point: ``generator.run.generate(config, output_dir)``.
"""

from __future__ import annotations

from ontorag_demo.generator.entities import (
    ComponentInstance,
    GroundTruth,
    LotInstance,
    ProcessRunInstance,
    ProductInstance,
    QCResultInstance,
    SupplierInstance,
)
from ontorag_demo.generator.run import GeneratorOutput, generate

__all__ = [
    "ComponentInstance",
    "GeneratorOutput",
    "GroundTruth",
    "LotInstance",
    "ProcessRunInstance",
    "ProductInstance",
    "QCResultInstance",
    "SupplierInstance",
    "generate",
]
