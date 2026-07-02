import pytest

from skillmind.analyzer.patterns import (
    AnalysisResult,
    CommandPattern,
    ToolSequencePattern,
    _clean_snippet,
    _extract_tool_sequence,
    _normalize_command,
    analyze,
)
from skillmind.telemetry.claude_code import Session, ToolCall, Turn


# --- helpers ---

def _make_session(session_id: str, commands: list[str], tool_names: list[str] = None) -> Session:
    tool_calls = []
    if commands:
        tool_calls += [ToolCall(name="Bash", input={"command": cmd}, session_id=session_id) for cmd in commands]
    if tool_names:
        tool_calls += [ToolCall(name=name, input={}, session_id=session_id) for name in tool_names]
    turn = Turn(role="assistant", text="", tool_calls=tool_calls, session_id=session_id)
    return Session(session_id=session_id, project_path="/fake", turns=[turn])


def _make_session_with_context(session_id: str, cmd_context_pairs: list[tuple[str, str]]) -> Session:
    """Session where each bash command carries an assistant reasoning snippet."""
    tool_calls = [
        ToolCall(name="Bash", input={"command": cmd}, session_id=session_id, context=ctx)
        for cmd, ctx in cmd_context_pairs
    ]
    turn = Turn(role="assistant", text="", tool_calls=tool_calls, session_id=session_id)
    return Session(session_id=session_id, project_path="/fake", turns=[turn])


def _make_tool_calls(names: list[str], session_id: str = "s") -> list[ToolCall]:
    return [ToolCall(name=n, input={}, session_id=session_id) for n in names]


# --- _normalize_command ---

def test_normalize_single_token():
    assert _normalize_command("git") == "git"


def test_normalize_two_tokens_no_flag():
    assert _normalize_command("git add") == "git add"
    assert _normalize_command("gh api") == "gh api"


def test_normalize_flag_as_second_token():
    assert _normalize_command("git --version") == "git"
    assert _normalize_command("ls -la") == "ls"


def test_normalize_path_only_commands():
    assert _normalize_command("cd /some/long/path") == "cd"
    assert _normalize_command("export FOO=bar") == "export"
    assert _normalize_command("source ~/.zshrc") == "source"
    assert _normalize_command(". ~/.bashrc") == "."


def test_normalize_empty():
    assert _normalize_command("") == ""
    assert _normalize_command("   ") == "   "


def test_normalize_extra_whitespace():
    assert _normalize_command("  git   add  ") == "git add"


# --- _extract_tool_sequence ---

def test_extract_tool_sequence_basic():
    calls = _make_tool_calls(["Bash", "Bash", "Read", "Write"])
    seqs = _extract_tool_sequence(calls, window=3)
    assert ("Bash", "Bash", "Read") in seqs
    assert ("Bash", "Read", "Write") in seqs
    assert len(seqs) == 2


def test_extract_tool_sequence_too_short():
    calls = _make_tool_calls(["Bash", "Read"])
    assert _extract_tool_sequence(calls, window=3) == []


def test_extract_tool_sequence_exact_window():
    calls = _make_tool_calls(["Bash", "Read", "Write"])
    seqs = _extract_tool_sequence(calls, window=3)
    assert seqs == [("Bash", "Read", "Write")]


def test_extract_tool_sequence_empty():
    assert _extract_tool_sequence([], window=3) == []


# --- analyze ---

def test_analyze_command_patterns():
    s1 = _make_session("s1", ["git status", "git status", "ls"])
    s2 = _make_session("s2", ["git status", "ls"])
    result = analyze([s1, s2], min_command_count=2, min_sequence_count=99)
    cmds = {p.command: p for p in result.command_patterns}
    assert "git status" in cmds
    assert cmds["git status"].count == 3
    assert "ls" in cmds
    assert cmds["ls"].count == 2


def test_analyze_filters_low_count_commands():
    s1 = _make_session("s1", ["rare-cmd"])
    result = analyze([s1], min_command_count=2, min_sequence_count=99)
    assert not any(p.command == "rare-cmd" for p in result.command_patterns)


def test_analyze_sequence_patterns():
    tool_names = ["Bash", "Bash", "Read"]
    s1 = _make_session("s1", [], tool_names)
    s2 = _make_session("s2", [], tool_names)
    result = analyze([s1, s2], min_command_count=99, min_sequence_count=2)
    seqs = {p.sequence for p in result.sequence_patterns}
    assert ("Bash", "Bash", "Read") in seqs


def test_analyze_session_deduplication():
    # Same command appearing multiple times in one session counts once toward session list
    s1 = _make_session("s1", ["git add", "git add", "git add"])
    result = analyze([s1], min_command_count=1, min_sequence_count=99)
    cmds = {p.command: p for p in result.command_patterns}
    assert cmds["git add"].count == 3
    assert len(cmds["git add"].sessions) == 1


