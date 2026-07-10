import json
import textwrap
from pathlib import Path

import pytest

from skillmind.telemetry.claude_code import (
    Session,
    ToolCall,
    _enrich_contexts,
    _extract_text,
    _parse_timestamp,
    iter_session_files,
    load_all_sessions,
    parse_session_file,
)


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(l) for l in lines))


# --- _parse_timestamp ---

def test_parse_timestamp_iso():
    ts = _parse_timestamp({"timestamp": "2024-01-15T10:30:00Z"})
    assert ts is not None
    assert ts.year == 2024


def test_parse_timestamp_missing():
    assert _parse_timestamp({}) is None


def test_parse_timestamp_invalid():
    assert _parse_timestamp({"timestamp": "not-a-date"}) is None


# --- _extract_text ---

def test_extract_text_string():
    assert _extract_text("hello") == "hello"


def test_extract_text_content_blocks():
    content = [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]
    assert _extract_text(content) == "foo\nbar"


def test_extract_text_skips_non_text_blocks():
    content = [{"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "hi"}]
    assert _extract_text(content) == "hi"


def test_extract_text_empty():
    assert _extract_text(None) == ""
    assert _extract_text([]) == ""


# --- ToolCall.context ---

def test_tool_call_context_from_assistant_turn(tmp_path):
    f = tmp_path / "ctx.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "I'll run git status to check the working tree."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}},
        ]}},
    ])
    session = parse_session_file(f)
    tc = session.tool_calls[0]
    assert "git status" in tc.context
    assert "working tree" in tc.context


def test_tool_call_context_empty_for_no_text(tmp_path):
    f = tmp_path / "ctx2.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        ]}},
    ])
    session = parse_session_file(f)
    assert session.tool_calls[0].context == ""


def test_tool_call_lookback_stitches_prior_turns(tmp_path):
    f = tmp_path / "lookback.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "Let me check the auth module first."},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/auth.py"}},
        ]}},
        # tool result — empty text, transparent to lookback
        {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "1", "content": "..."},
        ]}},
        {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "Token validation is too late. Fixing and committing."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m 'fix'"}},
        ]}},
    ])
    session = parse_session_file(f)
    bash_tc = next(tc for tc in session.tool_calls if tc.name == "Bash")
    assert "auth module" in bash_tc.context
    assert "Token validation" in bash_tc.context


def test_tool_call_stops_at_task_boundary(tmp_path):
    f = tmp_path / "boundary.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "Setting up the database schema."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "psql setup.sql"}},
        ]}},
        # real user request = task boundary
        {"message": {"role": "user", "content": "Now deploy the app"}},
        {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "Deploying the application."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "git push heroku main"}},
        ]}},
    ])
    session = parse_session_file(f)
    deploy_tc = next(tc for tc in session.tool_calls if "heroku" in (tc.command or ""))
    assert "Deploying" in deploy_tc.context
    assert "database" not in deploy_tc.context


# --- parse_session_file ---

def test_parse_session_file_basic(tmp_path):
    f = tmp_path / "abc123.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "user", "content": "do something"}},
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}
        ]}},
    ])
    session = parse_session_file(f)
    assert session.session_id == "abc123"
    assert len(session.turns) == 2
    assert session.bash_commands == ["ls -la"]


def test_parse_session_file_tool_calls(tmp_path):
    f = tmp_path / "sess1.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/foo/bar.py"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}},
        ]}},
    ])
    session = parse_session_file(f)
    assert len(session.tool_calls) == 2
    assert session.tool_calls[0].name == "Read"
    assert session.tool_calls[1].command == "git status"


def test_parse_session_file_skips_bad_lines(tmp_path):
    f = tmp_path / "sess2.jsonl"
    f.write_text('{"message": {"role": "user", "content": "ok"}}\nnot json\n')
    session = parse_session_file(f)
    assert len(session.turns) == 1


def test_parse_session_file_skips_unknown_roles(tmp_path):
    f = tmp_path / "sess3.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "system", "content": "sys prompt"}},
        {"message": {"role": "user", "content": "hi"}},
    ])
    session = parse_session_file(f)
    assert len(session.turns) == 1
    assert session.turns[0].role == "user"


def test_parse_session_file_empty(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.write_text("")
    session = parse_session_file(f)
    assert session.turns == []
    assert session.bash_commands == []


# --- Session properties ---

def test_session_files_touched(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b.py"}},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/a/c.py"}},
        ]}},
    ])
    session = parse_session_file(f)
    assert set(session.files_touched) == {"/a/b.py", "/a/c.py"}


def test_session_tool_name_counts(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/x"}},
        ]}},
    ])
    session = parse_session_file(f)
    assert session.tool_name_counts == {"Bash": 2, "Read": 1}


# --- iter_session_files / load_all_sessions ---

def test_iter_session_files(tmp_path):
    proj = tmp_path / "proj1"
    proj.mkdir()
    (proj / "a.jsonl").write_text("")
    (proj / "b.jsonl").write_text("")
    (proj / "notes.txt").write_text("")
    files = list(iter_session_files(tmp_path))
    assert len(files) == 2
    assert all(f.suffix == ".jsonl" for f in files)


def test_iter_session_files_missing_dir(tmp_path):
    files = list(iter_session_files(tmp_path / "nonexistent"))
    assert files == []


def test_load_all_sessions(tmp_path):
    for name in ("s1", "s2", "s3"):
        f = tmp_path / f"{name}.jsonl"
        _write_jsonl(f, [{"message": {"role": "user", "content": name}}])
    sessions = load_all_sessions(tmp_path)
    assert len(sessions) == 3


def test_load_all_sessions_limit(tmp_path):
    for name in ("s1", "s2", "s3"):
        f = tmp_path / f"{name}.jsonl"
        _write_jsonl(f, [{"message": {"role": "user", "content": name}}])
    sessions = load_all_sessions(tmp_path, limit=2)
    assert len(sessions) == 2
