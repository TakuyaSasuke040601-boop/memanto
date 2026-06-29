"""
MEMANTO Core Architecture - Namespace Strategy & Memory Records
"""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from memanto.app.constants import (
    MemoryType,
    ProvenanceType,
    ScopeType,
    SourceType,
    StatusType,
)


class MemoryScope(BaseModel):
    """Defines the scope for memory isolation"""

    scope_type: ScopeType
    scope_id: str

    def to_namespace(self) -> str:
        """Convert scope to Moorcheh namespace using deterministic mapping"""
        # memanto_{scope_type}_{scope_id}
        return f"memanto_{self.scope_type}_{self.scope_id}"

    @classmethod
    def from_namespace(cls, namespace: str) -> "MemoryScope":
        """Parse namespace back to scope"""
        from typing import cast

        parts = namespace.split("_")
        if len(parts) != 3 or parts[0] != "memanto":
            raise ValueError(f"Invalid MEMANTO namespace format: {namespace}")
        return cls(scope_type=cast(ScopeType, parts[1]), scope_id=parts[2])


class MemoryRecord(BaseModel):
    """Structured memory record with standardized format"""

    # Core fields
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MemoryType | None = None
    title: str = Field(max_length=100)
    content: str = Field(max_length=10000)

    # Metadata fields
    scope_type: ScopeType
    scope_id: str
    actor_id: str
    source: SourceType
    source_ref: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    status: StatusType = "active"
    tags: list[str] = Field(default_factory=list)

    # Provenance
    provenance: ProvenanceType = "explicit_statement"

    # Timestamps (auto-populated by server)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    ttl_seconds: int | None = None

    def to_moorcheh_document(self) -> dict[str, Any]:
        """
        Convert to Moorcheh document format with flat metadata fields.

        Moorcheh stores metadata as flat fields on the document, which enables
        powerful filtering using the # syntax (e.g., #memory_type:fact #confidence>0.8)
        """
        memory_type = self.type or "fact"

        # Format text as standardized card for semantic search
        text = f"[{memory_type.upper()}] {self.title}\n\n{self.content}"
        if self.tags:
            text += f"\n\nTags: {', '.join(self.tags)}"

        # Build document with flat metadata fields (not nested!)
        document = {
            "id": self.id,
            "text": text,
            # Metadata fields (flat structure for Moorcheh filtering)
            "memory_type": memory_type,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "actor_id": self.actor_id,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
            # Provenance
            "provenance": self.provenance,
            # Timestamps
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

        # Add optional fields only if present
        if self.source_ref:
            document["source_ref"] = self.source_ref
        if self.tags:
            document["tags"] = ",".join(self.tags)  # Comma-separated for filtering
        if self.expires_at:
            document["expires_at"] = self.expires_at.isoformat()
        if self.ttl_seconds:
            document["ttl_seconds"] = self.ttl_seconds

        return document

    def get_scope(self) -> MemoryScope:
        """Get the memory scope"""
        return MemoryScope(scope_type=self.scope_type, scope_id=self.scope_id)

    def set_ttl(self, seconds: int):
        """Set TTL and expiration"""
        self.ttl_seconds = seconds
        self.expires_at = datetime.utcnow() + timedelta(seconds=seconds)


# Utility functions
def create_memory_scope(scope_type: ScopeType, scope_id: str) -> MemoryScope:
    """Helper to create memory scope"""
    return MemoryScope(scope_type=scope_type, scope_id=scope_id)


def parse_namespace(namespace: str) -> MemoryScope:
    """Helper to parse namespace"""
    return MemoryScope.from_namespace(namespace)


def validate_namespace_format(namespace: str) -> bool:
    """Validate namespace follows MEMANTO convention"""
    pattern = r"^memanto_(user|workspace|agent|session)_[a-zA-Z0-9_-]+$"
    return bool(re.match(pattern, namespace))
