# ruff: noqa: E402, I001
"""PoC for Bug Challenge #770: temporal recall filters were silently ignored.

Run from the repository root:

    uv run python scripts/poc_temporal_recall_filter.py

Before the fix, build_temporal_query() emitted a created_after field but
RecallRequest did not declare it, so Pydantic dropped the field and /recall
searched the entire history. After the fix, the same payload preserves the
created_after bound and /recall passes it into MemoryReadService.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memanto.app.routes.memory import RecallRequest
from memanto.app.utils.temporal_helpers import build_temporal_query


payload = build_temporal_query(
    "http://localhost:8000",
    "support-agent",
    "importer preference",
    relative_time="last 7 days",
)["json"]

print("Payload emitted by build_temporal_query():")
print(payload)

request = RecallRequest.model_validate(payload)
created_after = getattr(request, "created_after", None)

if created_after is None:
    raise SystemExit(
        "BUG REPRODUCED: RecallRequest dropped created_after, so /recall cannot "
        "apply the temporal filter."
    )

print("OK: RecallRequest preserved created_after:", created_after.isoformat())
