# SkillMind — Project Context for Claude Code

## What this project is

SkillMind is a CLI tool that observes Claude Code session logs, detects recurring
patterns (bash commands, tool-call sequences), and automatically generates SKILL.md
files from them. Think of it as "skills that write skills".

## Market context (researched June 2026)

- SKILL.md is now an open standard (agentskills.io, published Dec 2025 by Anthropic)
- 40+ agents support it: Claude Code, Codex CLI, Cursor, Gemini CLI, Copilot, VS Code...
- 1.9M+ public skills exist but average quality is only 6.2/12 (SkillsBench 2026)
- Closest competitor: Codex "Record & Replay" — manual, single-session, Codex-only
- No one has built automatic multi-session telemetry-driven skill generation yet
- Enterprise moat: 36% of public skills contain security issues (Snyk 2026)
  SkillMind is local-only — skills never leave the machine

## Architecture

```
skillmind/
├── telemetry/claude_code.py   # Parse ~/.claude/projects/**/*.jsonl
├── analyzer/patterns.py       # CommandPattern, ToolSequencePattern, analyze()
├── generator/skill_writer.py  # LLM-agnostic: Anthropic / OpenAI-compat / skeleton
├── adapters/                  # Phase 2: .cursorrules, copilot-instructions.md
└── cli.py                     # `skillmind scan` + `skillmind suggest`
```

## Key design decisions

- No API key = still useful (skeleton SKILL.md, scan always works)
- LLM priority: ANTHROPIC_API_KEY → OPENAI_API_KEY → SKILLMIND_OLLAMA → skeleton
- uv for package management — always use `uv run`, `uv add`, `uv sync`
- SKILL.md is canonical; adapters compile to agent-specific formats in phase 2

## CLI

```bash
uv run skillmind scan
uv run skillmind suggest --dry-run
uv run skillmind suggest --output ./skills --top-n 5
```

## Roadmap

### Phase 1 (current)
- [x] Telemetry parser, pattern analyzer, LLM-agnostic generator, CLI
- [ ] Test suite — tests/test_telemetry.py + tests/test_analyzer.py
- [ ] GitHub Actions CI
- [ ] PyPI publish

### Phase 2
- [ ] Cursor + Copilot adapter
- [ ] Team skill registry (git-based sync)
- [ ] Auto-PR on new skill detection

### Phase 3 (SaaS)
- [ ] Cross-session analytics dashboard
- [ ] Private registry with access control
- [ ] Marketplace push (Agensi integration)

## Next task for Claude Code

Write tests/test_telemetry.py and tests/test_analyzer.py, then .github/workflows/ci.yml
