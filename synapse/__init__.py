"""
Project Synapse — Phase 1 foundation package.

Local, cloud-free semantic data core primitives:
contracts, ABAC, control-plane math, ingest, extract, conflict resolution.
"""

__version__ = "0.17.0"

from synapse.models import (
    Claim,
    Conflict,
    Entity,
    Episode,
    Fact,
    RawObject,
)
from synapse.harness import run_checkout_incident_simulation
from synapse.adjudication import AdjudicationService
from synapse.schema_validate import validate_model_dict
from synapse.eval_runner import evaluate_all, evaluate_checkout_incident, evaluate_pack

__all__ = [
    "AdjudicationService",
    "Claim",
    "Conflict",
    "Entity",
    "Episode",
    "Fact",
    "RawObject",
    "evaluate_all",
    "evaluate_checkout_incident",
    "evaluate_pack",
    "run_checkout_incident_simulation",
    "validate_model_dict",
    "__version__",
]

