"""Orchestrate sampling + RDF write + ground-truth dump in one call."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from ontorag_demo.causal.model import DEFAULT_GENERATOR_CONFIG, GeneratorConfig
from ontorag_demo.generator.entities import GroundTruth
from ontorag_demo.generator.rdf_writer import build_graph, serialise
from ontorag_demo.generator.sampler import sample

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratorOutput:
    turtle_path: Path
    ground_truth_path: Path
    triple_count: int
    ground_truth: GroundTruth


def generate(
    config: GeneratorConfig = DEFAULT_GENERATOR_CONFIG,
    output_dir: Path | str = Path("data/generated"),
) -> GeneratorOutput:
    """Sample, serialise to Turtle, and write the answer key.

    The function is deliberately synchronous — sampling is CPU-bound and
    keeping it sync makes it trivial to call from tests without spinning
    up an event loop.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    suppliers, lots, components, runs, products, qcs, gt = sample(config)
    logger.info(
        "Sampled %d suppliers, %d lots, %d components, %d runs, %d products (%d fails)",
        len(suppliers),
        len(lots),
        len(components),
        len(runs),
        len(products),
        gt.total_failures,
    )

    graph = build_graph(suppliers, lots, components, runs, products, qcs)
    turtle_path = out / "manufacturing-instances.ttl"
    triple_count = serialise(graph, str(turtle_path))

    gt_path = out / "ground_truth.json"
    gt_path.write_text(
        json.dumps(asdict(gt), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )

    return GeneratorOutput(
        turtle_path=turtle_path,
        ground_truth_path=gt_path,
        triple_count=triple_count,
        ground_truth=gt,
    )
