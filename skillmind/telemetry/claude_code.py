"""
skillmind.telemetry.claude_code
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Parse Claude Code session JSONL logs from ~/.claude/projects/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass
class ToolCall:
    name: str
    input: dict
    session_id: str
    timestamp: datetime | None = None

    @property
    def command(self) -> str | None:
        return self.input.get("command")

    @property
    def file_path(self) -> str | None:
        return self.input.get("file_path") or self.input.get("path")


@dataclass
class Turn:
    role: str
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    session_id: str = ""
    timestamp: datetime | None = None


@dataclass
class Session:
    session_id: str
    project_path: str
    turns: list[Turn] = field(default_factory=list)

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [tc for turn in self.turns for tc in turn.tool_calls]

    @property
    def bash_commands(self) -> list[str]:
        return [tc.command for tc in self.tool_calls
                if tc.name == "Bash" and tc.command]

    @property
    def files_touched(self) -> list[str]:
        return [tc.file_path for tc in self.tool_calls if tc.file_path]

    @property
    def tool_name_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tc in self.tool_calls:
            counts[tc.name] = counts.get(tc.name, 0) + 1
        return counts


def _parse_timestamp(raw: dict) -> datetime | None:
    ts = raw.get("timestamp") or raw.get("ts")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _extract_text(content) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()


def _extract_tool_calls(content, session_id: str,
                         timestamp: datetime | None) -> list[ToolCall]:
    if not content:
        return []
    return [
        ToolCall(
            name=b.get("name", "unknown"),
            input=b.get("input", {}),
            session_id=session_id,
            timestamp=timestamp,
        )
        for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]


def parse_session_file(path: Path) -> Session:
    session_id = path.stem
    turns: list[Turn] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = raw.get("message") or raw
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content")
            ts = _parse_timestamp(raw)
            turns.append(Turn(
                role=role,
                text=_extract_text(content),
                tool_calls=_extract_tool_calls(
                    content if isinstance(content, list) else None,
                    session_id=session_id,
                    timestamp=ts,
                ),
                session_id=session_id,
                timestamp=ts,
            ))
    return Session(session_id=session_id, project_path=str(path.parent), turns=turns)


def iter_session_files(base_dir: Path | None = None) -> Iterator[Path]:
    if base_dir is None:
        base_dir = Path.home() / ".claude" / "projects"
    if not base_dir.exists():
        return
    yield from sorted(base_dir.rglob("*.jsonl"))


def load_all_sessions(base_dir: Path | None = None,
                      limit: int | None = None) -> list[Session]:
    sessions = []
    for i, path in enumerate(iter_session_files(base_dir)):
        if limit and i >= limit:
            break
        try:
            sessions.append(parse_session_file(path))
        except Exception as exc:
            print(f"[warn] could not parse {path}: {exc}")
    return sessions
