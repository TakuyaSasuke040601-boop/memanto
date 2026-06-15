"""
Source → Memanto schema mappers.

Each mapper takes a provider export dict (the same shape produced by the
``cli/analyze/*_export.py`` modules) and yields memory dicts in the format
accepted by ``SdkClient.batch_remember``:

    {"title": str, "content": str, "type": str | None,
     "tags": list[str], "confidence": float}

Mappers skip rows with empty content. ``type`` may be ``None`` — the server's
``MemoryParsingService`` will auto-classify at write time. Titles are derived
from the first ~80 characters of content when the source has no obvious title.

Adding a new provider: write a ``map_<provider>`` function returning
``list[dict]``, register it in ``MAPPERS``, and add a per-provider count
helper in ``cli/commands/migrate.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from memanto.app.constants import VALID_MEMORY_TYPES

# Mem0 ships category labels per memory. Map the common ones to Memanto's
# typed primitives; everything else falls through to None (auto-classify).
_MEM0_CATEGORY_TO_TYPE: dict[str, str] = {
    "personal_details": "fact",
    "personal_preferences": "preference",
    "preferences": "preference",
    "professional_info": "fact",
    "work": "fact",
    "skills": "fact",
    "goals_and_plans": "goal",
    "tasks": "commitment",
    "relationships": "relationship",
    "events": "event",
    "decisions": "decision",
    "observations": "observation",
}

_DEFAULT_TITLE_CHARS = 80


def _title_from(content: str) -> str:
    text = content.strip().replace("\n", " ")
    if len(text) <= _DEFAULT_TITLE_CHARS:
        return text
    return text[: _DEFAULT_TITLE_CHARS - 3].rstrip() + "..."


def _coerce_type(raw: str | None) -> str | None:
    if not raw:
        return None
    t = raw.strip().lower()
    return t if t in VALID_MEMORY_TYPES else None


def _scope_tag(scope: dict[str, Any] | None) -> str | None:
    if not scope:
        return None
    for k, v in scope.items():
        if v:
            return f"{k}={v}"
    return None


def map_mem0(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a Mem0 export to Memanto memory payloads.

    Source-of-truth field is ``memory`` (the distilled fact). Categories
    become Memanto types where they overlap (preferences/goals/etc) and are
    also added as tags. The export scope (user_id/agent_id) is preserved as
    a tag so users can still partition recall by their original Mem0 entity.
    """
    rows: list[dict[str, Any]] = []
    for mem in export.get("memories", []) or []:
        content = (mem.get("memory") or mem.get("content") or "").strip()
        if not content:
            continue

        categories = [
            str(c).lower() for c in (mem.get("categories") or []) if c
        ]
        memory_type: str | None = None
        for cat in categories:
            memory_type = _MEM0_CATEGORY_TO_TYPE.get(cat) or _coerce_type(cat)
            if memory_type:
                break

        tags = list(dict.fromkeys(categories))
        scope_tag = _scope_tag(mem.get("export_scope"))
        if scope_tag:
            tags.append(scope_tag)

        rows.append(
            {
                "title": _title_from(content),
                "content": content,
                "type": memory_type,
                "tags": tags,
                "confidence": 0.8,
            }
        )
    return rows


def map_letta(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a Letta archival passage export to Memanto memory payloads.

    Archival passages are stored conversational facts. Type defaults to
    ``observation`` — closest Memanto primitive for "things the agent has
    seen / recorded over time". Agent name/id is tagged so multi-agent
    Letta accounts stay queryable post-migration.
    """
    rows: list[dict[str, Any]] = []
    for passage in export.get("passages", []) or []:
        content = (
            passage.get("text")
            or passage.get("content")
            or ""
        ).strip()
        if not content:
            continue

        tags: list[str] = []
        agent_name = passage.get("export_agent_name")
        agent_id = passage.get("export_agent_id")
        if agent_name:
            tags.append(f"agent={agent_name}")
        elif agent_id:
            tags.append(f"agent_id={agent_id}")

        rows.append(
            {
                "title": _title_from(content),
                "content": content,
                "type": "observation",
                "tags": tags,
                "confidence": 0.8,
            }
        )
    return rows


def map_supermemory(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a Supermemory export to Memanto memory payloads.

    Uses the ``memories[]`` array — Supermemory's AI-extracted facts — as
    the primary source. Falls back to document chunks only when no
    extracted memories are present (rare; mostly fresh accounts). Each row
    keeps its container tag so Supermemory namespaces map to Memanto tags.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for mem in export.get("memories", []) or []:
        content = (
            mem.get("content")
            or mem.get("memory")
            or mem.get("text")
            or ""
        ).strip()
        if not content:
            continue

        tags: list[str] = []
        tag = mem.get("container_tag")
        if tag:
            tags.append(str(tag))

        rows.append(
            {
                "title": _title_from(content),
                "content": content,
                "type": None,
                "tags": tags,
                "confidence": 0.8,
            }
        )
        seen.add(content)

    if rows:
        return rows

    # Fallback: harvest chunk text when extracted memories are empty.
    for doc in export.get("documents", []) or []:
        doc_tags = [str(t) for t in (doc.get("container_tags") or []) if t]
        for chunk in doc.get("chunks", []) or []:
            content = (chunk.get("content") or chunk.get("text") or "").strip()
            if not content or content in seen:
                continue
            seen.add(content)
            rows.append(
                {
                    "title": _title_from(content),
                    "content": content,
                    "type": "artifact",
                    "tags": doc_tags,
                    "confidence": 0.7,
                }
            )
    return rows


MAPPERS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "mem0": map_mem0,
    "letta": map_letta,
    "supermemory": map_supermemory,
}


def type_breakdown(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count mapped rows by resolved (or unclassified) type — for previews."""
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("type") or "auto"
        counts[key] = counts.get(key, 0) + 1
    return counts
