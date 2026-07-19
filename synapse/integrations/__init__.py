"""
Official open-source engine integrations from the master blueprint.

Repos (document specification):
  - getzep/graphiti       → graphiti-core (live)
  - microsoft/graphrag    → graphrag package
  - datajuicer/data-juicer → py-data-juicer
  - VectifyAI/PageIndex   → pageindex package

Each adapter prefers the real package when importable; falls back to
in-repo lite only if the package is missing — never silently pretends.
"""

from synapse.integrations.availability import engine_availability
from synapse.integrations.data_juicer_adapter import (
    DataJuicerAdapter,
    create_prep_adapter,
)
from synapse.integrations.graphiti_adapter import graphiti_status
from synapse.integrations.graphrag_adapter import (
    GraphRAGAdapter,
    create_graphrag_adapter,
)
from synapse.integrations.pageindex_adapter import (
    PageIndexAdapter,
    create_pageindex_adapter,
)

__all__ = [
    "engine_availability",
    "graphiti_status",
    "DataJuicerAdapter",
    "GraphRAGAdapter",
    "PageIndexAdapter",
    "create_prep_adapter",
    "create_graphrag_adapter",
    "create_pageindex_adapter",
]
