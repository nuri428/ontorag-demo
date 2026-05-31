"""Immutable dataclass DTOs that the sampler emits and the writers consume."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SupplierInstance:
    uri: str
    supplier_id: str
    is_suspect: bool


@dataclass(frozen=True)
class LotInstance:
    uri: str
    lot_id: str
    supplier_uri: str
    # Latent BN states recorded for ground-truth verification, NOT serialised
    # into the public RDF (a real factory wouldn't have these labels available).
    supplier_quality: str
    lot_quality: str
    is_contaminated: bool


@dataclass(frozen=True)
class ComponentInstance:
    uri: str
    component_id: str
    lot_uri: str
    component_quality: str


@dataclass(frozen=True)
class ProcessRunInstance:
    uri: str
    component_uri: str
    step_uri: str
    condition: str  # discrete state (e.g. "normal" / "high" / "low")


@dataclass(frozen=True)
class ProductInstance:
    uri: str
    product_id: str
    # The chain of three process runs that produced this product. Stored as
    # URIs so the RDF writer can emit `mfg:producedBy` triples symmetrically.
    process_run_uris: tuple[str, ...]


@dataclass(frozen=True)
class QCResultInstance:
    uri: str
    product_uri: str
    verdict: str  # "pass" / "fail"


@dataclass(frozen=True)
class GroundTruth:
    """Answer key consumed by Stage 4 to verify ontorag reaches the same conclusions.

    Captures the things a real factory ops team wouldn't know up-front:
    which supplier is over-represented in defect causes, which lot was
    silently contaminated, and what the *actual* generative process
    parameters were.
    """

    suspect_supplier_id: str
    contaminated_lot_id: str
    # URI of the assembly step — the only process step whose condition
    # actually drives ProductDefect in the BN. Stage 4 should rediscover this.
    causal_process_step_uri: str
    # ProductIDs that failed QC, grouped by the dominant cause attribution from
    # the generator (heuristic but exact given how the sample was drawn).
    failures_by_cause: dict[str, list[str]] = field(default_factory=dict)
    # Per-supplier failure counts (Stage 4 traceability cross-check).
    failures_by_supplier: dict[str, int] = field(default_factory=dict)
    # Per-lot failure counts.
    failures_by_lot: dict[str, int] = field(default_factory=dict)
    total_products: int = 0
    total_failures: int = 0
