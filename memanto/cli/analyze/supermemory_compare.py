"""
Compare a Supermemory account export against Memanto.

Two layers:
  1. Deterministic metrics computed locally from the export JSON (trustworthy,
     reproducible). These drive every number in the report.
  2. A narrative written by Memanto's own LLM (Moorcheh ``answer`` endpoint),
     grounded strictly in the computed metrics.

Benchmark percentages are intentionally NOT used — only defensible
architectural differences and numbers derived from the user's real data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# --------------------------------------------------------------------------
# Assumptions — every projected number is derived from these. They are printed
# verbatim in the report footer so the analysis stays transparent and editable.
# --------------------------------------------------------------------------
ASSUMPTIONS: dict[str, Any] = {
    "chars_per_token": 4,
    # A standard Float32 embedding stored by vector databases (~4 KB/vector).
    "vector_bytes_float32": 4096,
    # Memanto/Moorcheh stores a 32x-compressed binary code per vector.
    "vector_bytes_memanto": 128,
    "compression_ratio": 32,
    # Published latency envelopes (architectural, not benchmark scores).
    "supermemory_read_ms": 300,
    "memanto_read_ms": 90,
    # Cost assumption for the ingestion "extraction tax" (input tokens an LLM
    # must read to extract facts before embedding). Adjust for your model.
    "extraction_usd_per_1m_input_tokens": 0.15,
}


def _human_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"


def _chunk_text(chunk: dict[str, Any]) -> str:
    return chunk.get("content") or chunk.get("text") or ""


def _memory_text(memory: dict[str, Any]) -> str:
    return memory.get("content") or memory.get("memory") or memory.get("title") or ""


def compute_metrics(export: dict[str, Any]) -> dict[str, Any]:
    """Compute deterministic comparison metrics from a Supermemory export."""
    summary = export.get("summary", {}) or {}
    documents = export.get("documents", []) or []
    memories = export.get("memories", []) or []

    doc_count = int(summary.get("document_count") or len(documents))
    chunk_count = int(summary.get("chunk_count") or 0)
    memory_count = int(summary.get("memory_entry_count") or len(memories))
    tag_count = int(summary.get("container_tag_count") or 0)
    connection_count = int(summary.get("connection_count") or 0)

    total_chars = 0
    for doc in documents:
        for chunk in doc.get("chunks", []) or []:
            total_chars += len(_chunk_text(chunk))
    for memory in memories:
        total_chars += len(_memory_text(memory))

    cpt = ASSUMPTIONS["chars_per_token"]
    content_tokens = total_chars // cpt if cpt else 0

    # Ingestion tax: Supermemory passes content through an extraction LLM at
    # ingest time. Memanto's typed primitives bypass the LLM entirely → 0.
    ingestion_tokens_sm = content_tokens
    ingestion_cost_sm = (
        ingestion_tokens_sm / 1_000_000
    ) * ASSUMPTIONS["extraction_usd_per_1m_input_tokens"]

    # Storage: one vector per chunk (fall back to memory count if no chunks).
    vector_count = chunk_count or memory_count
    storage_sm_bytes = vector_count * ASSUMPTIONS["vector_bytes_float32"]
    storage_mem_bytes = vector_count * ASSUMPTIONS["vector_bytes_memanto"]
    storage_saved_bytes = storage_sm_bytes - storage_mem_bytes

    read_ms_sm = ASSUMPTIONS["supermemory_read_ms"]
    read_ms_mem = ASSUMPTIONS["memanto_read_ms"]
    latency_speedup = round(read_ms_sm / read_ms_mem, 1) if read_ms_mem else 0

    return {
        "volume": {
            "documents": doc_count,
            "chunks": chunk_count,
            "memories": memory_count,
            "container_tags": tag_count,
            "connections": connection_count,
            "total_content_chars": total_chars,
            "estimated_content_tokens": content_tokens,
            "vector_count": vector_count,
        },
        "ingestion_tax": {
            "supermemory_extraction_tokens": ingestion_tokens_sm,
            "supermemory_extraction_cost_usd": round(ingestion_cost_sm, 4),
            "memanto_extraction_tokens": 0,
            "memanto_extraction_cost_usd": 0.0,
            "tokens_saved": ingestion_tokens_sm,
        },
        "storage": {
            "supermemory_bytes": storage_sm_bytes,
            "memanto_bytes": storage_mem_bytes,
            "bytes_saved": storage_saved_bytes,
            "supermemory_human": _human_bytes(storage_sm_bytes),
            "memanto_human": _human_bytes(storage_mem_bytes),
            "saved_human": _human_bytes(storage_saved_bytes),
            "compression_ratio": ASSUMPTIONS["compression_ratio"],
        },
        "latency": {
            "supermemory_read_ms": read_ms_sm,
            "memanto_read_ms": read_ms_mem,
            "speedup_x": latency_speedup,
            "ms_saved_per_query": read_ms_sm - read_ms_mem,
        },
    }


def build_llm_prompt(metrics: dict[str, Any]) -> str:
    """Self-contained instruction + data for the Moorcheh answer endpoint."""
    v = metrics["volume"]
    t = metrics["ingestion_tax"]
    s = metrics["storage"]
    lat = metrics["latency"]

    return (
        "You are a senior infrastructure analyst writing a migration brief that "
        "compares a user's existing Supermemory deployment against Memanto "
        "(powered by the Moorcheh engine). Use ONLY the measured data below. "
        "Do NOT invent benchmark scores or numbers that are not provided.\n\n"
        "=== MEASURED SUPERMEMORY FOOTPRINT ===\n"
        f"- Documents: {v['documents']}\n"
        f"- RAG chunks (vectors): {v['chunks']}\n"
        f"- Memory entries: {v['memories']}\n"
        f"- Container tags: {v['container_tags']}\n"
        f"- Estimated content tokens: {v['estimated_content_tokens']:,}\n\n"
        "=== PROJECTED MEMANTO IMPACT (if you migrate) ===\n"
        f"1. Ingestion tax — Today Supermemory would run an extraction LLM over "
        f"this content at ingest (~{t['supermemory_extraction_tokens']:,} input "
        f"tokens, ~${t['supermemory_extraction_cost_usd']}). With Memanto, typed "
        f"primitives could bypass that step → 0 tokens, $0.\n"
        f"2. Latency — Supermemory is ~{lat['supermemory_read_ms']}ms read with an "
        f"indexing delay before new memories are searchable. Memanto could deliver "
        f"<{lat['memanto_read_ms']}ms read and 0ms write (instantly searchable) — "
        f"about {lat['speedup_x']}x faster per query.\n"
        f"3. Storage — Supermemory currently stores Float32 vectors "
        f"({s['supermemory_human']} across {v['vector_count']} vectors). Memanto "
        f"could use {s['compression_ratio']}x binary compression ({s['memanto_human']}), "
        f"freeing {s['saved_human']}, on serverless infra that scales to zero when "
        f"idle.\n"
        "4. Retrieval model — Supermemory uses probabilistic Approximate Nearest "
        "Neighbor (ANN) search; Memanto would use deterministic exact-match recall "
        "(bitwise Hamming distance on CPU), which can reduce vector-induced "
        "mis-retrieval.\n\n"
        "VOICE & TENSE (required):\n"
        "- Present tense for what the user HAS in Supermemory today (measured facts).\n"
        "- Future or conditional tense for Memanto benefits (can save, would save, "
        "could improve, if you migrate). Do NOT write as if they already use Memanto.\n\n"
        "Write a concise, professional markdown brief with these sections:\n"
        "## Executive summary (2-3 sentences)\n"
        "## What you could save by migrating (bullet token, storage, latency wins "
        "using the numbers above)\n"
        "## What could improve in your memory layer (precision, instant writes, typed "
        "primitives, serverless cost)\n"
        "## Migration considerations (honest trade-offs and next steps)\n"
        "Keep it grounded and specific to the numbers. Do not add benchmark "
        "percentages."
    )


def build_report_markdown(
    *,
    metrics: dict[str, Any],
    narrative: str,
    export_path: str,
    llm_model: str,
    llm_method: str,
    exported_at: str | None,
) -> str:
    v = metrics["volume"]
    t = metrics["ingestion_tax"]
    s = metrics["storage"]
    lat = metrics["latency"]
    generated = datetime.now(timezone.utc).isoformat()

    lines: list[str] = []
    lines.append("# Memanto vs. Supermemory — Memory Analysis Report")
    lines.append("")
    lines.append(f"_Generated: {generated}_")
    if exported_at:
        lines.append(f"_Supermemory export: {exported_at}_")
    lines.append("")
    lines.append("## Your Supermemory footprint (measured)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Documents | {v['documents']:,} |")
    lines.append(f"| RAG chunks (vectors) | {v['chunks']:,} |")
    lines.append(f"| Memory entries | {v['memories']:,} |")
    lines.append(f"| Container tags | {v['container_tags']:,} |")
    lines.append(f"| Connections | {v['connections']:,} |")
    lines.append(f"| Estimated content tokens | {v['estimated_content_tokens']:,} |")
    lines.append("")
    lines.append("## Projected impact of migrating to Memanto")
    lines.append("")
    lines.append("### 1. Ingestion tax (token savings)")
    lines.append("")
    lines.append("| | Supermemory | Memanto |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| Extraction input tokens | {t['supermemory_extraction_tokens']:,} | 0 |"
    )
    lines.append(
        f"| Extraction cost (assumed rate) | "
        f"${t['supermemory_extraction_cost_usd']} | $0.00 |"
    )
    lines.append("")
    lines.append(
        f"**You could save ~{t['tokens_saved']:,} input tokens** at ingest if you "
        "migrate — Memanto's typed primitives would skip the extraction LLM entirely."
    )
    lines.append("")
    lines.append("### 2. Latency & indexing")
    lines.append("")
    lines.append("| | Supermemory | Memanto |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| Read latency | ~{lat['supermemory_read_ms']}ms | "
        f"<{lat['memanto_read_ms']}ms |"
    )
    lines.append("| Write availability | indexing delay | 0ms (instant) |")
    lines.append("")
    lines.append(
        f"**Reads could be ~{lat['speedup_x']}x faster** (~{lat['ms_saved_per_query']}ms "
        "saved per query), and new memories would be searchable the moment they are "
        "written."
    )
    lines.append("")
    lines.append("### 3. Storage footprint")
    lines.append("")
    lines.append("| | Supermemory | Memanto |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| Vector storage | {s['supermemory_human']} | {s['memanto_human']} |"
    )
    lines.append("")
    lines.append(
        f"**Storage could be ~{s['compression_ratio']}x smaller** — you would free "
        f"{s['saved_human']} and could run on serverless infrastructure that scales "
        "to zero when idle."
    )
    lines.append("")
    lines.append("## Analysis")
    lines.append("")
    lines.append(narrative.strip() if narrative else "_(LLM narrative unavailable.)_")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Method & assumptions")
    lines.append("")
    lines.append(f"- **LLM:** {llm_model}")
    lines.append(f"- **How compared:** {llm_method}")
    lines.append(f"- **Source export:** `{export_path}`")
    lines.append(
        "- **Metrics:** computed locally from the export; benchmark percentages "
        "deliberately excluded."
    )
    lines.append("- **Assumptions used:**")
    for key, value in ASSUMPTIONS.items():
        lines.append(f"  - `{key}` = {value}")
    lines.append("")
    return "\n".join(lines)
