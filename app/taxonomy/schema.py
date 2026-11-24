from dataclasses import dataclass
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


@dataclass(frozen=True)
class Scope:
    org_id: UUID
    site_id: UUID


class TagNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    status: Literal["active", "inactive"]
    children: list[UUID]


class TagTree(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roots: list[UUID]
    nodes: dict[UUID, TagNode]

    @model_validator(mode="after")
    def validate_node_references(self):
        if any(root not in self.nodes for root in self.roots):
            raise ValueError("tree references a missing root node")
        if any(child not in self.nodes for node in self.nodes.values() for child in node.children):
            raise ValueError("tree references a missing child node")
        return self


class AliasMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: dict[str, UUID]


Snapshot = TypeVar("Snapshot", TagTree, AliasMap)
Kind = Literal["tree", "alias"]


class CachedSnapshot(BaseModel, Generic[Snapshot]):
    model_config = ConfigDict(extra="forbid")

    dictionary_id: UUID
    version: int
    data: Snapshot