def test_analyze_empty_sessions():
    result = analyze([], min_command_count=1, min_sequence_count=1)
    assert result.command_patterns == []
    assert result.sequence_patterns == []
    assert result.total_sessions == 0
    assert result.total_tool_calls == 0


def test_analyze_total_counts():
    s1 = _make_session("s1", ["ls"], ["Bash", "Read"])
    s2 = _make_session("s2", ["ls"], ["Bash", "Write"])
    result = analyze([s1, s2], min_command_count=1, min_sequence_count=99)
    assert result.total_sessions == 2
    assert result.total_tool_calls == 6  # 2 bash cmds + read + write + 2 bash tool calls


def test_analyze_cd_stripped():
    s1 = _make_session("s1", ["cd /home/user/projects", "cd /tmp"])
    s2 = _make_session("s2", ["cd /other/path"])
    result = analyze([s1, s2], min_command_count=2, min_sequence_count=99)
    cmds = {p.command for p in result.command_patterns}
    assert "cd" in cmds
    assert not any("/" in c for c in cmds)


# --- intent extraction ---

def test_analyze_intent_snippets_populated():
    s1 = _make_session_with_context("s1", [
        ("git status", "I'll check the working tree before committing."),
        ("git status", "Let me verify what changed."),
    ])
    s2 = _make_session_with_context("s2", [
        ("git status", "Running git status to see untracked files."),
    ])
    result = analyze([s1, s2], min_command_count=1, min_sequence_count=99)
    cmds = {p.command: p for p in result.command_patterns}
    assert "git status" in cmds
    assert len(cmds["git status"].intent_snippets) == 3


def test_analyze_intent_snippets_deduplicated():
    repeated_ctx = "I'll check the working tree."
    s1 = _make_session_with_context("s1", [
        ("git status", repeated_ctx),
        ("git status", repeated_ctx),
    ])
    result = analyze([s1], min_command_count=1, min_sequence_count=99)
    cmds = {p.command: p for p in result.command_patterns}
    assert cmds["git status"].intent_snippets.count(repeated_ctx) == 1


def test_analyze_intent_snippets_capped_at_five():
    pairs = [(f"git status", f"Context number {i}") for i in range(10)]
    s1 = _make_session_with_context("s1", pairs)
    result = analyze([s1], min_command_count=1, min_sequence_count=99)
    cmds = {p.command: p for p in result.command_patterns}
    assert len(cmds["git status"].intent_snippets) <= 5


def test_analyze_no_intent_when_context_empty():
    s1 = _make_session("s1", ["git status", "git status"])
    result = analyze([s1], min_command_count=1, min_sequence_count=99)
    cmds = {p.command: p for p in result.command_patterns}
    assert cmds["git status"].intent_snippets == []


def test_clean_snippet_trims_and_joins_lines():
    text = "  First line.  \n  Second line.  \n"
    assert _clean_snippet(text) == "First line. Second line."


def test_clean_snippet_truncates_long_text():
    long_text = "x" * 300
    assert len(_clean_snippet(long_text)) == 200


# --- CommandPattern / ToolSequencePattern properties ---

def test_command_pattern_confidence_caps_at_one():
    p = CommandPattern(command="git add", count=100, sessions=[])
    assert p.confidence == 1.0


def test_command_pattern_confidence_partial():
    p = CommandPattern(command="git add", count=5, sessions=[])
    assert p.confidence == 0.5


def test_tool_sequence_label():
    p = ToolSequencePattern(sequence=("Bash", "Read", "Write"), count=1, sessions=[])
    assert p.label == "Bash → Read → Write"


def test_tool_sequence_confidence_caps():
    p = ToolSequencePattern(sequence=("A", "B", "C"), count=10, sessions=[])
    assert p.confidence == 1.0


# --- AnalysisResult top_n ---

def test_top_commands_sorted():
    patterns = [
        CommandPattern("b", 5, []),
        CommandPattern("a", 10, []),
        CommandPattern("c", 2, []),
    ]
    result = AnalysisResult(command_patterns=patterns, sequence_patterns=[], total_sessions=1, total_tool_calls=0)
    top = result.top_commands(2)
    assert [p.command for p in top] == ["a", "b"]


def test_top_sequences_sorted():
    patterns = [
        ToolSequencePattern(("X", "Y", "Z"), 3, []),
        ToolSequencePattern(("A", "B", "C"), 7, []),
    ]
    result = AnalysisResult(command_patterns=[], sequence_patterns=patterns, total_sessions=1, total_tool_calls=0)
    top = result.top_sequences(1)
    assert top[0].sequence == ("A", "B", "C")
