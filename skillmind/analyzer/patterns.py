"""
skillmind.analyzer.patterns
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Detect recurring patterns across Claude Code sessions.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from skillmind.telemetry.claude_code import Session, ToolCall


@dataclass
class CommandPattern:
    command: str
    count: int
    sessions: list[str] = field(default_factory=list)
    intent_snippets: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return min(1.0, self.count / 10)


@dataclass
class ToolSequencePattern:
    sequence: tuple[str, ...]
    count: int
    sessions: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return " → ".join(self.sequence)

    @property
    def confidence(self) -> float:
        return min(1.0, self.count / 5)


@dataclass
class AnalysisResult:
    command_patterns: list[CommandPattern]
    sequence_patterns: list[ToolSequencePattern]
    total_sessions: int
    total_tool_calls: int

    def top_commands(self, n: int = 10) -> list[CommandPattern]:
        return sorted(self.command_patterns, key=lambda p: p.count, reverse=True)[:n]

    def top_sequences(self, n: int = 10) -> list[ToolSequencePattern]:
        return sorted(self.sequence_patterns, key=lambda p: p.count, reverse=True)[:n]


_PATH_ONLY_CMDS = {"cd", "export", "source", "."}
_MAX_SNIPPET_LEN = 200
_MAX_SNIPPETS_PER_PATTERN = 5


def _clean_snippet(text: str) -> str:
    """Trim and normalise a context snippet to a single short string."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    joined = " ".join(lines)
    return joined[:_MAX_SNIPPET_LEN].strip()

def _normalize_command(cmd: str) -> str:
    tokens = cmd.strip().split()
    if not tokens:
        return cmd
    base = tokens[0]
    if base in _PATH_ONLY_CMDS:
        return base
    if len(tokens) > 1 and not tokens[1].startswith("-"):
        base = f"{tokens[0]} {tokens[1]}"
    return base


def _extract_tool_sequence(tool_calls: list[ToolCall],
                            window: int = 3) -> list[tuple[str, ...]]:
    names = [tc.name for tc in tool_calls]
    return [tuple(names[i:i + window]) for i in range(len(names) - window + 1)]


def analyze(sessions: list[Session],
            min_command_count: int = 2,
            min_sequence_count: int = 2,
            sequence_window: int = 3) -> AnalysisResult:
    command_counter: Counter[str] = Counter()
    command_sessions: dict[str, list[str]] = {}
    command_intents: dict[str, list[str]] = {}
    sequence_counter: Counter[tuple] = Counter()
    sequence_sessions: dict[tuple, list[str]] = {}
    total_tool_calls = 0

    for session in sessions:
        seen_cmds: set[str] = set()
        seen_seqs: set[tuple] = set()
        total_tool_calls += len(session.tool_calls)

        for tc in session.tool_calls:
            if tc.name != "Bash" or not tc.command:
                continue
            norm = _normalize_command(tc.command)
            command_counter[norm] += 1
            if norm not in seen_cmds:
                command_sessions.setdefault(norm, []).append(session.session_id)
                seen_cmds.add(norm)
            if tc.context:
                snippet = _clean_snippet(tc.context)
                existing = command_intents.setdefault(norm, [])
                if snippet and snippet not in existing and len(existing) < _MAX_SNIPPETS_PER_PATTERN:
                    existing.append(snippet)

        for seq in _extract_tool_sequence(session.tool_calls, window=sequence_window):
            sequence_counter[seq] += 1
            if seq not in seen_seqs:
                sequence_sessions.setdefault(seq, []).append(session.session_id)
                seen_seqs.add(seq)

    return AnalysisResult(
        command_patterns=[
            CommandPattern(
                cmd, count,
                command_sessions.get(cmd, []),
                command_intents.get(cmd, []),
            )
            for cmd, count in command_counter.items()
            if count >= min_command_count
        ],
        sequence_patterns=[
            ToolSequencePattern(seq, count, sequence_sessions.get(seq, []))
            for seq, count in sequence_counter.items()
            if count >= min_sequence_count
        ],
        total_sessions=len(sessions),
        total_tool_calls=total_tool_calls,
    )
