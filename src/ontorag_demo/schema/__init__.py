"""Stage 1 — OWL/Turtle schema for the synthetic manufacturing domain."""

from __future__ import annotations

from importlib.resources import files

SCHEMA_PATH = files(__package__) / "manufacturing.ttl"
"""Resource path for the TBox Turtle file."""

NAMESPACE = "https://ontorag-demo.dev/manufacturing#"
"""URI prefix used for all classes and instances in the demo."""
