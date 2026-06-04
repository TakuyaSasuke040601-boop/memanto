"""
MEMANTO CLI - Analyze external memory providers (export, compare, report).
"""

from datetime import datetime, timezone

import typer
from rich.panel import Panel

from memanto.cli.analyze.supermemory_compare import (
    build_llm_prompt,
    build_report_markdown,
    compute_metrics,
)
from memanto.cli.analyze.supermemory_export import run_supermemory_export
from memanto.cli.commands._shared import (
    BOLD_PRIMARY,
    BRIGHT,
    PRIMARY,
    SUCCESS,
    _error,
    _warn,
    analyze_app,
    config_manager,
    console,
    get_client,
)


def _resolve_supermemory_api_key(api_key: str | None) -> str:
    if api_key and api_key.strip():
        config_manager.set_supermemory_api_key(api_key.strip())
        resolved = config_manager.get_supermemory_api_key()
        if resolved:
            return resolved

    stored = config_manager.get_supermemory_api_key()
    if stored:
        return stored

    console.print(
        Panel.fit(
            f"[{BOLD_PRIMARY}]Supermemory API key[/{BOLD_PRIMARY}]\n"
            "[dim]Get yours at https://supermemory.ai/docs[/dim]",
            border_style=PRIMARY,
        )
    )
    entered = typer.prompt("  Enter your Supermemory API key", hide_input=True)
    if not entered or not entered.strip():
        _error(
            "Supermemory API key is required.",
            hint="Pass --api-key or set SUPERMEMORY_API_KEY in ~/.memanto/.env",
        )

    config_manager.set_supermemory_api_key(entered.strip())
    console.print("[green]  ✓ API key saved to ~/.memanto/.env[/green]")
    resolved = config_manager.get_supermemory_api_key()
    if not resolved:
        _error("Failed to save Supermemory API key.")
    return resolved


def _generate_narrative(prompt: str) -> tuple[str, str, str]:
    """
    Generate the comparison narrative with Memanto's own LLM (Moorcheh answer).

    Returns (narrative_text, llm_model, llm_method). On any failure, returns an
    empty narrative so the deterministic report is still written.
    """
    method = (
        "Moorcheh 'answer' endpoint over the active agent's namespace; "
        "memory retrieval suppressed (top_k=1, high threshold) so the model "
        "writes purely from the supplied metrics."
    )
    try:
        client = get_client()
        active_agent_id, _ = config_manager.get_active_session()
        if not active_agent_id:
            _warn(
                "No active agent — skipping LLM narrative. "
                "Run 'memanto agent activate <agent-id>' to include it."
            )
            return "", "none (no active agent)", method

        ans_cfg = config_manager.get_answer_config()
        model = ans_cfg.get("model", "unknown")

        result = client.answer(
            agent_id=active_agent_id,
            question=prompt,
            limit=1,
            kiosk_mode=True,
            threshold=0.99,
            temperature=0.3,
            header_prompt=(
                "You are a precise infrastructure analyst writing a migration brief. "
                "Use present tense for the user's current Supermemory footprint; "
                "use future or conditional tense (can/would/could) for Memanto "
                "benefits. Output clean markdown. Do not fabricate benchmark numbers."
            ),
            footer_prompt="Return only the markdown brief, no preamble.",
        )
        narrative = (result or {}).get("answer", "") or ""
        return narrative, model, method
    except Exception as exc:
        _warn(f"LLM narrative generation failed: {exc}")
        return "", "unavailable (generation failed)", method


@analyze_app.command("supermemory")
def analyze_supermemory(
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        envvar="SUPERMEMORY_API_KEY",
        help="Supermemory API key (saved to ~/.memanto/.env)",
    ),
):
    """Analyze a Supermemory account and compare it against Memanto.

    Exports all Supermemory data, computes deterministic savings metrics from
    your real data, generates an LLM comparison narrative, and writes a report.

    Output is saved to:
        ~/.memanto/analyze/supermemory/<timestamp>/
            supermemory_export.json
            analyze-report.md

    The Supermemory key is stored in ~/.memanto/.env. The narrative uses your
    active Memanto agent's LLM (run 'memanto agent activate <id>' first).

    Examples:
        memanto analyze supermemory
        memanto analyze supermemory --api-key sm_...
    """
    key = _resolve_supermemory_api_key(api_key)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = config_manager.get_analyze_dir("supermemory") / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel.fit(
            f"[{BOLD_PRIMARY}]Supermemory analyze[/{BOLD_PRIMARY}]\n"
            "Exporting account data and comparing against Memanto...",
            border_style=PRIMARY,
        )
    )

    def on_progress(message: str) -> None:
        console.print(f"  [{BRIGHT}]…[/{BRIGHT}] {message}")

    try:
        export_path, export = run_supermemory_export(
            key,
            run_dir,
            on_progress=on_progress,
        )
    except ImportError as exc:
        _error(str(exc))
    except Exception as exc:
        _error(f"Supermemory export failed: {exc}")

    on_progress("Computing comparison metrics...")
    metrics = compute_metrics(export)

    on_progress("Generating comparison narrative...")
    narrative, llm_model, llm_method = _generate_narrative(build_llm_prompt(metrics))

    report_md = build_report_markdown(
        metrics=metrics,
        narrative=narrative,
        export_path=str(export_path),
        llm_model=llm_model,
        llm_method=llm_method,
        exported_at=export.get("exported_at"),
    )
    report_path = run_dir / "analyze-report.md"
    report_path.write_text(report_md, encoding="utf-8")

    v = metrics["volume"]
    t = metrics["ingestion_tax"]
    s = metrics["storage"]
    lat = metrics["latency"]

    console.print()
    console.print(
        Panel(
            f"[bold green]Analysis complete[/bold green]\n\n"
            f"[dim]Report:[/dim] {report_path}\n"
            f"[dim]Export:[/dim] {export_path}\n\n"
            f"[dim]Documents:[/dim] {v['documents']}  "
            f"[dim]Chunks:[/dim] {v['chunks']}  "
            f"[dim]Memories:[/dim] {v['memories']}\n"
            f"[dim]Could save at ingest:[/dim] ~{t['tokens_saved']:,} tokens\n"
            f"[dim]Could free storage:[/dim] {s['saved_human']} "
            f"(~{s['compression_ratio']}x smaller)\n"
            f"[dim]Read latency (projected):[/dim] ~{lat['supermemory_read_ms']}ms → "
            f"<{lat['memanto_read_ms']}ms (~{lat['speedup_x']}x faster)",
            border_style=SUCCESS,
        )
    )
