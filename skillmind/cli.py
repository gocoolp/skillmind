"""
skillmind CLI — `skillmind scan` and `skillmind suggest`
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich import box, print as rprint
from rich.panel import Panel
from rich.table import Table

from skillmind.telemetry.claude_code import load_all_sessions
from skillmind.analyzer.patterns import analyze
from skillmind.generator.skill_writer import (
    detect_backend,
    skill_from_command_pattern,
    write_skill_file,
)

app = typer.Typer(
    help="SkillMind — detect reusable skills from Claude Code sessions",
    no_args_is_help=True,
)


def _backend_label() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "[green]Anthropic API[/green]"
    if os.environ.get("OPENAI_API_KEY"):
        return "[green]OpenAI-compatible[/green]"
    if os.environ.get("SKILLMIND_OLLAMA"):
        return "[green]Ollama (local)[/green]"
    return "[yellow]none — skeleton mode[/yellow]"


@app.command()
def scan(
    limit: Optional[int] = typer.Option(None, help="Max sessions to parse"),
    log_dir: Optional[Path] = typer.Option(None, help="Override ~/.claude/projects/"),
    min_count: int = typer.Option(2, help="Min occurrences to surface a pattern"),
):
    """Parse Claude Code sessions and show a pattern summary."""
    rprint(Panel(f"[bold]SkillMind scan[/bold]  ·  LLM: {_backend_label()}", expand=False))

    sessions = load_all_sessions(base_dir=log_dir, limit=limit)
    if not sessions:
        rprint("\n[yellow]No sessions found.[/yellow]")
        rprint("[dim]Expected: ~/.claude/projects/**/*.jsonl[/dim]")
        raise typer.Exit()

    result = analyze(sessions, min_command_count=min_count, min_sequence_count=min_count)
    rprint(f"\n[green]✓[/green] [bold]{result.total_sessions}[/bold] sessions · "
           f"[bold]{result.total_tool_calls}[/bold] tool calls\n")

    cmd_table = Table("Command pattern", "Count", "Sessions", "Confidence",
                      box=box.SIMPLE, header_style="bold")
    for p in result.top_commands(10):
        cmd_table.add_row(p.command, str(p.count), str(len(p.sessions)),
                          f"[green]{'█' * int(p.confidence * 10)}[/green]")
    rprint("[bold]Top bash command patterns[/bold]")
    rprint(cmd_table)

    seq_table = Table("Tool sequence", "Count", "Sessions",
                      box=box.SIMPLE, header_style="bold")
    for p in result.top_sequences(8):
        seq_table.add_row(p.label, str(p.count), str(len(p.sessions)))
    rprint("[bold]Top tool-call sequences[/bold]")
    rprint(seq_table)
    rprint("\n[dim]Run [bold]skillmind suggest[/bold] to generate SKILL.md files.[/dim]")


@app.command()
def suggest(
    top_n: int = typer.Option(3, help="Number of top patterns to generate"),
    output: Optional[Path] = typer.Option(None, help="Directory to write SKILL.md files"),
    limit: Optional[int] = typer.Option(None, help="Max sessions to parse"),
    log_dir: Optional[Path] = typer.Option(None, help="Override ~/.claude/projects/"),
    min_count: int = typer.Option(2, help="Min occurrences to surface a pattern"),
    dry_run: bool = typer.Option(False, help="Print drafts without writing files"),
):
    """Generate SKILL.md drafts from the most frequent patterns."""
    backend = detect_backend()
    rprint(Panel(f"[bold]SkillMind suggest[/bold]  ·  LLM: {_backend_label()}", expand=False))

    if backend is None:
        rprint("\n[yellow]No LLM backend — generating skeleton files.[/yellow]")
        rprint("[dim]Set ANTHROPIC_API_KEY / OPENAI_API_KEY / SKILLMIND_OLLAMA for AI drafts.[/dim]\n")

    sessions = load_all_sessions(base_dir=log_dir, limit=limit)
    if not sessions:
        rprint("[yellow]No sessions found.[/yellow]")
        raise typer.Exit()

    result = analyze(sessions, min_command_count=min_count)
    patterns = result.top_commands(top_n)
    if not patterns:
        rprint(f"[yellow]No patterns with min_count >= {min_count}.[/yellow]")
        raise typer.Exit()

    written: list[Path] = []
    for i, pattern in enumerate(patterns, 1):
        tag = "[green](AI)[/green]" if backend else "[dim](skeleton)[/dim]"
        rprint(f"[cyan]{i}/{len(patterns)}[/cyan] {tag} [bold]{pattern.command}[/bold] · {pattern.count}×")
        content, ai = skill_from_command_pattern(pattern, backend)

        if dry_run or output is None:
            rprint(f"\n[dim]{'─'*50}[/dim]\n{content}\n[dim]{'─'*50}[/dim]")
        else:
            path = write_skill_file(content, output, pattern.command)
            written.append(path)
            rprint(f"  [green]✓[/green] {'AI-drafted' if ai else 'skeleton'} → {path}")

    if written:
        rprint(f"\n[bold green]Done.[/bold green] {len(written)} file(s) → [bold]{output}[/bold]")
        if not backend:
            rprint("[dim]Tip: fill in the TODO sections, or re-run with an API key.[/dim]")


if __name__ == "__main__":
    app()
