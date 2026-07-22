"""
Workspaces: the top-level project boundary a user creates first, imports
sources into, and runs the relationship-discovery journey within. One
workspace's confirmed relationships *are* its schema -- multiple
workspaces naturally give multiple schemas. Combining several workspaces
into a "super schema" is a separate, explicit step (synapse/super_schema.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from synapse.models import new_id, utc_now_iso

DEFAULT_WORKSPACE_ID = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"


@dataclass
class Workspace:
    workspace_id: str
    name: str
    description: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(cls, name: str, description: str = "") -> "Workspace":
        return cls(workspace_id=new_id(), name=name, description=description)
